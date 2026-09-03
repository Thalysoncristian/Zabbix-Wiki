"""Zabbix falso (transporte JSON-RPC em memória) para testar o pipeline offline.

Reproduz o comportamento dos métodos de leitura usados pelo coletor, com um
ambiente pequeno mas representativo:

* trigger de template compartilhado por 2 hosts  -> mesma alert_key (não é colisão)
* trigger criado por LLD com protótipo           -> chave baseada no protótipo
* trigger local de host                          -> chave baseada no host
* 2 triggers locais com a MESMA descrição e expressões diferentes -> colisão real
"""

from __future__ import annotations

from typing import Any

TEMPLATES = [
    {"templateid": "10001", "host": "Linux by Zabbix agent", "name": "Linux by Zabbix agent"},
    {"templateid": "10002", "host": "Wazuh SIEM by HTTP", "name": "Wazuh SIEM by HTTP"},
]

HOSTGROUPS = [
    {"groupid": "4", "name": "Infraestrutura"},
    {"groupid": "5", "name": "Servidores Linux"},
    {"groupid": "6", "name": "SIEM"},
]

HOSTS = [
    {
        "hostid": "10501",
        "host": "srv-linux-01",
        "name": "Vibe - Zabbix Proxy",
        "status": "0",
        "description": "",
        "hostgroups": [HOSTGROUPS[0], HOSTGROUPS[1]],
        "parentTemplates": [{"templateid": "10001", "host": "Linux by Zabbix agent", "name": "Linux by Zabbix agent"}],
        "inventory": {"os": "Ubuntu 22.04", "location": "DC1", "contact": "", "notes": "", "tag": ""},
    },
    {
        "hostid": "10502",
        "host": "srv-linux-02",
        "name": "Vibe - App Server",
        "status": "0",
        "description": "",
        "hostgroups": [HOSTGROUPS[0], HOSTGROUPS[1]],
        "parentTemplates": [{"templateid": "10001", "host": "Linux by Zabbix agent", "name": "Linux by Zabbix agent"}],
        "inventory": [],
    },
    {
        "hostid": "10503",
        "host": "wazuh",
        "name": "Vibe - Wazuh SIEM",
        "status": "0",
        "description": "",
        "hostgroups": [HOSTGROUPS[0], HOSTGROUPS[2]],
        "parentTemplates": [{"templateid": "10002", "host": "Wazuh SIEM by HTTP", "name": "Wazuh SIEM by HTTP"}],
        "inventory": {"os": "Rocky Linux 9", "location": "DC2"},
    },
]

ITEMS = [
    {"itemid": "5001", "hostid": "10501", "key_": "vfs.fs.size[/,pfree]", "name": "/: Space available in %",
     "units": "%", "value_type": "0", "delay": "1m", "status": "0", "state": "0", "description": ""},
    {"itemid": "5002", "hostid": "10502", "key_": "vfs.fs.size[/,pfree]", "name": "/: Space available in %",
     "units": "%", "value_type": "0", "delay": "1m", "status": "0", "state": "0", "description": ""},
    {"itemid": "5003", "hostid": "10501", "key_": "vfs.fs.size[/var,pfree]", "name": "/var: Space available in %",
     "units": "%", "value_type": "0", "delay": "1m", "status": "0", "state": "0", "description": ""},
    {"itemid": "5010", "hostid": "10503", "key_": "proc.num[filebeat]", "name": "Processos filebeat",
     "units": "", "value_type": "3", "delay": "1m", "status": "0", "state": "0", "description": ""},
    {"itemid": "5011", "hostid": "10503", "key_": "proc.num[wazuh-manager]", "name": "Processos wazuh-manager",
     "units": "", "value_type": "3", "delay": "1m", "status": "0", "state": "0", "description": ""},
    {"itemid": "5020", "hostid": "10503", "key_": "wazuh.queue.usage", "name": "Uso da fila de eventos",
     "units": "%", "value_type": "0", "delay": "5m", "status": "0", "state": "0", "description": ""},
]


def _host_stub(hostid: str) -> dict[str, Any]:
    host = next(h for h in HOSTS if h["hostid"] == hostid)
    return {k: host[k] for k in ("hostid", "host", "name", "status", "description")}


def _template_stub(templateid: str) -> dict[str, Any]:
    template = next(t for t in TEMPLATES if t["templateid"] == templateid)
    return {"hostid": templateid, "host": template["host"], "name": template["name"], "status": "3"}


def _item_stub(itemid: str) -> dict[str, Any]:
    item = next(i for i in ITEMS if i["itemid"] == itemid)
    return {k: item[k] for k in ("itemid", "hostid", "key_", "name", "units", "value_type")}


#: Triggers de host (o que a coleta enxerga com templated=False).
HOST_TRIGGERS = [
    {
        "triggerid": "100",
        "description": "Linux: Disk space is critically low (used > {$VFS.FS.PUSED.MAX.CRIT})",
        "expression": "{1001}<20",
        "expression_expanded": "last(/srv-linux-01/vfs.fs.size[/,pfree])<20",
        "recovery_expression": "",
        "recovery_mode": "0",
        "priority": "4",
        "status": "0",
        "value": "0",
        "state": "0",
        "comments": "Partição raiz acima do limite configurado.",
        "manual_close": "0",
        "opdata": "Livre: {ITEM.LASTVALUE1}",
        "event_name": "",
        "templateid": "900",
        "flags": "0",
        "hosts": ["10501"],
        "items": ["5001"],
        "tags": [{"tag": "scope", "value": "capacity"}, {"tag": "component", "value": "storage"}],
        "dependencies": [],
    },
    {
        "triggerid": "101",
        "description": "Linux: Disk space is critically low (used > {$VFS.FS.PUSED.MAX.CRIT})",
        "expression": "{1002}<20",
        "expression_expanded": "last(/srv-linux-02/vfs.fs.size[/,pfree])<20",
        "recovery_expression": "",
        "recovery_mode": "0",
        "priority": "4",
        "status": "0",
        "value": "1",
        "state": "0",
        "comments": "Partição raiz acima do limite configurado.",
        "manual_close": "0",
        "opdata": "Livre: {ITEM.LASTVALUE1}",
        "event_name": "",
        "templateid": "900",
        "flags": "0",
        "hosts": ["10502"],
        "items": ["5002"],
        "tags": [{"tag": "scope", "value": "capacity"}, {"tag": "component", "value": "storage"}],
        "dependencies": [],
    },
    {
        "triggerid": "200",
        "description": "/var: Disk space is critically low",
        "expression": "{1003}<10",
        "expression_expanded": "last(/srv-linux-01/vfs.fs.size[/var,pfree])<10",
        "recovery_expression": "",
        "recovery_mode": "0",
        "priority": "4",
        "status": "0",
        "value": "0",
        "state": "0",
        "comments": "",
        "manual_close": "1",
        "opdata": "",
        "event_name": "",
        "templateid": "0",
        "flags": "4",
        "hosts": ["10501"],
        "items": ["5003"],
        "tags": [{"tag": "component", "value": "storage"}],
        "dependencies": ["400"],
        "discoveryRule": {"itemid": "7001", "name": "Mounted filesystem discovery", "key_": "vfs.fs.discovery"},
        "triggerDiscovery": {"parent_triggerid": "300"},
    },
    {
        "triggerid": "400",
        "description": "Wazuh: fila de eventos ACIMA do limite",
        "expression": "{1004}>90",
        "expression_expanded": "last(/wazuh/wazuh.queue.usage)>90",
        "recovery_expression": "last(/wazuh/wazuh.queue.usage)<80",
        "recovery_mode": "1",
        "priority": "3",
        "status": "0",
        "value": "0",
        "state": "0",
        "comments": "Fila do analisador de eventos acumulando.",
        "manual_close": "0",
        "opdata": "",
        "event_name": "SIEM: fila de eventos acima do limite",
        "templateid": "0",
        "flags": "0",
        "hosts": ["10503"],
        "items": ["5020"],
        "tags": [{"tag": "service", "value": "siem"}],
        "dependencies": [],
    },
    {
        "triggerid": "401",
        "description": "Serviço parado",
        "expression": "{1005}=0",
        "expression_expanded": "last(/wazuh/proc.num[filebeat])=0",
        "recovery_expression": "",
        "recovery_mode": "0",
        "priority": "4",
        "status": "0",
        "value": "0",
        "state": "0",
        "comments": "",
        "manual_close": "0",
        "opdata": "",
        "event_name": "",
        "templateid": "0",
        "flags": "0",
        "hosts": ["10503"],
        "items": ["5010"],
        "tags": [],
        "dependencies": [],
    },
    {
        "triggerid": "402",
        "description": "Serviço  PARADO",
        "expression": "{1006}=0",
        "expression_expanded": "last(/wazuh/proc.num[wazuh-manager])=0",
        "recovery_expression": "",
        "recovery_mode": "0",
        "priority": "5",
        "status": "0",
        "value": "0",
        "state": "0",
        "comments": "",
        "manual_close": "0",
        "opdata": "",
        "event_name": "",
        "templateid": "0",
        "flags": "0",
        "hosts": ["10503"],
        "items": ["5011"],
        "tags": [],
        "dependencies": [],
    },
]

#: Triggers definidos nos templates (alcançados pela cadeia `templateid`).
TEMPLATE_TRIGGERS = [
    {
        "triggerid": "900",
        "description": "Linux: Disk space is critically low (used > {$VFS.FS.PUSED.MAX.CRIT})",
        "templateid": "0",
        "hosts": ["T10001"],
    }
]

#: Protótipos de trigger (LLD).
TRIGGER_PROTOTYPES = [
    {
        "triggerid": "300",
        "description": "{#FSNAME}: Disk space is critically low",
        "templateid": "301",
        "hosts": ["10501"],
    },
    {
        "triggerid": "301",
        "description": "{#FSNAME}: Disk space is critically low",
        "templateid": "0",
        "hosts": ["T10001"],
    },
]


def _expand_hosts(ids: list[str]) -> list[dict[str, Any]]:
    return [_template_stub(i[1:]) if i.startswith("T") else _host_stub(i) for i in ids]


class FakeZabbix:
    """Transporte compatível com `ZabbixReadOnlyClient(transport=...)`."""

    def __init__(self, version: str = "7.0.0", token: str = "fake-token"):
        self.version = version
        self.token = token
        self.methods_called: list[str] = []

    # ------------------------------------------------------------------ helpers
    def _authorized(self, payload: dict[str, Any], headers: dict[str, str]) -> bool:
        bearer = headers.get("Authorization", "")
        if bearer == f"Bearer {self.token}":
            return True
        return payload.get("auth") == self.token

    @staticmethod
    def _error(message: str, data: str = "") -> dict[str, Any]:
        return {"jsonrpc": "2.0", "error": {"code": -32602, "message": message, "data": data}, "id": 1}

    @staticmethod
    def _ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    # --------------------------------------------------------------- dispatcher
    def __call__(self, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        method = payload["method"]
        params = payload.get("params") or {}
        self.methods_called.append(method)

        if method == "apiinfo.version":
            return self._ok(self.version)
        if not self._authorized(payload, headers):
            return self._error("Application error.", "Not authorised.")

        handler = getattr(self, f"_{method.replace('.', '_')}", None)
        if handler is None:
            return self._error("Application error.", f"Method '{method}' not supported by fake.")
        return self._ok(handler(params))

    # ------------------------------------------------------------------ métodos
    def _hostgroup_get(self, params: dict[str, Any]) -> Any:
        rows = HOSTGROUPS
        names = (params.get("filter") or {}).get("name")
        if names:
            rows = [g for g in rows if g["name"] in names]
        if params.get("groupids"):
            wanted = {str(i) for i in params["groupids"]}
            rows = [g for g in rows if g["groupid"] in wanted]
        if params.get("countOutput"):
            return str(len(rows))
        return [dict(g) for g in rows]

    def _host_get(self, params: dict[str, Any]) -> Any:
        rows = HOSTS
        if params.get("hostids"):
            wanted = {str(i) for i in params["hostids"]}
            rows = [h for h in rows if h["hostid"] in wanted]
        if params.get("countOutput"):
            return str(len(rows))

        result = []
        for host in rows:
            row = {k: host[k] for k in ("hostid", "host", "name", "status", "description")}
            if "selectHostGroups" in params:
                row["hostgroups"] = [dict(g) for g in host["hostgroups"]]
            elif "selectGroups" in params:
                row["groups"] = [dict(g) for g in host["hostgroups"]]
            if "selectParentTemplates" in params:
                row["parentTemplates"] = [dict(t) for t in host["parentTemplates"]]
            if "selectInventory" in params:
                row["inventory"] = host["inventory"]
            result.append(row)
        return result

    def _template_get(self, params: dict[str, Any]) -> Any:
        rows = TEMPLATES
        if params.get("templateids"):
            wanted = {str(i) for i in params["templateids"]}
            rows = [t for t in rows if t["templateid"] in wanted]
        return [dict(t) for t in rows]

    def _item_get(self, params: dict[str, Any]) -> Any:
        rows = ITEMS
        if params.get("itemids"):
            wanted = {str(i) for i in params["itemids"]}
            rows = [i for i in rows if i["itemid"] in wanted]
        output = params.get("output") or []
        if "name_resolved" in output:
            return [{**i, "name_resolved": i["name"]} for i in rows]
        return [dict(i) for i in rows]

    def _trigger_get(self, params: dict[str, Any]) -> Any:
        pool = HOST_TRIGGERS + TEMPLATE_TRIGGERS
        if params.get("triggerids"):
            wanted = {str(i) for i in params["triggerids"]}
            rows = [t for t in pool if t["triggerid"] in wanted]
        else:
            rows = list(HOST_TRIGGERS)
            if params.get("groupids"):
                wanted = {str(i) for i in params["groupids"]}
                rows = [
                    t
                    for t in rows
                    if any(g["groupid"] in wanted for h in t["hosts"] for g in _host_groups_of(h))
                ]
            if params.get("limit"):
                rows = rows[: int(params["limit"])]
        if params.get("countOutput"):
            return str(len(rows))
        return [self._render_trigger(t, params) for t in rows]

    def _triggerprototype_get(self, params: dict[str, Any]) -> Any:
        wanted = {str(i) for i in params.get("triggerids", [])}
        rows = [t for t in TRIGGER_PROTOTYPES if t["triggerid"] in wanted]
        return [self._render_trigger(t, params) for t in rows]

    def _render_trigger(self, trigger: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        row: dict[str, Any] = {
            "triggerid": trigger["triggerid"],
            "description": trigger["description"],
            "templateid": trigger.get("templateid", "0"),
        }
        for field in ("expression", "recovery_expression", "recovery_mode", "priority", "status", "value",
                      "state", "comments", "manual_close", "opdata", "event_name", "flags"):
            if field in trigger:
                row[field] = trigger[field]
        if params.get("expandExpression"):
            row["expression"] = trigger.get("expression_expanded", trigger.get("expression", ""))
        if "selectHosts" in params:
            row["hosts"] = _expand_hosts(trigger.get("hosts", []))
        if "selectItems" in params:
            row["items"] = [_item_stub(i) for i in trigger.get("items", [])]
        if "selectTags" in params:
            row["tags"] = [dict(t) for t in trigger.get("tags", [])]
        if "selectDependencies" in params:
            row["dependencies"] = [{"triggerid": d} for d in trigger.get("dependencies", [])]
        if "selectDiscoveryRule" in params and trigger.get("discoveryRule"):
            row["discoveryRule"] = dict(trigger["discoveryRule"])
        if "selectTriggerDiscovery" in params and trigger.get("triggerDiscovery"):
            row["triggerDiscovery"] = dict(trigger["triggerDiscovery"])
        return row


def _host_groups_of(hostid: str) -> list[dict[str, Any]]:
    host = next((h for h in HOSTS if h["hostid"] == hostid), None)
    return host["hostgroups"] if host else []
