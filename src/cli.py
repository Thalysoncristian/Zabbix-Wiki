"""CLI do projeto.

    python main.py collect        # coleta -> snapshot bruto + normalizado
    python main.py check          # apenas testa a conexão (read-only)
    python main.py merge          # consolida vários snapshots numa base única
    python main.py serve          # interface web local de consulta
    python main.py scope          # hosts por volume: quem está dentro e fora do escopo
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

from .collect import RawSnapshot, collect_raw, partial_snapshot_of
from .config import ConfigError, load_settings
from .core.repository import AlertRepository
from .core.status import DOCUMENTED_STATUSES, UNDOCUMENTED
from .merge import merge_raw_snapshots
from .normalize import normalize_snapshot
from .progress import ConsoleProgress
from .reconcile import reconcile
from .report import CHECK, build_report, format_report_lines
from .snapshot import list_snapshots, load_raw_snapshot, write_json, write_partial_snapshot, write_snapshot
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
        help="restringe a coleta a um grupo de hosts (pode repetir, ou separar por vírgula)",
    )
    collect_cmd.add_argument(
        "--page-size",
        type=int,
        default=None,
        metavar="N",
        help="objetos por página na hidratação (padrão: ZABBIX_PAGE_SIZE do .env)",
    )
    collect_cmd.add_argument(
        "--split-by-group",
        action="store_true",
        help="grava um snapshot independente por grupo, em vez de um snapshot da execução",
    )
    collect_cmd.add_argument(
        "--merge",
        action="store_true",
        help="com --split-by-group: consolida os snapshots desta execução ao final",
    )
    collect_cmd.add_argument(
        "--resume",
        action="store_true",
        help="reaproveita os IDs já descobertos por uma coleta anterior do mesmo escopo",
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
        "--examples",
        type=int,
        default=0,
        metavar="N",
        help="imprime N alertas normalizados completos ao final (padrão: 0 — cada um tem ~80 linhas de JSON)",
    )
    collect_cmd.add_argument(
        "--no-redact",
        action="store_true",
        help="NÃO redigir segredos encontrados na configuração do Zabbix (não recomendado)",
    )
    collect_cmd.add_argument(
        "--full",
        action="store_true",
        help="relatório detalhado: mais colisões, mais famílias e expressões inteiras",
    )

    sub.add_parser("check", help="testa a conexão e as credenciais, sem coletar nada")

    mrg = sub.add_parser(
        "merge",
        help="consolida vários snapshots independentes num snapshot único (deduplicando por ID)",
    )
    mrg.add_argument(
        "snapshots",
        nargs="*",
        default=[],
        help="diretórios de snapshot a consolidar (padrão: todos os de output/snapshots)",
    )
    mrg.add_argument("--output", default=None, help="diretório dos snapshots (padrão: OUTPUT_DIR do .env)")
    mrg.add_argument("--full", action="store_true", help="relatório detalhado")
    mrg.add_argument(
        "--last",
        type=int,
        default=None,
        metavar="N",
        help="consolida apenas os N snapshots mais recentes",
    )

    srv = sub.add_parser("serve", help="sobe a interface web local de consulta (somente leitura)")
    srv.add_argument("--host", default="127.0.0.1",
                     help="endereço de escuta (padrão: 127.0.0.1 — só esta máquina)")
    srv.add_argument("--port", type=int, default=8000, help="porta (padrão: 8000)")
    srv.add_argument("--output", default=None, help="diretório dos snapshots (padrão: OUTPUT_DIR do .env)")
    srv.add_argument("--docs-dir", default=None, help="diretório das fichas (padrão: docs/alerts)")
    srv.add_argument("--snapshot", default=None,
                     help="caminho de um snapshot específico (padrão: o mais recente não-parcial)")
    srv.add_argument("--scopes-file", default=None,
                     help="arquivo de escopos operacionais (padrão: scopes.json)")

    esc = sub.add_parser(
        "scope",
        help="lista os escopos e os hosts por volume de alertas (dentro e fora)",
    )
    esc.add_argument("--scope", default=None, metavar="ID", help="escopo a avaliar (padrão: o de scopes.json)")
    esc.add_argument("--output", default=None, help="diretório dos snapshots (padrão: OUTPUT_DIR do .env)")
    esc.add_argument("--snapshot", default=None, help="snapshot específico (padrão: o mais recente não-parcial)")
    esc.add_argument("--scopes-file", default=None, help="arquivo de escopos (padrão: scopes.json)")
    esc.add_argument("--top", type=int, default=25, metavar="N", help="quantos hosts listar (padrão: 25)")

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


def _split_group_names(values: Sequence[str]) -> list[str]:
    """Aceita `--host-group A --host-group B` e `--host-group "A,B"`.

    As duas formas existem porque nomes de grupo com vírgula são raros, mas
    nomes com espaço são comuns — quem digita à mão prefere repetir a flag, e
    quem gera o comando por script prefere a lista.
    """
    nomes: list[str] = []
    for bruto in values:
        for parte in str(bruto).split(","):
            nome = parte.strip()
            if nome and nome not in nomes:
                nomes.append(nome)
    return nomes


def _known_trigger_ids(output_dir: str, host_groups: Sequence[str]) -> list[str]:
    """IDs de triggers já descobertos pela última coleta do mesmo escopo.

    Retomar aqui significa "não redescobrir", não "não rebaixar": os IDs são
    somados aos que a descoberta encontrar agora, e a hidratação confirma cada
    um. Um trigger apagado no Zabbix simplesmente não volta.
    """
    alvo = sorted(host_groups)
    for snapshot_dir in reversed(list_snapshots(output_dir)):
        try:
            payload = load_raw_snapshot(snapshot_dir)
        except (OSError, ValueError):
            continue
        meta = payload.get("meta") or {}
        grupos = sorted((meta.get("scope") or {}).get("host_groups") or [])
        if grupos == alvo and meta.get("discovered_trigger_ids"):
            print(f"→ Retomando a partir de {snapshot_dir.name}")
            return [str(i) for i in meta["discovered_trigger_ids"]]
    return []


def _gravar(output_dir: str, raw: RawSnapshot, examples: int, *, full: bool = False) -> dict[str, Any]:
    """Normaliza, grava o snapshot e imprime o relatório. Devolve o relatório."""
    normalized = normalize_snapshot(raw)
    paths = write_snapshot(output_dir, raw, normalized)
    report = build_report(raw, normalized, paths)
    paths["report"] = write_json(paths["snapshot_dir"] / "report.json", report)
    report["paths"]["report"] = str(paths["report"])

    print()
    print("\n".join(format_report_lines(report, full=full)))
    if not full:
        print("(relatório resumido — use --full para o detalhamento, ou -v para o progresso página a página)")
    _print_examples(normalized.alerts, examples)
    return report


def cmd_collect(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    output_dir = args.output or settings.output_dir
    host_groups = _split_group_names(args.host_group) or settings.host_groups
    page_size = args.page_size or settings.page_size

    print(f"→ Coletando de {settings.url} ({settings.auth_mode}, somente leitura)")
    print(f"→ Escopo: {', '.join(host_groups) if host_groups else 'ambiente inteiro (grupo a grupo)'}")
    print(f"→ Página: {page_size} objetos | retries: {settings.max_retries} | backoff: {settings.retry_backoff}s")

    if args.split_by_group and not host_groups:
        # Sem grupos explícitos, o próprio coletor já percorre grupo a grupo;
        # dividir em snapshots exigiria enumerar antes só para isso.
        raise ConfigError("--split-by-group exige pelo menos um --host-group.")
    if args.merge and not args.split_by_group:
        raise ConfigError("--merge só faz sentido junto com --split-by-group.")

    escopos: list[list[str]] = [[g] for g in host_groups] if args.split_by_group else [list(host_groups)]

    client = ZabbixReadOnlyClient.from_settings(settings)
    relatorios: list[dict[str, Any]] = []
    brutos: list[RawSnapshot] = []
    parcial = False
    try:
        for indice, escopo in enumerate(escopos, start=1):
            if len(escopos) > 1:
                print(f"\n=== Coleta {indice}/{len(escopos)}: {', '.join(escopo)} ===")
            progresso = ConsoleProgress(verbose=args.verbose)
            try:
                raw = collect_raw(
                    client,
                    host_groups=escopo,
                    limit=args.limit,
                    only_monitored=args.only_monitored,
                    include_template_triggers=args.include_template_triggers,
                    page_size=page_size,
                    known_trigger_ids=_known_trigger_ids(output_dir, escopo) if args.resume else (),
                    redact_secrets=settings.redact_secrets and not args.no_redact,
                    on_progress=progresso,
                )
            except BaseException as exc:
                # Interrupção não pode destruir o que já veio: o parcial vai para
                # um diretório próprio e os snapshots anteriores ficam intactos.
                parcial_raw = partial_snapshot_of(exc)
                if parcial_raw is not None:
                    destino = write_partial_snapshot(output_dir, parcial_raw, str(exc))
                    print(f"\n⚠ Coleta interrompida. Snapshot PARCIAL preservado em {destino}", file=sys.stderr)
                    print(
                        "  Ele NÃO é uma base válida — serve para auditoria e para retomar com --resume.",
                        file=sys.stderr,
                    )
                raise

            progresso.finish()
            redacao = raw.meta.get("redaction") or {}
            if redacao.get("values_redacted"):
                print(
                    f"  ⚠ {redacao['values_redacted']} valor(es) com aparência de segredo foram "
                    "redigidos. Eles estão em texto claro na configuração do Zabbix — "
                    "considere rotacioná-los."
                )
            brutos.append(raw)
            relatorios.append(_gravar(output_dir, raw, args.examples, full=args.full))
            parcial = parcial or bool((raw.meta.get("collection") or {}).get("partial"))
    finally:
        client.logout()

    if args.merge and len(brutos) > 1:
        print("\n=== Consolidando os snapshots desta execução ===")
        consolidado, resumo = merge_raw_snapshots([b.to_dict() for b in brutos])
        _gravar(output_dir, consolidado, 0, full=args.full)
        _print_merge_summary(resumo)
    elif len(escopos) > 1:
        print("\nPara consolidar estas coletas numa base única:")
        print(f"  python main.py merge --last {len(escopos)}")

    return EXIT_OK


def _print_merge_summary(resumo: dict[str, Any]) -> None:
    print()
    print("── Consolidação ───────────────────────────────────────────────")
    for fonte in resumo["sources"]:
        marca = "⚠ parcial" if fonte.get("partial") else "ok"
        print(f"  · {fonte.get('collected_at', '?')}  {fonte.get('scope', '?')}  [{marca}]")
    print(f"  objetos consolidados : {', '.join(f'{k}={v}' for k, v in resumo['counts'].items() if v)}")
    duplicados = resumo["duplicates_deduplicated"]
    print(
        "  duplicatas removidas : "
        + (", ".join(f"{k}={v}" for k, v in duplicados.items()) if duplicados else "nenhuma")
    )
    conflitos = resumo["conflicts"]
    if conflitos:
        print(f"  ⚠ conflitos (mesmo ID, conteúdo diferente): {len(conflitos)} — venceu a coleta mais recente")
        for conflito in conflitos[:3]:
            campos = ", ".join(conflito["field_hint"][:4]) or "?"
            print(f"    ! {conflito['collection']} {conflito['id']}: {campos}")
        if len(conflitos) > 3:
            print(f"    ... e mais {len(conflitos) - 3} conflito(s)")
    else:
        print("  conflitos            : nenhum")
    if resumo["partial_sources"]:
        print(f"  ⚠ {len(resumo['partial_sources'])} fonte(s) parcial(is) — a base consolidada também é parcial")
    if not resumo["complete_environment"]:
        print("  ⚠ Esta base NÃO representa o ambiente inteiro: cobre apenas os escopos listados acima.")


def cmd_merge(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    output_dir = args.output or settings.output_dir

    if args.snapshots:
        diretorios = [Path(caminho) for caminho in args.snapshots]
    else:
        diretorios = list_snapshots(output_dir)
        if args.last:
            diretorios = diretorios[-int(args.last):]
    # Snapshots já consolidados não entram de novo: reconsolidar um merge
    # inflaria as contagens de duplicata sem acrescentar nenhum objeto.
    if not args.snapshots:
        diretorios = [d for d in diretorios if "consolidado" not in d.name and "parcial" not in d.name]

    if len(diretorios) < 2:
        raise ConfigError(
            f"São necessários ao menos 2 snapshots para consolidar (encontrados: {len(diretorios)} em "
            f"{output_dir}/snapshots). Rode `python main.py collect --host-group ...` para outros grupos antes."
        )

    print(f"→ Consolidando {len(diretorios)} snapshots de {output_dir}/snapshots")
    payloads = []
    for diretorio in diretorios:
        print(f"  · {diretorio.name}")
        try:
            payloads.append(load_raw_snapshot(diretorio))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Snapshot inválido em {diretorio}: {exc}") from exc

    consolidado, resumo = merge_raw_snapshots(payloads)
    _gravar(output_dir, consolidado, 0, full=args.full)
    _print_merge_summary(resumo)
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


def cmd_serve(args: argparse.Namespace) -> int:
    """Sobe a interface web.

    Este processo NÃO abre conexão com o Zabbix e não lê as credenciais: ele
    serve o snapshot que já está em disco. `load_settings` é usado só para
    descobrir o diretório de saída — por isso a ausência de token não impede
    a interface de subir.
    """
    from .web.server import serve_forever

    try:
        settings = load_settings(args.env_file)
        output_dir = args.output or settings.output_dir
    except ConfigError:
        # Sem .env configurado a interface ainda funciona: ela só precisa dos
        # arquivos do snapshot.
        output_dir = args.output or "output"

    docs_dir = args.docs_dir or "docs/alerts"

    print(f"→ Snapshots : {output_dir}/snapshots")
    print(f"→ Fichas    : {docs_dir}")
    print("→ Somente leitura: este processo não acessa o Zabbix nem lê credenciais.")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"⚠ Escutando em {args.host}: qualquer pessoa na rede poderá ver toda a "
            "configuração de monitoramento, sem senha.",
            file=sys.stderr,
        )

    def pronto(url: str) -> None:
        print(f"\n  Interface em {url}")
        print("  Ctrl+C para encerrar.\n")

    try:
        serve_forever(
            output_dir=output_dir, docs_dir=docs_dir, snapshot=args.snapshot,
            host=args.host, port=args.port, on_ready=pronto, scopes_file=args.scopes_file,
        )
    except OSError as exc:
        raise ConfigError(f"Não foi possível abrir {args.host}:{args.port} — {exc}") from exc
    return EXIT_OK


def cmd_scope(args: argparse.Namespace) -> int:
    """Mostra o efeito do escopo sobre o snapshot, host a host.

    Existe para que a decisão de excluir um host seja tomada com o volume na
    frente, e não por semelhança de nome. Excluir "Control-M DEV" porque
    "Control-M PRD" foi excluído é palpite; ver que ele tem 12 alertas (ou
    3.000) é informação.
    """
    from .scope import load_scopes
    from .web.readmodel import ReadModel, resolve_snapshot

    try:
        settings = load_settings(args.env_file)
        output_dir = args.output or settings.output_dir
    except ConfigError:
        output_dir = args.output or "output"

    configuracao = load_scopes(args.scopes_file)
    escopo = configuracao.get(args.scope)
    caminho = resolve_snapshot(output_dir, args.snapshot)
    modelo = ReadModel(caminho, docs_dir="docs/alerts", scope=escopo)

    ambiente = modelo.environment
    dentro, fora = len(modelo.alerts), len(modelo.out_of_scope)

    print(f"→ Snapshot : {caminho.name}")
    print(f"→ Escopos  : {configuracao.source or '(nenhum scopes.json — só o ambiente inteiro)'}")
    print()
    print("── Escopos configurados ───────────────────────────────────────")
    for item in configuracao.listar():
        marca = "→" if item["id"] == escopo.id else " "
        padrao = " (padrão)" if item["is_default"] else ""
        regra = ", ".join(item["exclude_hosts"] + item["exclude_host_patterns"]
                          + item["include_hosts"] + item["include_host_patterns"]) or "sem filtro"
        print(f"  {marca} {item['id']:<12} {item['label']:<20}{padrao}")
        print(f"      {item['mode']}: {regra[:90]}")

    print()
    print(f"── Efeito do escopo '{escopo.id}' ──────────────────────────────")
    print(f"  ambiente coletado : {ambiente['alerts']:>7} alertas, {ambiente['hosts']:>4} hosts, "
          f"{ambiente['families']:>4} famílias")
    print(f"  dentro do escopo  : {dentro:>7} alertas, {len(modelo.hosts):>4} hosts, "
          f"{len(modelo.families):>4} famílias")
    proporcao = (fora / ambiente["alerts"] * 100) if ambiente["alerts"] else 0
    print(f"  fora do escopo    : {fora:>7} alertas ({proporcao:.0f}% do ambiente)")

    # Hosts por volume, com o veredito do escopo em cada linha. Esta é a
    # tabela que a decisão de exclusão precisa.
    por_host: dict[str, dict[str, Any]] = {}
    for alerta in modelo.alerts + modelo.out_of_scope:
        zbx = alerta.get("zabbix") or {}
        host = zbx.get("host") or {}
        nome = host.get("name") or host.get("host") or "(sem host)"
        registro = por_host.setdefault(nome, {"alertas": 0, "tecnico": host.get("host") or "", "lld": 0})
        registro["alertas"] += 1
        if zbx.get("discovered"):
            registro["lld"] += 1

    ordenados = sorted(por_host.items(), key=lambda kv: -kv[1]["alertas"])
    print()
    print(f"── Hosts por volume (top {args.top}) ───────────────────────────────")
    print(f"  {'alertas':>8} {'LLD':>7}  {'%amb':>5}  escopo    host")
    for nome, registro in ordenados[: max(1, args.top)]:
        no_escopo = escopo.includes_host(nome, registro["tecnico"])
        pct = registro["alertas"] / ambiente["alerts"] * 100 if ambiente["alerts"] else 0
        print(f"  {registro['alertas']:>8} {registro['lld']:>7}  {pct:>4.0f}%  "
              f"{'dentro' if no_escopo else 'FORA  '}    {nome[:60]}")
    if len(ordenados) > args.top:
        print(f"  ... e mais {len(ordenados) - args.top} host(s). Use --top para ver mais.")

    print()
    print("Para excluir um host do escopo, edite scopes.json e rode este comando de novo.")
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
        if args.command == "merge":
            return cmd_merge(args)
        if args.command == "serve":
            return cmd_serve(args)
        if args.command == "scope":
            return cmd_scope(args)
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
