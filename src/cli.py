"""CLI mínima da ETAPA 1.

    python main.py collect        # coleta -> snapshot bruto + normalizado
    python main.py check          # apenas testa a conexão (read-only)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Sequence

from .collect import collect_raw
from .config import ConfigError, load_settings
from .normalize import normalize_snapshot
from .report import build_report, format_report_lines
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
