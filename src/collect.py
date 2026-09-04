"""Coleta bruta (read-only) dos dados do Zabbix necessários à ficha operacional.

Ordem da coleta e como os relacionamentos são resolvidos:

    trigger  ->  item  ->  host  ->  host group
                              \\->  template
    trigger  ->  template de origem (cadeia `templateid`)
    trigger  ->  protótipo (quando o trigger foi criado por LLD)
    trigger  ->  dependências (nomes resolvidos)

Nada aqui escreve no Zabbix: todas as chamadas passam pela allowlist do
`ZabbixReadOnlyClient`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .zabbix_client import ZabbixError, ZabbixReadOnlyClient, chunked

logger = logging.getLogger(__name__)

MAX_TEMPLATE_CHAIN_DEPTH = 10

TRIGGER_OUTPUT = [
    "triggerid",
    "description",
    "expression",
    "recovery_expression",
    "recovery_mode",
    "priority",
    "status",
    "value",
    "state",
    "comments",
    "manual_close",
    "opdata",
    "event_name",
    "templateid",
    "flags",
]

HOST_OUTPUT = ["hostid", "host", "name", "status", "description"]
ITEM_OUTPUT = ["itemid", "hostid", "key_", "name", "units", "value_type", "description", "delay", "status", "state"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class RawSnapshot:
    """Aquilo que foi efetivamente recebido do Zabbix (imutável, para auditoria)."""

    meta: dict[str, Any] = field(default_factory=dict)
    data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    api_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "counts": {name: len(rows) for name, rows in sorted(self.data.items())},
            "api_calls": self.api_calls,
            "data": self.data,
        }


def _ids(rows: Iterable[dict[str, Any]], key: str) -> list[str]:
    out: list[str] = []
    for row in rows:
        value = str(row.get(key) or "")
        if value and value != "0":
            out.append(value)
    return out


def _nested_ids(rows: Iterable[dict[str, Any]], parent: str, key: str) -> list[str]:
    """IDs de uma propriedade aninhada, que a API devolve como lista ou objeto."""
    out: list[str] = []
    for row in rows:
        nested = row.get(parent) or []
        children = [nested] if isinstance(nested, dict) else nested
        for child in children:
            if isinstance(child, dict):
                value = str(child.get(key) or "")
                if value and value != "0":
                    out.append(value)
    return out


def collect_raw(
    client: ZabbixReadOnlyClient,
    *,
    host_groups: Iterable[str] = (),
    limit: int | None = None,
    only_monitored: bool = False,
    include_template_triggers: bool = False,
    on_step: Callable[[str], None] = lambda _msg: None,
) -> RawSnapshot:
    """Executa a coleta completa e devolve o snapshot bruto."""
    version = client.connect()
    on_step(f"Conectado ao Zabbix (API {version}, {client.auth_description})")

    filters: dict[str, Any] = {
        "host_groups": list(host_groups),
        "limit": limit,
        "only_monitored": only_monitored,
        "include_template_triggers": include_template_triggers,
    }

    # ------------------------------------------------------------ grupos filtro
    group_filter_ids: list[str] = []
    requested_groups = [g for g in host_groups if g]
    if requested_groups:
        found = client.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": requested_groups}}) or []
        group_filter_ids = _ids(found, "groupid")
        missing = sorted(set(requested_groups) - {row.get("name") for row in found})
        if missing:
            raise ZabbixError(f"Grupos de hosts não encontrados no Zabbix: {', '.join(missing)}")
        on_step(f"Filtro por grupos: {', '.join(requested_groups)}")

    # ---------------------------------------------------------------- triggers
    trigger_params: dict[str, Any] = {
        "output": TRIGGER_OUTPUT,
        "selectHosts": HOST_OUTPUT,
        "selectItems": ["itemid", "hostid", "key_", "name", "units", "value_type"],
        "selectDependencies": ["triggerid", "description"],
        "selectTags": "extend",
        "sortfield": "description",
    }
    # Selects ligados a LLD mudaram de nome entre versões; são opcionais e a
    # coleta não pode falhar por causa deles.
    optional_selects = {
        "selectDiscoveryRule": ["itemid", "name", "key_"],
        "selectTriggerDiscovery": ["parent_triggerid"],
    }
    if not include_template_triggers:
        trigger_params["templated"] = False
    if only_monitored:
        trigger_params["monitored"] = True

    if limit:
        # Coleta de teste (--limit): uma única chamada, sem paginar por host.
        if group_filter_ids:
            trigger_params["groupids"] = group_filter_ids
        trigger_params["limit"] = int(limit)
        triggers = _get_triggers(client, trigger_params, optional_selects, on_step)
    else:
        # Coleta completa: pedir todos os triggers do escopo numa chamada só
        # costuma estourar tempo/memória do servidor Zabbix em ambientes
        # grandes (HTTP 500 com corpo vazio). Resolvemos os hosts do escopo
        # primeiro e paginamos o trigger.get em lotes de hosts.
        scope_host_ids = _resolve_scope_host_ids(client, group_filter_ids)
        triggers = _get_triggers_by_host(client, trigger_params, optional_selects, scope_host_ids, on_step)

    on_step(f"{len(triggers)} triggers coletados")

    # Expressões expandidas: mesma consulta, apenas com expandExpression.
    trigger_ids = _ids(triggers, "triggerid")
    expanded = client.get_by_ids(
        "trigger.get",
        "triggerids",
        trigger_ids,
        {
            "output": ["triggerid", "expression", "recovery_expression", "description", "opdata", "event_name"],
            "expandExpression": True,
        },
    )
    on_step(f"{len(expanded)} expressões expandidas")

    # ------------------------------------------- cadeia de templates do trigger
    parent_triggers = _collect_template_chain(client, "trigger.get", _ids(triggers, "templateid"), on_step)

    # ------------------------------------------------- protótipos (triggers LLD)
    prototype_ids = _nested_ids(triggers, "triggerDiscovery", "parent_triggerid")
    trigger_prototypes: list[dict[str, Any]] = []
    if prototype_ids:
        try:
            trigger_prototypes = client.get_by_ids(
                "triggerprototype.get",
                "triggerids",
                prototype_ids,
                {"output": ["triggerid", "description", "templateid"], "selectHosts": ["hostid", "host", "name", "status"]},
            )
            trigger_prototypes += _collect_template_chain(
                client, "triggerprototype.get", _ids(trigger_prototypes, "templateid"), on_step
            )
            on_step(f"{len(trigger_prototypes)} protótipos de trigger (LLD) resolvidos")
        except ZabbixError as exc:
            # Ambiente sem permissão de leitura em protótipos: a coleta continua,
            # apenas a chave dos triggers descobertos cai no fallback host+descrição.
            logger.warning("Não foi possível resolver protótipos de trigger: %s", exc)
            on_step(f"Protótipos de trigger não resolvidos ({exc})")

    # ------------------------------------------------------------- dependências
    dependency_ids = _nested_ids(triggers, "dependencies", "triggerid")
    dependency_triggers = (
        client.get_by_ids(
            "trigger.get",
            "triggerids",
            dependency_ids,
            {"output": ["triggerid", "description", "priority"], "selectHosts": ["hostid", "host", "name"]},
        )
        if dependency_ids
        else []
    )

    # -------------------------------------------------------------------- hosts
    host_ids = _nested_ids(triggers, "hosts", "hostid")
    hosts = _get_hosts(client, host_ids)
    on_step(f"{len(hosts)} hosts resolvidos")

    # -------------------------------------------------------------- host groups
    group_ids = _nested_ids(hosts, "hostgroups", "groupid") + _nested_ids(hosts, "groups", "groupid")
    host_groups_rows = (
        client.get_by_ids("hostgroup.get", "groupids", group_ids, {"output": ["groupid", "name"]}) if group_ids else []
    )
    on_step(f"{len(host_groups_rows)} grupos de hosts resolvidos")

    # ---------------------------------------------------------------- templates
    template_ids = (
        _nested_ids(hosts, "parentTemplates", "templateid")
        + _nested_ids(parent_triggers, "hosts", "hostid")
        + _nested_ids(trigger_prototypes, "hosts", "hostid")
    )
    templates = (
        client.get_by_ids("template.get", "templateids", template_ids, {"output": ["templateid", "host", "name"]})
        if template_ids
        else []
    )
    on_step(f"{len(templates)} templates resolvidos")

    # -------------------------------------------------------------------- itens
    item_ids = _nested_ids(triggers, "items", "itemid")
    items = _get_items(client, item_ids)
    on_step(f"{len(items)} itens relacionados resolvidos")

    meta = {
        "collector_version": "0.1.0",
        "collected_at": utc_now_iso(),
        "collected_at_local": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "zabbix_endpoint": client.endpoint,
        "zabbix_version": version,
        "auth_method": client.auth_description,
        "read_only": True,
        "filters": filters,
    }

    return RawSnapshot(
        meta=meta,
        data={
            "triggers": triggers,
            "triggers_expanded": expanded,
            "parent_triggers": parent_triggers,
            "trigger_prototypes": trigger_prototypes,
            "dependency_triggers": dependency_triggers,
            "hosts": hosts,
            "hostgroups": host_groups_rows,
            "templates": templates,
            "items": items,
        },
        api_calls=list(client.call_log),
    )


def _resolve_scope_host_ids(client: ZabbixReadOnlyClient, group_filter_ids: list[str]) -> list[str]:
    """Hosts do escopo da coleta — usados só para paginar o trigger.get."""
    params: dict[str, Any] = {"output": ["hostid"]}
    if group_filter_ids:
        params["groupids"] = group_filter_ids
    hosts = client.call("host.get", params) or []
    return _ids(hosts, "hostid")


def _get_triggers_by_host(
    client: ZabbixReadOnlyClient,
    params: dict[str, Any],
    optional_selects: dict[str, Any],
    host_ids: list[str],
    on_step: Callable[[str], None],
) -> list[dict[str, Any]]:
    """trigger.get em lotes de hostids.

    Uma única chamada trazendo os triggers de milhares de hosts (com todos os
    selects usados aqui) pode estourar o tempo/memória do servidor Zabbix e
    devolver HTTP 500 com corpo vazio. Paginando por lotes de hosts, cada
    chamada fica pequena o bastante para o servidor responder normalmente.
    Como um host pode pertencer a mais de um grupo do escopo, deduplicamos
    por triggerid ao final.
    """
    batches = list(chunked(host_ids, client.trigger_batch_size))
    collected: dict[str, dict[str, Any]] = {}
    for index, batch in enumerate(batches, start=1):
        rows = _get_triggers(client, {**params, "hostids": batch}, optional_selects, on_step)
        for row in rows:
            collected[str(row.get("triggerid"))] = row
        on_step(f"lote {index}/{len(batches)} de hosts: {len(rows)} triggers ({len(collected)} acumulados)")
    return list(collected.values())


def _get_triggers(
    client: ZabbixReadOnlyClient,
    params: dict[str, Any],
    optional_selects: dict[str, Any],
    on_step: Callable[[str], None],
) -> list[dict[str, Any]]:
    """trigger.get tolerante a parâmetros opcionais indisponíveis na versão."""
    try:
        return client.call("trigger.get", {**params, **optional_selects}) or []
    except ZabbixError as exc:
        logger.warning("trigger.get com selects de LLD falhou (%s); repetindo sem eles", exc)
        on_step(f"Aviso: selects de LLD indisponíveis nesta versão ({exc})")
        return client.call("trigger.get", params) or []


def _collect_template_chain(
    client: ZabbixReadOnlyClient,
    method: str,
    seed_ids: Iterable[str],
    on_step: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Sobe a cadeia `templateid` até o trigger/protótipo definido no template raiz."""
    pending = {i for i in seed_ids if i and i != "0"}
    seen: set[str] = set()
    collected: list[dict[str, Any]] = []
    depth = 0

    while pending and depth < MAX_TEMPLATE_CHAIN_DEPTH:
        batch = sorted(pending - seen)
        if not batch:
            break
        rows = client.get_by_ids(
            method,
            "triggerids",
            batch,
            {
                "output": ["triggerid", "description", "templateid"],
                "selectHosts": ["hostid", "host", "name", "status"],
            },
        )
        collected.extend(rows)
        seen.update(batch)
        pending = {str(row.get("templateid")) for row in rows if str(row.get("templateid") or "0") != "0"} - seen
        depth += 1

    if depth >= MAX_TEMPLATE_CHAIN_DEPTH and pending:  # pragma: no cover - defensivo
        on_step(f"Aviso: cadeia de templates de {method} truncada em {MAX_TEMPLATE_CHAIN_DEPTH} níveis")
    return collected


def _get_hosts(client: ZabbixReadOnlyClient, host_ids: Iterable[str]) -> list[dict[str, Any]]:
    """host.get com compatibilidade entre `selectHostGroups` (>=6.2) e `selectGroups`."""
    base = {
        "output": HOST_OUTPUT,
        "selectParentTemplates": ["templateid", "host", "name"],
        "selectInventory": "extend",
    }
    ids = list(host_ids)
    if not ids:
        return []

    select_groups_key = "selectHostGroups" if client.supports_host_groups_select() else "selectGroups"
    try:
        return client.get_by_ids("host.get", "hostids", ids, {**base, select_groups_key: ["groupid", "name"]})
    except ZabbixError as exc:
        fallback = "selectGroups" if select_groups_key == "selectHostGroups" else "selectHostGroups"
        logger.warning("host.get com %s falhou (%s); tentando %s", select_groups_key, exc, fallback)
        return client.get_by_ids("host.get", "hostids", ids, {**base, fallback: ["groupid", "name"]})


def _get_items(client: ZabbixReadOnlyClient, item_ids: Iterable[str]) -> list[dict[str, Any]]:
    """item.get pedindo `name_resolved` quando a versão suportar (Zabbix >= 6.4)."""
    ids = list(item_ids)
    if not ids:
        return []

    from .zabbix_client import parse_version

    output = list(ITEM_OUTPUT)
    if parse_version(client.api_version()) >= (6, 4):
        output.append("name_resolved")
    try:
        return client.get_by_ids("item.get", "itemids", ids, {"output": output})
    except ZabbixError as exc:
        if "name_resolved" not in output:
            raise
        logger.warning("item.get com name_resolved falhou (%s); repetindo sem o campo", exc)
        return client.get_by_ids("item.get", "itemids", ids, {"output": ITEM_OUTPUT})
