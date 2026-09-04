"""Normalização: snapshot bruto -> alertas autocontidos.

Regra central: o JSON normalizado não pode depender de IDs para ser
compreensível. Nomes de host, grupos, templates e itens já vêm resolvidos.
IDs continuam presentes apenas como referência técnica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .collect import RawSnapshot
from .keys import (
    build_alert_key,
    compute_source_hash,
    expression_signature,
    normalize_description,
    short_hash,
)

PRIORITY_NAMES = {
    "0": "Not classified",
    "1": "Information",
    "2": "Warning",
    "3": "Average",
    "4": "High",
    "5": "Disaster",
}
TRIGGER_STATUS_NAMES = {"0": "enabled", "1": "disabled"}
TRIGGER_VALUE_NAMES = {"0": "OK", "1": "PROBLEM"}
TRIGGER_STATE_NAMES = {"0": "normal", "1": "unknown"}
RECOVERY_MODE_NAMES = {"0": "expression", "1": "recovery expression", "2": "none"}
HOST_STATUS_NAMES = {"0": "monitored", "1": "not monitored", "3": "template"}
ITEM_VALUE_TYPE_NAMES = {
    "0": "numeric float",
    "1": "character",
    "2": "log",
    "3": "numeric unsigned",
    "4": "text",
    "5": "binary",
}
HOST_STATUS_TEMPLATE = "3"
TRIGGER_FLAG_DISCOVERED = "4"

#: Campos de inventário que fazem sentido para operação (o resto é descartado).
INVENTORY_FIELDS = (
    "type",
    "type_full",
    "name",
    "alias",
    "os",
    "os_full",
    "location",
    "site_city",
    "contact",
    "notes",
    "tag",
    "poc_1_name",
    "poc_1_email",
    "poc_1_phone_a",
    "poc_2_name",
    "poc_2_email",
)


def _enum(value: Any, names: dict[str, str]) -> dict[str, str]:
    raw = "" if value is None else str(value)
    return {"value": raw, "name": names.get(raw, "unknown")}


def _as_bool(value: Any) -> bool:
    return str(value) in ("1", "true", "True")


def _index(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(key)): row for row in rows if row.get(key) is not None}


def _entity_display_name(row: dict[str, Any]) -> str:
    """Nome visível de host/template (`name`), caindo para o nome técnico."""
    return str(row.get("name") or row.get("host") or "").strip()


@dataclass
class NormalizedResult:
    alerts: list[dict[str, Any]] = field(default_factory=list)
    key_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    collisions: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def normalize_snapshot(raw: RawSnapshot | dict[str, Any]) -> NormalizedResult:
    """Converte o snapshot bruto em uma lista de alertas normalizados."""
    payload = raw.to_dict() if isinstance(raw, RawSnapshot) else raw
    meta = payload.get("meta", {})
    data = payload.get("data", {})

    triggers = data.get("triggers") or []
    expanded_index = _index(data.get("triggers_expanded") or [], "triggerid")
    parent_index = _index(data.get("parent_triggers") or [], "triggerid")
    prototype_index = _index(data.get("trigger_prototypes") or [], "triggerid")
    dependency_index = _index(data.get("dependency_triggers") or [], "triggerid")
    host_index = _index(data.get("hosts") or [], "hostid")
    group_index = {str(r.get("groupid")): str(r.get("name") or "") for r in data.get("hostgroups") or []}
    template_index = _index(data.get("templates") or [], "templateid")
    item_index = _index(data.get("items") or [], "itemid")

    collected_at = meta.get("collected_at", "")
    zabbix_version = meta.get("zabbix_version", "")

    alerts: list[dict[str, Any]] = []
    for trigger in triggers:
        alerts.append(
            _normalize_trigger(
                trigger,
                expanded_index=expanded_index,
                parent_index=parent_index,
                prototype_index=prototype_index,
                dependency_index=dependency_index,
                host_index=host_index,
                group_index=group_index,
                template_index=template_index,
                item_index=item_index,
                collected_at=collected_at,
                zabbix_version=zabbix_version,
            )
        )

    key_index, collisions = analyze_keys(alerts)
    for alert in alerts:
        entry = key_index[alert["alert_key"]]
        alert["alert_key_collision"] = entry["collision"]
        alert["alert_key_suggested"] = (
            f"{alert['alert_key']}#{short_hash(alert['zabbix']['expression_signature'])}"
            if entry["collision"]
            else None
        )

    return NormalizedResult(
        alerts=alerts,
        key_index=key_index,
        collisions=collisions,
        stats=build_stats(alerts, key_index, collisions),
    )


def _normalize_trigger(
    trigger: dict[str, Any],
    *,
    expanded_index: dict[str, dict[str, Any]],
    parent_index: dict[str, dict[str, Any]],
    prototype_index: dict[str, dict[str, Any]],
    dependency_index: dict[str, dict[str, Any]],
    host_index: dict[str, dict[str, Any]],
    group_index: dict[str, str],
    template_index: dict[str, dict[str, Any]],
    item_index: dict[str, dict[str, Any]],
    collected_at: str,
    zabbix_version: str,
) -> dict[str, Any]:
    triggerid = str(trigger.get("triggerid") or "")
    description_raw = str(trigger.get("description") or "")

    # ------------------------------------------------------------------- host
    trigger_hosts = trigger.get("hosts") or []
    host_stub = trigger_hosts[0] if trigger_hosts else {}
    host_row = host_index.get(str(host_stub.get("hostid")), host_stub) or {}
    host_aliases = tuple(
        {str(host_row.get("host") or ""), str(host_row.get("name") or ""), str(host_stub.get("host") or "")}
    )

    # ------------------------------------------------------------- expressões
    expanded = expanded_index.get(triggerid, {})
    expression_raw = str(trigger.get("expression") or "")
    expression_expanded = str(expanded.get("expression") or "")
    recovery_raw = str(trigger.get("recovery_expression") or "")
    recovery_expanded = str(expanded.get("recovery_expression") or "")

    # --------------------------------------------------- template de origem
    source_template = _resolve_source_template(trigger, parent_index, template_index)

    # ------------------------------------------------------ protótipo (LLD)
    discovered = str(trigger.get("flags") or "0") == TRIGGER_FLAG_DISCOVERED
    prototype = _resolve_prototype(trigger, prototype_index, template_index)

    # ------------------------------------------------------------ alert_key
    scope, basis_description, strategy = _resolve_key_scope(
        host_row=host_row,
        source_template=source_template,
        prototype=prototype,
        description_raw=description_raw,
    )
    alert_key = build_alert_key(scope["name"], basis_description, triggerid=triggerid)

    # ---------------------------------------------------------------- itens
    items = []
    for item_stub in trigger.get("items") or []:
        itemid = str(item_stub.get("itemid") or "")
        item_row = {**item_stub, **item_index.get(itemid, {})}
        items.append(
            {
                "itemid": itemid,
                "key_": str(item_row.get("key_") or ""),
                "name": str(item_row.get("name_resolved") or item_row.get("name") or ""),
                "units": str(item_row.get("units") or ""),
                "value_type": _enum(item_row.get("value_type"), ITEM_VALUE_TYPE_NAMES),
                "update_interval": str(item_row.get("delay") or ""),
            }
        )
    items.sort(key=lambda i: (i["key_"], i["itemid"]))

    # ---------------------------------------------------------- dependências
    dependencies = []
    for dep in trigger.get("dependencies") or []:
        depid = str(dep.get("triggerid") or "")
        dep_row = dependency_index.get(depid, dep)
        dep_hosts = dep_row.get("hosts") or []
        dependencies.append(
            {
                "triggerid": depid,
                "description": str(dep_row.get("description") or ""),
                "host": _entity_display_name(dep_hosts[0]) if dep_hosts else "",
            }
        )
    dependencies.sort(key=lambda d: (d["host"], d["description"]))

    # ------------------------------------------------------------------ tags
    tags = sorted(
        ({"tag": str(t.get("tag") or ""), "value": str(t.get("value") or "")} for t in trigger.get("tags") or []),
        key=lambda t: (t["tag"], t["value"]),
    )

    host_groups = _resolve_host_groups(host_row, group_index)
    templates = _resolve_host_templates(host_row, template_index)

    expr_signature = expression_signature(expression_expanded or expression_raw, host_aliases)
    recovery_signature = expression_signature(recovery_expanded or recovery_raw, host_aliases)

    zabbix_block: dict[str, Any] = {
        "triggerid": triggerid,
        "description_raw": description_raw,
        "description_normalized": normalize_description(description_raw),
        "expression_raw": expression_raw,
        "expression_expanded": expression_expanded,
        "expression_signature": expr_signature,
        "recovery_mode": _enum(trigger.get("recovery_mode"), RECOVERY_MODE_NAMES),
        "recovery_expression_raw": recovery_raw,
        "recovery_expression_expanded": recovery_expanded,
        "priority": _enum(trigger.get("priority"), PRIORITY_NAMES),
        "status": _enum(trigger.get("status"), TRIGGER_STATUS_NAMES),
        "value": _enum(trigger.get("value"), TRIGGER_VALUE_NAMES),
        "state": _enum(trigger.get("state"), TRIGGER_STATE_NAMES),
        "opdata": str(trigger.get("opdata") or ""),
        "event_name": str(trigger.get("event_name") or ""),
        "comments": str(trigger.get("comments") or ""),
        "manual_close": _as_bool(trigger.get("manual_close")),
        "templated": bool(source_template),
        "source_template": source_template["name"] if source_template else None,
        "discovered": discovered,
        "discovery_rule": _discovery_rule(trigger),
        "prototype_description": prototype["description"] if prototype else None,
        "dependencies": dependencies,
        "tags": tags,
        "host": {
            "hostid": str(host_row.get("hostid") or ""),
            "host": str(host_row.get("host") or ""),
            "name": _entity_display_name(host_row),
            "status": _enum(host_row.get("status"), HOST_STATUS_NAMES),
            "inventory": _prune_inventory(host_row.get("inventory")),
        },
        "host_groups": host_groups,
        "templates": templates,
        "items": items,
        "zabbix_version": zabbix_version,
        "collected_at": collected_at,
    }

    zabbix_block["source_hash"] = compute_source_hash(
        {
            "description_raw": description_raw,
            "expression_signature": expr_signature,
            "recovery_mode": zabbix_block["recovery_mode"]["value"],
            "recovery_expression_signature": recovery_signature,
            "priority": zabbix_block["priority"]["value"],
            "opdata": zabbix_block["opdata"],
            "event_name": zabbix_block["event_name"],
            "comments": zabbix_block["comments"],
            "manual_close": zabbix_block["manual_close"],
            "tags": [f"{t['tag']}={t['value']}" for t in tags],
            "items": [f"{i['key_']}|{i['units']}|{i['value_type']['value']}" for i in items],
            "host": zabbix_block["host"]["host"],
            "host_groups": host_groups,
            "templates": templates,
            "source_template": zabbix_block["source_template"],
        }
    )

    return {
        "alert_key": alert_key,
        "alert_key_strategy": strategy,
        "alert_key_scope": scope,
        "alert_key_basis_description": basis_description,
        "alert_key_collision": False,
        "alert_key_suggested": None,
        "scope": "zabbix",
        "zabbix": zabbix_block,
    }


def _discovery_rule(trigger: dict[str, Any]) -> dict[str, str] | None:
    rule = trigger.get("discoveryRule") or {}
    if not rule:
        return None
    return {
        "itemid": str(rule.get("itemid") or ""),
        "name": str(rule.get("name") or ""),
        "key_": str(rule.get("key_") or ""),
    }


def _resolve_source_template(
    trigger: dict[str, Any],
    parent_index: dict[str, dict[str, Any]],
    template_index: dict[str, dict[str, Any]],
) -> dict[str, str] | None:
    """Sobe a cadeia `templateid` e devolve o template que define o trigger."""
    current = str(trigger.get("templateid") or "0")
    last_row: dict[str, Any] | None = None
    seen: set[str] = set()

    while current not in ("", "0") and current in parent_index and current not in seen:
        seen.add(current)
        last_row = parent_index[current]
        current = str(last_row.get("templateid") or "0")

    if not last_row:
        return None
    return _owner_entity(last_row, template_index)


def _resolve_prototype(
    trigger: dict[str, Any],
    prototype_index: dict[str, dict[str, Any]],
    template_index: dict[str, dict[str, Any]],
) -> dict[str, str] | None:
    """Resolve o protótipo (trigger prototype) de um trigger criado por LLD.

    A descrição do protótipo mantém as macros de descoberta (`{#FSNAME}`), o que
    a torna uma base de chave muito mais estável do que a descrição já expandida
    do trigger descoberto.
    """
    discovery = trigger.get("triggerDiscovery") or {}
    current = str(discovery.get("parent_triggerid") or "0")
    row: dict[str, Any] | None = None
    seen: set[str] = set()

    while current not in ("", "0") and current in prototype_index and current not in seen:
        seen.add(current)
        row = prototype_index[current]
        current = str(row.get("templateid") or "0")

    if not row:
        return None
    owner = _owner_entity(row, template_index)
    return {
        "triggerid": str(row.get("triggerid") or ""),
        "description": str(row.get("description") or ""),
        "owner_name": owner["name"],
        "owner_type": owner["type"],
        "owner_id": owner["id"],
    }


def _owner_entity(row: dict[str, Any], template_index: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Host/template dono de um trigger (via `selectHosts`)."""
    hosts = row.get("hosts") or []
    owner = hosts[0] if hosts else {}
    owner_id = str(owner.get("hostid") or "")
    template_row = template_index.get(owner_id)
    name = _entity_display_name(template_row or owner)
    is_template = str(owner.get("status") or "") == HOST_STATUS_TEMPLATE or template_row is not None
    return {"type": "template" if is_template else "host", "name": name, "id": owner_id}


def _resolve_key_scope(
    *,
    host_row: dict[str, Any],
    source_template: dict[str, str] | None,
    prototype: dict[str, str] | None,
    description_raw: str,
) -> tuple[dict[str, str], str, str]:
    """Decide o escopo e a descrição-base usados na `alert_key`.

    Prioridade (do mais estável para o menos estável):
      1. protótipo de LLD (template/host dono do protótipo + descrição JÁ
         EXPANDIDA do próprio trigger, não o texto cru do protótipo);
      2. template de origem do trigger herdado;
      3. host (trigger local, criado direto no host).

    Por que a descrição expandida, e não `prototype["description"]`: o texto
    cru do protótipo (`"{#SERVICE.NAME}" ({#SERVICE.DISPLAYNAME}) is not
    running`) tem duas macros que a normalização reduz ao mesmo marcador —
    então TODOS os serviços descobertos em um host (Windows Audio, AWS SSM
    Agent, firewall...) colidiriam na mesma chave, apesar de serem alertas
    operacionalmente distintos. A descrição já expandida do trigger contém o
    nome real da entidade descoberta (`"AudioEndpointBuilder" (...) is not
    running`), o que produz uma chave por entidade. O escopo continua vindo do
    protótipo (host/template dono), o que preserva a chave estável mesmo que
    o triggerid mude numa redescoberta.
    """
    if prototype and prototype["owner_name"]:
        return (
            {"type": prototype["owner_type"], "name": prototype["owner_name"], "id": prototype["owner_id"]},
            description_raw,
            "prototype+description",
        )
    if source_template and source_template["name"]:
        return source_template, description_raw, "template+description"
    return (
        {
            "type": "host",
            "name": str(host_row.get("host") or _entity_display_name(host_row)),
            "id": str(host_row.get("hostid") or ""),
        },
        description_raw,
        "host+description",
    )


def _resolve_host_groups(host_row: dict[str, Any], group_index: dict[str, str]) -> list[str]:
    names: set[str] = set()
    for group in (host_row.get("hostgroups") or []) + (host_row.get("groups") or []):
        gid = str(group.get("groupid") or "")
        name = str(group.get("name") or "") or group_index.get(gid, "")
        if name:
            names.add(name)
    return sorted(names)


def _resolve_host_templates(host_row: dict[str, Any], template_index: dict[str, dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for template in host_row.get("parentTemplates") or []:
        tid = str(template.get("templateid") or "")
        row = template_index.get(tid, template)
        name = _entity_display_name(row)
        if name:
            names.add(name)
    return sorted(names)


def _prune_inventory(inventory: Any) -> dict[str, str]:
    """Mantém apenas campos de inventário úteis e não vazios."""
    if not isinstance(inventory, dict):
        return {}
    return {
        field_name: str(inventory[field_name]).strip()
        for field_name in INVENTORY_FIELDS
        if str(inventory.get(field_name) or "").strip()
    }


def analyze_keys(alerts: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Agrupa alertas por `alert_key` e identifica colisões reais.

    Vários hosts compartilhando o mesmo trigger de template geram a MESMA
    `alert_key` — isso é desejado (procedimento único para N hosts) e não é
    colisão. Colisão é quando a mesma `alert_key` agrupa triggers
    tecnicamente diferentes (assinaturas de expressão distintas).
    """
    index: dict[str, dict[str, Any]] = {}

    for alert in alerts:
        key = alert["alert_key"]
        zbx = alert["zabbix"]
        entry = index.setdefault(
            key,
            {
                "alert_key": key,
                "strategy": alert["alert_key_strategy"],
                "scope": alert["alert_key_scope"],
                "count": 0,
                "triggerids": [],
                "hosts": [],
                "descriptions": [],
                "signatures": [],
                "occurrences": [],
                "collision": False,
            },
        )
        entry["count"] += 1
        entry["triggerids"].append(zbx["triggerid"])
        host_name = zbx["host"]["name"] or zbx["host"]["host"]
        if host_name and host_name not in entry["hosts"]:
            entry["hosts"].append(host_name)
        if zbx["description_raw"] not in entry["descriptions"]:
            entry["descriptions"].append(zbx["description_raw"])
        if zbx["expression_signature"] not in entry["signatures"]:
            entry["signatures"].append(zbx["expression_signature"])
        entry["occurrences"].append(
            {
                "triggerid": zbx["triggerid"],
                "host": host_name,
                "description_raw": zbx["description_raw"],
                "expression_expanded": zbx["expression_expanded"],
                "expression_signature": zbx["expression_signature"],
                "priority": zbx["priority"]["name"],
                "source_template": zbx["source_template"],
            }
        )

    collisions: list[dict[str, Any]] = []
    for entry in index.values():
        if len(entry["signatures"]) > 1:
            entry["collision"] = True
            collisions.append(
                {
                    "alert_key": entry["alert_key"],
                    "strategy": entry["strategy"],
                    "distinct_signatures": len(entry["signatures"]),
                    "suggested_key_pattern": f"{entry['alert_key']}#<sha256(expression_signature)[:8]>",
                    "suggested_keys": sorted(
                        {
                            f"{entry['alert_key']}#{short_hash(occ['expression_signature'])}"
                            for occ in entry["occurrences"]
                        }
                    ),
                    "occurrences": entry["occurrences"],
                }
            )

    collisions.sort(key=lambda c: (-c["distinct_signatures"], c["alert_key"]))
    return index, collisions


def build_stats(
    alerts: list[dict[str, Any]],
    key_index: dict[str, dict[str, Any]],
    collisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Métricas da coleta, usadas no relatório final."""

    def count_by(getter) -> dict[str, int]:
        acc: dict[str, int] = {}
        for alert in alerts:
            acc[getter(alert)] = acc.get(getter(alert), 0) + 1
        return dict(sorted(acc.items(), key=lambda kv: (-kv[1], kv[0])))

    shared_keys = {k: v["count"] for k, v in key_index.items() if v["count"] > 1}
    return {
        "alerts": len(alerts),
        "unique_alert_keys": len(key_index),
        "alert_key_collisions": len(collisions),
        "alert_keys_shared_by_multiple_triggers": len(shared_keys),
        "by_priority": count_by(lambda a: a["zabbix"]["priority"]["name"]),
        "by_key_strategy": count_by(lambda a: a["alert_key_strategy"]),
        "by_status": count_by(lambda a: a["zabbix"]["status"]["name"]),
        "templated": sum(1 for a in alerts if a["zabbix"]["templated"]),
        "discovered": sum(1 for a in alerts if a["zabbix"]["discovered"]),
        "without_comments": sum(1 for a in alerts if not a["zabbix"]["comments"].strip()),
        "without_tags": sum(1 for a in alerts if not a["zabbix"]["tags"]),
        "with_dependencies": sum(1 for a in alerts if a["zabbix"]["dependencies"]),
        "top_shared_alert_keys": [
            {"alert_key": k, "triggers": c}
            for k, c in sorted(shared_keys.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        ],
    }
