"""Relatório da coleta (ETAPA 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .collect import RawSnapshot
from .normalize import NormalizedResult

CHECK = "✓"


def build_report(raw: RawSnapshot, normalized: NormalizedResult, paths: dict[str, Path]) -> dict[str, Any]:
    counts = {name: len(rows) for name, rows in raw.data.items()}
    return {
        "meta": raw.meta,
        "counts": {
            "triggers": counts.get("triggers", 0),
            "hosts": counts.get("hosts", 0),
            "host_groups": counts.get("hostgroups", 0),
            "templates": counts.get("templates", 0),
            "items": counts.get("items", 0),
            "trigger_prototypes": counts.get("trigger_prototypes", 0),
            "dependency_triggers": counts.get("dependency_triggers", 0),
            "api_calls": len(raw.api_calls),
        },
        "normalization": normalized.stats,
        "collisions": normalized.collisions,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def format_report_lines(report: dict[str, Any]) -> list[str]:
    """Saída de console exigida pelo critério de conclusão da ETAPA 1."""
    counts = report["counts"]
    stats = report["normalization"]
    meta = report["meta"]
    paths = report["paths"]

    lines = [
        f"{CHECK} Conectado ao Zabbix (API {meta.get('zabbix_version', '?')}, {meta.get('auth_method', '?')})",
        f"{CHECK} {counts['triggers']} triggers encontrados",
        f"{CHECK} {counts['hosts']} hosts resolvidos",
        f"{CHECK} {counts['host_groups']} host groups resolvidos",
        f"{CHECK} {counts['templates']} templates resolvidos",
        f"{CHECK} {counts['items']} itens relacionados resolvidos",
        f"{CHECK} Snapshot bruto salvo -> {paths['raw']}",
        f"{CHECK} Alertas normalizados salvos -> {paths['alerts']}",
        f"{CHECK} {stats['unique_alert_keys']} alertas únicos",
        f"{CHECK} {stats['alert_key_collisions']} possíveis colisões de alert_key",
        "",
        "── Detalhamento ───────────────────────────────────────────────",
        f"  alertas normalizados          : {stats['alerts']}",
        f"  alert_keys únicas             : {stats['unique_alert_keys']}",
        f"  alert_keys com >1 trigger     : {stats['alert_keys_shared_by_multiple_triggers']} "
        "(esperado: mesmo trigger de template em vários hosts)",
        f"  triggers herdados de template : {stats['templated']}",
        f"  triggers criados por LLD      : {stats['discovered']}",
        f"  sem comentário no Zabbix      : {stats['without_comments']}",
        f"  sem tags                      : {stats['without_tags']}",
        f"  com dependências              : {stats['with_dependencies']}",
        f"  chamadas à API (read-only)    : {counts['api_calls']}",
        "",
        "  Severidade : " + ", ".join(f"{name}={qtd}" for name, qtd in stats["by_priority"].items()),
        "  Estratégia de alert_key : " + ", ".join(f"{name}={qtd}" for name, qtd in stats["by_key_strategy"].items()),
    ]

    familias = stats.get("families") or {}
    if familias.get("families"):
        lines.append("")
        lines.append("── Famílias de alertas (nível em que o procedimento é único) ──")
        lines.append(
            f"  {familias['alerts']} alertas se organizam em {familias['families']} famílias "
            f"({familias['alerts_in_multi_alert_families']} alertas em famílias com mais de um)"
        )
        for familia in stats.get("top_families", [])[:6]:
            lines.append(
                f"    {familia['alerts']:>5} alertas / {familia['hosts']:>3} hosts  "
                f"{familia['label'][:55]}  [{familia['origin'][:28]}]"
            )

    genericas = stats.get("generic_rules") or {}
    if genericas.get("rules_spanning_multiple_hosts"):
        lines.append("")
        lines.append("── Regras genéricas inferidas (mesma descrição + mesma expressão) ─")
        lines.append(f"  procedimentos distintos estimados : {genericas['estimated_distinct_procedures']}")
        lines.append(
            f"  regras que abrangem vários hosts   : {genericas['rules_spanning_multiple_hosts']} "
            f"({genericas['alerts_in_multi_host_rules']} alertas)"
        )
        lines.append(
            f"  fichas duplicadas evitáveis        : {genericas['duplicate_alert_keys_avoidable']} "
            "(se o escopo de template estivesse disponível)"
        )
        for regra in stats.get("top_generic_rules", [])[:5]:
            lines.append(
                f"    {regra['hosts']:>4} hosts / {regra['alert_keys']:>3} chaves  {regra['description'][:60]}"
            )

    if stats["top_shared_alert_keys"]:
        lines.append("")
        lines.append("── alert_keys compartilhadas por mais triggers ────────────────")
        for item in stats["top_shared_alert_keys"]:
            lines.append(f"  {item['triggers']:>4}x  {item['alert_key']}")

    if report["collisions"]:
        lines.append("")
        lines.append("── COLISÕES DE alert_key (mesma chave, triggers diferentes) ───")
        for collision in report["collisions"][:10]:
            motivos = collision.get("reasons") or ["expressoes_diferentes"]
            causas = []
            if "expressoes_diferentes" in motivos:
                causas.append(f"{collision['distinct_signatures']} expressões distintas")
            if "escopo_ambiguo" in motivos:
                causas.append(f"{collision['distinct_hostids']} hosts com o mesmo slug de escopo")
            if "duplicado_no_host" in motivos:
                total = sum(len(t) for t in (collision.get("duplicated_on_hosts") or {}).values())
                causas.append(f"{total} triggers distintos no mesmo host")
            lines.append(f"  ! {collision['alert_key']}  ({'; '.join(causas)})")
            for occ in collision["occurrences"][:4]:
                lines.append(
                    f"      - {occ['host']} (hostid {occ.get('hostid', '?')}, "
                    f"trigger {occ['triggerid']}, {occ['priority']}) :: {occ['description_raw']}"
                )
                lines.append(f"        {occ['expression_expanded'] or occ['expression_signature']}")
            if len(collision["occurrences"]) > 4:
                lines.append(f"      ... e mais {len(collision['occurrences']) - 4} ocorrência(s)")
            lines.append(f"      chave sugerida: {collision['suggested_key_pattern']}")
        if len(report["collisions"]) > 10:
            lines.append(f"  ... e mais {len(report['collisions']) - 10} colisão(ões) em {paths['collisions']}")
    else:
        lines.append("")
        lines.append("Nenhuma colisão de alert_key detectada nesta coleta.")

    lines.append("")
    lines.append(f"Snapshot completo em: {paths['snapshot_dir']}")
    return lines
