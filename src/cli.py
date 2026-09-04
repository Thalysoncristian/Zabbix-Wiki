"""CLI do projeto.

    python main.py collect        # coleta -> snapshot bruto + normalizado
    python main.py check          # apenas testa a conexão (read-only)
    python main.py reconcile      # snapshot -> fichas em docs/alerts/
    python main.py status         # cobertura da documentação
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .collect import collect_raw
from .config import ConfigError, load_settings
from .core.repository import AlertRepository
from .core.status import DOCUMENTED_STATUSES, UNDOCUMENTED
from .normalize import normalize_snapshot
from .reconcile import reconcile
from .report import CHECK, build_report, format_report_lines
from .snapshot import write_json, write_snapshot
from .zabbix_client import ZabbixError, ZabbixReadOnlyClient

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_ZABBIX = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Base de conhecimento operacional de alertas Zabbix — ETAPA 1 (coleta read-only).",
    )
    parser.add_argument("--env-file", default=".env", help="arquivo de variáveis (padrão: .env)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log detalhado (DEBUG)")
    sub = parser.add_subparsers(dest="command", required=True)

    collect_cmd = sub.add_parser("collect", help="coleta os alertas do Zabbix e grava um snapshot")
    collect_cmd.add_argument("--output", default=None, help="diretório de saída (padrão: OUTPUT_DIR do .env)")
    collect_cmd.add_argument("--limit", type=int, default=None, help="limita a quantidade de triggers (testes)")
    collect_cmd.add_argument(
        "--host-group",
        action="append",
        default=[],
        metavar="NOME",
        help="restringe a coleta a um grupo de hosts (pode repetir)",
    )
    collect_cmd.add_argument(
        "--only-monitored", action="store_true", help="apenas triggers habilitados em hosts monitorados"
    )
    collect_cmd.add_argument(
        "--include-template-triggers",
        action="store_true",
        help="inclui também os triggers definidos nos templates (por padrão só os dos hosts)",
    )
    collect_cmd.add_argument(
        "--examples", type=int, default=2, metavar="N", help="quantos alertas de exemplo imprimir ao final (padrão: 2)"
    )

    sub.add_parser("check", help="testa a conexão e as credenciais, sem coletar nada")

    rec = sub.add_parser(
        "reconcile",
        help="aplica um snapshot sobre as fichas em docs/alerts/ (nunca sobrescreve documentação)",
    )
    rec.add_argument(
        "snapshot",
        nargs="?",
        default=None,
        help="caminho do alerts.json ou do diretório do snapshot (padrão: o mais recente)",
    )
    rec.add_argument("--docs-dir", default=None, help="diretório das fichas (padrão: docs/alerts)")
    rec.add_argument("--output", default=None, help="diretório dos snapshots (padrão: OUTPUT_DIR do .env)")
    rec.add_argument(
        "--no-prune",
        action="store_true",
        help="não marcar como ausentes as fichas que não apareceram nesta coleta",
    )
    rec.add_argument("--dry-run", action="store_true", help="mostra o que faria, sem gravar nada")

    st = sub.add_parser("status", help="cobertura da documentação nas fichas")
    st.add_argument("--docs-dir", default=None, help="diretório das fichas (padrão: docs/alerts)")
    return parser


def _print_examples(alerts: list[dict[str, Any]], quantity: int) -> None:
    if quantity <= 0 or not alerts:
        return

    # Diversifica: um exemplo por estratégia de alert_key, depois completa.
    chosen: list[dict[str, Any]] = []
    seen_strategies: set[str] = set()
    for alert in alerts:
        if alert["alert_key_strategy"] not in seen_strategies:
            seen_strategies.add(alert["alert_key_strategy"])
            chosen.append(alert)
        if len(chosen) >= quantity:
            break
    for alert in alerts:
        if len(chosen) >= quantity:
            break
        if alert not in chosen:
            chosen.append(alert)

    print("\n── Exemplos de alertas normalizados ───────────────────────────")
    for alert in chosen[:quantity]:
        print(json.dumps(alert, indent=2, ensure_ascii=False))
        print()


def cmd_collect(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    output_dir = args.output or settings.output_dir
    host_groups = args.host_group or settings.host_groups

    print(f"→ Coletando de {settings.url} ({settings.auth_mode}, somente leitura)")

    client = ZabbixReadOnlyClient.from_settings(settings)
    try:
        raw = collect_raw(
            client,
            host_groups=host_groups,
            limit=args.limit,
            only_monitored=args.only_monitored,
            include_template_triggers=args.include_template_triggers,
            on_step=lambda message: print(f"  · {message}"),
        )
    finally:
        client.logout()

    normalized = normalize_snapshot(raw)
    paths = write_snapshot(output_dir, raw, normalized)
    report = build_report(raw, normalized, paths)
    paths["report"] = write_json(paths["snapshot_dir"] / "report.json", report)
    report["paths"]["report"] = str(paths["report"])

    print()
    print("\n".join(format_report_lines(report)))
    _print_examples(normalized.alerts, args.examples)
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    client = ZabbixReadOnlyClient.from_settings(settings)
    try:
        version = client.connect()
        print(f"✓ Conectado ao Zabbix (API {version}, {client.auth_description})")
        print(f"  endpoint : {client.endpoint}")
        print(f"  config   : {settings.describe()}")
        totais: dict[str, str] = {}
        for label, method in (
            ("host groups", "hostgroup.get"),
            ("hosts", "host.get"),
            ("triggers", "trigger.get"),
            ("templates", "template.get"),
        ):
            total = str(client.call(method, {"countOutput": True}))
            totais[label] = total
            print(f"  {label:<12}: {total} visíveis para estas credenciais")

        if totais.get("templates") in ("0", "None", ""):
            print()
            print("⚠ Nenhum template visível para estas credenciais.")
            print("  No Zabbix, o acesso a templates é concedido por grupos de templates e")
            print("  costuma faltar para usuários somente leitura. Sem isso, a coleta não")
            print("  consegue identificar que um alerta é regra genérica de template — todo")
            print("  alerta vira específico do host, e a documentação teria de ser repetida")
            print("  host a host na ETAPA 2.")
            print("  Peça ao admin do Zabbix acesso de leitura aos grupos de templates.")
    finally:
        client.logout()
    return EXIT_OK


def _latest_snapshot(output_dir: str) -> Path | None:
    raiz = Path(output_dir) / "snapshots"
    if not raiz.is_dir():
        return None
    candidatos = [d for d in raiz.iterdir() if d.is_dir() and not d.is_symlink()]
    return max(candidatos, key=lambda d: d.name) if candidatos else None


def _resolve_snapshot_file(argumento: str | None, output_dir: str) -> Path:
    """Aceita o alerts.json, o diretório do snapshot, ou nada (o mais recente)."""
    if argumento:
        caminho = Path(argumento)
        if caminho.is_file():
            return caminho
        if caminho.is_dir():
            return caminho / "normalized" / "alerts.json"
        raise ConfigError(f"Snapshot não encontrado: {argumento}")

    recente = _latest_snapshot(output_dir)
    if recente is None:
        raise ConfigError(
            f"Nenhum snapshot em {output_dir}/snapshots. Rode `python main.py collect` antes."
        )
    return recente / "normalized" / "alerts.json"


def cmd_reconcile(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    caminho = _resolve_snapshot_file(args.snapshot, args.output or settings.output_dir)
    if not caminho.is_file():
        raise ConfigError(f"Arquivo de alertas normalizados não encontrado: {caminho}")

    payload = json.loads(caminho.read_text(encoding="utf-8"))
    alertas = payload.get("alerts") or []
    grupos_do_escopo = ((payload.get("meta") or {}).get("filters") or {}).get("host_groups") or []

    docs_dir = args.docs_dir or "docs/alerts"
    print(f"→ Snapshot : {caminho}")
    print(f"→ Fichas   : {docs_dir}")
    print(f"→ Escopo   : {', '.join(grupos_do_escopo) if grupos_do_escopo else 'ambiente completo'}")
    if args.dry_run:
        print("→ SIMULAÇÃO: nada será gravado")

    repositorio = AlertRepository(tempfile.mkdtemp() if args.dry_run else docs_dir)
    if args.dry_run:
        # Copia o estado atual para um diretório temporário, para simular sem tocar no real.
        origem = AlertRepository(docs_dir)
        for doc in origem.all():
            repositorio.save(doc)

    resultado = reconcile(
        alertas,
        repositorio,
        prune_missing=not args.no_prune,
        scope_host_groups=grupos_do_escopo,
    )

    resumo = resultado.summary()
    print()
    print(f"{CHECK} {len(alertas)} alertas do snapshot processados")
    print(f"{CHECK} {resumo['created']} fichas novas criadas (🆕 novo alerta)")
    print(f"{CHECK} {resumo['technical_updated']} com o fato técnico alterado no Zabbix")
    print(f"{CHECK} {resumo['marked_review_needed']} marcadas como review_needed")
    print(f"{CHECK} {resumo['reappeared']} voltaram a aparecer no Zabbix")
    print(f"{CHECK} {resumo['disappeared']} sumiram da coleta (ficha preservada)")
    print(f"{CHECK} {resumo['unchanged']} sem alteração técnica")

    for chave in resultado.created[:10]:
        print(f"    🆕 {chave}")
    if len(resultado.created) > 10:
        print(f"    ... e mais {len(resultado.created) - 10} ficha(s) nova(s)")
    for item in resultado.marked_review_needed[:10]:
        print(f"    ⚠ review_needed: {item['alert_key']}")

    if args.dry_run:
        print("\nSimulação concluída — nenhuma ficha real foi alterada.")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    repositorio = AlertRepository(args.docs_dir or "docs/alerts")
    fichas = list(repositorio.all())
    if not fichas:
        print("Nenhuma ficha em docs/alerts/. Rode `python main.py reconcile` depois de uma coleta.")
        return EXIT_OK

    por_status: dict[str, int] = {}
    por_nivel: dict[str, int] = {}
    for doc in fichas:
        por_status[doc.doc_status] = por_status.get(doc.doc_status, 0) + 1
        por_nivel[doc.doc_level] = por_nivel.get(doc.doc_level, 0) + 1

    documentadas = sum(qtd for st, qtd in por_status.items() if st in DOCUMENTED_STATUSES)
    cobertura = documentadas / len(fichas) * 100

    print(f"Fichas       : {len(fichas)}")
    print(f"Cobertura    : {documentadas}/{len(fichas)} ({cobertura:.1f}%) documentadas ou revisadas")
    print(f"Instâncias   : {por_nivel.get('instance', 0)}   Famílias: {por_nivel.get('family', 0)}")
    print(f"Ausentes     : {sum(1 for d in fichas if not d.present_in_zabbix)} não vistas na última coleta do escopo")
    print()
    for status, qtd in sorted(por_status.items(), key=lambda kv: (-kv[1], kv[0])):
        marcador = "🆕" if status == UNDOCUMENTED else "  "
        print(f"  {marcador} {status:<16} {qtd}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.command == "collect":
            return cmd_collect(args)
        if args.command == "check":
            return cmd_check(args)
        if args.command == "reconcile":
            return cmd_reconcile(args)
        if args.command == "status":
            return cmd_status(args)
    except ConfigError as exc:
        print(f"✗ Configuração inválida: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except ZabbixError as exc:
        print(f"✗ Erro na comunicação com o Zabbix: {exc}", file=sys.stderr)
        return EXIT_ZABBIX
    except KeyboardInterrupt:  # pragma: no cover
        print("\n✗ Interrompido pelo usuário.", file=sys.stderr)
        return 130

    build_parser().print_help()
    return EXIT_CONFIG
