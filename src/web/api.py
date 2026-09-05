"""Endpoints de leitura da interface.

Cada função recebe o `ReadModel` já carregado e os parâmetros da query string,
e devolve um dicionário serializável. Nenhuma delas fala com o Zabbix: a única
fonte é o snapshot em disco. É isso que torna a garantia "o frontend não
escreve no Zabbix" estrutural, e não uma promessa — não existe cliente Zabbix
importado neste módulo.

A única escrita permitida é em `docs/alerts/`, pelo `AlertRepository`, para o
procedimento local — o conhecimento que a equipe escreve.
"""

from __future__ import annotations

from typing import Any, Callable

from ..core.models import AlertDoc, build_family_key
from ..core.repository import AlertRepository, ConcurrentModificationError
from ..core.status import ALL_STATUSES, StatusError, assert_can_document, assert_transition
from ..keys import normalize_text
from ..rules.candidates import CONFIDENCE_LABELS
from ..rules.decisions import CANDIDATE, DECISIONS, STATUS_LABELS, DecisionError
from .readmodel import (
    PROCEDURE_LABELS,
    rule_doc_key,
    PROCEDURE_STATUSES,
    SEVERIDADES,
    ReadModel,
    contar_severidades,
    ordenar_severidades,
    paginate,
)


class ApiError(Exception):
    """Erro de requisição com código HTTP associado."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _um(params: dict[str, list[str]], nome: str, padrao: str = "") -> str:
    valores = params.get(nome) or []
    return valores[0].strip() if valores and valores[0] is not None else padrao


def _int(params: dict[str, list[str]], nome: str, padrao: int) -> int:
    try:
        return int(_um(params, nome) or padrao)
    except ValueError:
        return padrao


def _bool(params: dict[str, list[str]], nome: str) -> bool | None:
    """Filtro de três estados: sim, não, ou não filtrar."""
    valor = _um(params, nome).lower()
    if valor in ("1", "true", "sim", "yes"):
        return True
    if valor in ("0", "false", "nao", "não", "no"):
        return False
    return None


# --------------------------------------------------------------------- resumos
def resumo_alerta(modelo: ReadModel, alerta: dict[str, Any]) -> dict[str, Any]:
    """Linha da tabela de alertas — só o que a lista mostra.

    Deliberadamente pequeno: a tabela de 19.000 alertas não pode carregar
    itens, dependências e expressões que ela nem exibe.
    """
    zbx = alerta.get("zabbix") or {}
    triggerid = str(zbx.get("triggerid") or "")
    familia = modelo.family_of_alert(triggerid)
    procedimento = modelo.procedure_of_alert(triggerid)
    host = zbx.get("host") or {}
    return {
        "id": triggerid,
        "description": zbx.get("description_raw", ""),
        "alert_key": alerta.get("alert_key", ""),
        "severity": (zbx.get("priority") or {}).get("name", "Not classified"),
        "status": (zbx.get("status") or {}).get("name", ""),
        "host": {"id": str(host.get("hostid") or ""), "name": host.get("name") or host.get("host") or ""},
        "host_groups": zbx.get("host_groups") or [],
        "family": {"id": familia.id, "label": familia.label} if familia else None,
        "discovered": bool(zbx.get("discovered")),
        "has_comment": bool((zbx.get("comments") or "").strip()),
        "tags": len(zbx.get("tags") or []),
        "dependencies": len(zbx.get("dependencies") or []),
        "collision": bool(alerta.get("alert_key_collision")),
        "procedure_status": procedimento["status"],
    }


def detalhe_alerta(modelo: ReadModel, alerta: dict[str, Any]) -> dict[str, Any]:
    """Ficha completa de um alerta, com as três camadas separadas."""
    zbx = alerta.get("zabbix") or {}
    triggerid = str(zbx.get("triggerid") or "")
    familia = modelo.family_of_alert(triggerid)
    colisao = next(
        (c for c in modelo.collisions if c.get("alert_key") == alerta.get("alert_key")), None
    )
    return {
        "id": triggerid,
        "identification": {
            "description": zbx.get("description_raw", ""),
            "event_name": zbx.get("event_name", ""),
            "alert_key": alerta.get("alert_key", ""),
            "alert_key_strategy": alerta.get("alert_key_strategy", ""),
            "alert_key_scope": alerta.get("alert_key_scope") or {},
            "alert_key_suggested": alerta.get("alert_key_suggested"),
            "source_hash": zbx.get("source_hash", ""),
        },
        "origin": {
            "triggerid": triggerid,
            "host": zbx.get("host") or {},
            "host_groups": zbx.get("host_groups") or [],
            # `None` aqui significa "a coleta não resolveu", não "erro".
            # A interface mostra "não disponível", nunca uma falha.
            "source_template": zbx.get("source_template"),
            "templates": zbx.get("templates") or [],
            "discovered": bool(zbx.get("discovered")),
            "discovery_rule": zbx.get("discovery_rule"),
            "prototype_description": zbx.get("prototype_description"),
        },
        "condition": {
            "expression_raw": zbx.get("expression_raw", ""),
            "expression_expanded": zbx.get("expression_expanded", ""),
            "expression_signature": zbx.get("expression_signature", ""),
            "recovery_mode": zbx.get("recovery_mode") or {},
            "recovery_expression": zbx.get("recovery_expression_expanded")
            or zbx.get("recovery_expression_raw", ""),
            "opdata": zbx.get("opdata", ""),
            "manual_close": bool(zbx.get("manual_close")),
        },
        "severity": zbx.get("priority") or {},
        "state": {"status": zbx.get("status") or {}, "value": zbx.get("value") or {}, "runtime": zbx.get("state") or {}},
        "items": zbx.get("items") or [],
        "dependencies": zbx.get("dependencies") or [],
        "comments": zbx.get("comments", ""),
        "tags": zbx.get("tags") or [],
        "family": familia.resumo(modelo.procedure_of_family(familia.id)) if familia else None,
        "collision": colisao,
        "procedure": modelo.procedure_of_alert(triggerid),
        "collected_at": zbx.get("collected_at", ""),
    }


# ------------------------------------------------------------------- dashboard
def dashboard(modelo: ReadModel, _params: dict[str, list[str]]) -> dict[str, Any]:
    alertas = modelo.alerts
    sem_procedimento = sum(
        1 for tid in modelo.by_trigger if modelo.procedure_of_alert(tid)["status"] == "missing"
    )
    familias_sem_procedimento = sum(
        1 for fid in modelo.families if modelo.procedure_of_family(fid)["status"] == "missing"
    )
    multi_host = [f for f in modelo.families.values() if len(f.hosts) > 1]

    top = sorted(modelo.families.values(), key=lambda f: (-len(f.alert_ids), f.label))[:10]
    ambiente = modelo.environment

    # A visão de TRABALHO: quantas regras existem, quantas já têm procedimento,
    # e quais são as próximas. É esta a pergunta que a ferramenta responde.
    documentadas = em_andamento = pendentes = confirmadas = 0
    pendentes_lista: list[dict[str, Any]] = []
    for identificador in modelo.rules:
        decisao = modelo.decision_of_rule(identificador)
        if decisao["status"] == "ignored":
            continue
        if decisao["status"] == "confirmed":
            confirmadas += 1
        estado = modelo.procedure_of_rule(identificador)["status"]
        if estado == "documented":
            documentadas += 1
        elif estado in ("draft", "needs_review"):
            em_andamento += 1
        else:
            pendentes += 1
            payload = modelo.rule_payload(identificador)
            if payload:
                pendentes_lista.append(payload)
    ativas = documentadas + em_andamento + pendentes
    pendentes_lista.sort(key=_ordem_regra)

    grupos_trabalho = [
        _resumo_grupo_trabalho(modelo, gid, registro)
        for gid, registro in modelo.host_groups.items()
    ]
    grupos_trabalho.sort(key=lambda g: (-g["rules"]["pending"], -g["alerts"]))
    fora = len(modelo.out_of_scope)
    return {
        "snapshot": _snapshot_info(modelo),
        "scope": _scope_info(modelo),
        # As duas visões lado a lado. Ver "2.577 alertas" sem saber que o
        # ambiente tem 18.903 seria tão enganoso quanto o contrário.
        "environment": {
            **ambiente,
            "out_of_scope_alerts": fora,
            "out_of_scope_hosts": len({
                str((a.get("zabbix") or {}).get("host", {}).get("hostid") or "")
                for a in modelo.out_of_scope
            } - {""}),
        },
        "cards": [
            {"key": "alerts", "label": "Alertas", "value": len(alertas), "href": "/alerts"},
            {"key": "alert_keys", "label": "Alert keys únicas",
             "value": len({a.get("alert_key") for a in alertas}), "href": "/alerts"},
            {"key": "families", "label": "Famílias", "value": len(modelo.families), "href": "/families"},
            {"key": "hosts", "label": "Hosts", "value": len(modelo.hosts), "href": "/hosts"},
            {"key": "host_groups", "label": "Host groups", "value": len(modelo.host_groups),
             "href": "/host-groups"},
            {"key": "discovered", "label": "Alertas por LLD",
             "value": sum(1 for a in alertas if (a.get("zabbix") or {}).get("discovered")),
             "href": "/alerts?discovered=1"},
            {"key": "without_procedure", "label": "Alertas sem procedimento",
             "value": sem_procedimento, "href": "/alerts?procedure=missing"},
            {"key": "collisions", "label": "Colisões", "value": len(modelo.collisions), "href": "/collisions"},
            {"key": "with_dependencies", "label": "Com dependências",
             "value": sum(1 for a in alertas if (a.get("zabbix") or {}).get("dependencies")),
             "href": "/alerts?dependencies=1"},
        ],
        "severities": [
            {"name": nome, "value": qtd, "href": f"/alerts?severity={nome}"}
            for nome, qtd in contar_severidades(alertas).items()
        ],
        "quality": [
            {"key": "without_comment", "label": "Sem comentário no Zabbix",
             "value": sum(1 for a in alertas if not ((a.get("zabbix") or {}).get("comments") or "").strip()),
             "href": "/alerts?comment=0"},
            {"key": "without_tags", "label": "Sem tags",
             "value": sum(1 for a in alertas if not (a.get("zabbix") or {}).get("tags")),
             "href": "/alerts?tags=0"},
            {"key": "families_without_procedure", "label": "Famílias sem procedimento",
             "value": familias_sem_procedimento, "href": "/procedures?status=missing"},
            {"key": "collisions", "label": "Possíveis colisões de alert_key",
             "value": len(modelo.collisions), "href": "/collisions"},
            {"key": "multi_host", "label": "Famílias em vários hosts",
             "value": len(multi_host), "href": "/families?multi_host=1"},
        ],
        "top_families": [f.resumo(modelo.procedure_of_family(f.id)) for f in top],
        "work": {
            "rules_total": len(modelo.rules),
            "rules_active": ativas,
            "confirmed": confirmadas,
            "documented": documentadas,
            "in_progress": em_andamento,
            "pending": pendentes,
            "progress": round(documentadas / ativas * 100) if ativas else 0,
            "groups": grupos_trabalho[:8],
            "next_rules": pendentes_lista[:6],
        },
    }


# ---------------------------------------------------------------------- alertas
def _filtrar_alertas(modelo: ReadModel, params: dict[str, list[str]]) -> list[dict[str, Any]]:
    ids_busca = modelo.search_ids(_um(params, "q"))
    host = _um(params, "host")
    grupo = _um(params, "host_group")
    familia = _um(params, "family")
    severidade = _um(params, "severity")
    procedimento = _um(params, "procedure")
    descoberto = _bool(params, "discovered")
    comentario = _bool(params, "comment")
    tags = _bool(params, "tags")
    dependencias = _bool(params, "dependencies")
    colisao = _bool(params, "collision")

    if procedimento and procedimento not in PROCEDURE_STATUSES:
        raise ApiError(f"procedure inválido: {procedimento}. Válidos: {', '.join(PROCEDURE_STATUSES)}")
    if severidade and severidade not in SEVERIDADES:
        raise ApiError(f"severity inválida: {severidade}. Válidas: {', '.join(SEVERIDADES)}")

    resultado: list[dict[str, Any]] = []
    permitidos = set(ids_busca) if ids_busca is not None else None

    for alerta in modelo.alerts:
        zbx = alerta.get("zabbix") or {}
        tid = str(zbx.get("triggerid") or "")
        if permitidos is not None and tid not in permitidos:
            continue
        if host and str((zbx.get("host") or {}).get("hostid") or "") != host:
            continue
        if grupo:
            registro = modelo.host_groups.get(grupo)
            nome = registro["name"] if registro else grupo
            if nome not in (zbx.get("host_groups") or []):
                continue
        if familia and modelo.family_of.get(tid) != familia:
            continue
        if severidade and (zbx.get("priority") or {}).get("name") != severidade:
            continue
        if descoberto is not None and bool(zbx.get("discovered")) != descoberto:
            continue
        if comentario is not None and bool((zbx.get("comments") or "").strip()) != comentario:
            continue
        if tags is not None and bool(zbx.get("tags")) != tags:
            continue
        if dependencias is not None and bool(zbx.get("dependencies")) != dependencias:
            continue
        if colisao is not None and bool(alerta.get("alert_key_collision")) != colisao:
            continue
        if procedimento and modelo.procedure_of_alert(tid)["status"] != procedimento:
            continue
        resultado.append(alerta)
    return resultado


_ORDENACOES: dict[str, Callable[[dict[str, Any]], Any]] = {
    "description": lambda a: (a["zabbix"].get("description_raw") or "").lower(),
    "host": lambda a: ((a["zabbix"].get("host") or {}).get("name") or "").lower(),
    "severity": lambda a: SEVERIDADES.index((a["zabbix"].get("priority") or {}).get("name", "Not classified"))
    if (a["zabbix"].get("priority") or {}).get("name") in SEVERIDADES else 99,
}


def alerts(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    filtrados = _filtrar_alertas(modelo, params)

    ordenar = _um(params, "sort", "severity")
    chave = _ORDENACOES.get(ordenar)
    if chave:
        filtrados = sorted(filtrados, key=chave, reverse=_um(params, "order") == "desc")

    pagina, meta = paginate(filtrados, _int(params, "page", 1), _int(params, "per_page", 50))
    return {
        "items": [resumo_alerta(modelo, a) for a in pagina],
        "pagination": meta,
        "facets": {
            "severities": contar_severidades(filtrados),
            "total_unfiltered": len(modelo.alerts),
        },
    }


def alert_detail(modelo: ReadModel, alert_id: str) -> dict[str, Any]:
    alerta = modelo.by_trigger.get(alert_id)
    if alerta is None:
        raise ApiError(f"Alerta {alert_id} não existe neste snapshot.", 404)
    return detalhe_alerta(modelo, alerta)


# --------------------------------------------------------------------- famílias
def families(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    termo = _um(params, "q")
    procedimento = _um(params, "procedure")
    apenas_multi = _bool(params, "multi_host")
    descoberto = _bool(params, "discovered")

    itens = list(modelo.families.values())
    if termo:
        agulha = normalize_text(termo)
        itens = [f for f in itens if agulha in normalize_text(f"{f.label} {f.origin}")]
    if procedimento:
        itens = [f for f in itens if modelo.procedure_of_family(f.id)["status"] == procedimento]
    if apenas_multi is not None:
        itens = [f for f in itens if (len(f.hosts) > 1) == apenas_multi]
    if descoberto is not None:
        itens = [f for f in itens if f.discovered == descoberto]

    # Padrão: mais alertas primeiro — é o que diz onde escrever procedimento
    # rende mais.
    itens.sort(key=lambda f: (-len(f.alert_ids), f.label))
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 50))
    return {
        "items": [f.resumo(modelo.procedure_of_family(f.id)) for f in pagina],
        "pagination": meta,
        "facets": {"total_unfiltered": len(modelo.families)},
    }


def family_detail(modelo: ReadModel, family_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    familia = modelo.families.get(family_id)
    if familia is None:
        raise ApiError(f"Família {family_id} não existe neste snapshot.", 404)

    alertas = [modelo.by_trigger[tid] for tid in familia.alert_ids if tid in modelo.by_trigger]
    pagina, meta = paginate(alertas, _int(params, "page", 1), _int(params, "per_page", 50))

    expressoes: dict[str, dict[str, Any]] = {}
    for alerta in alertas:
        assinatura = alerta["zabbix"].get("expression_signature", "")
        entrada = expressoes.setdefault(
            assinatura, {"signature": assinatura, "alerts": 0, "example": alerta["zabbix"].get("expression_expanded", "")}
        )
        entrada["alerts"] += 1

    itens_chave: dict[str, int] = {}
    tags: dict[str, int] = {}
    comentarios: dict[str, int] = {}
    for alerta in alertas:
        zbx = alerta["zabbix"]
        for item in zbx.get("items") or []:
            itens_chave[item.get("key_", "")] = itens_chave.get(item.get("key_", ""), 0) + 1
        for tag in zbx.get("tags") or []:
            rotulo = f"{tag.get('tag')}={tag.get('value')}" if tag.get("value") else str(tag.get("tag"))
            tags[rotulo] = tags.get(rotulo, 0) + 1
        comentario = (zbx.get("comments") or "").strip()
        if comentario:
            comentarios[comentario] = comentarios.get(comentario, 0) + 1

    return {
        **familia.resumo(modelo.procedure_of_family(familia.id)),
        # `hosts` continua sendo a CONTAGEM (vem do resumo); a lista tem nome
        # próprio para não haver um campo que é número numa tela e lista noutra.
        "hosts_list": [{"id": hid, "name": nome} for hid, nome in sorted(familia.hosts.items(), key=lambda kv: kv[1])],
        "expressions": sorted(expressoes.values(), key=lambda e: -e["alerts"]),
        "item_keys": sorted(({"key": k, "alerts": v} for k, v in itens_chave.items()), key=lambda i: -i["alerts"])[:30],
        "tags": sorted(({"tag": k, "alerts": v} for k, v in tags.items()), key=lambda t: -t["alerts"])[:30],
        "comments": sorted(({"text": k, "alerts": v} for k, v in comentarios.items()), key=lambda c: -c["alerts"])[:10],
        "dependencies": sum(len(a["zabbix"].get("dependencies") or []) for a in alertas),
        "alerts_page": {
            "items": [resumo_alerta(modelo, a) for a in pagina],
            "pagination": meta,
        },
    }


# ------------------------------------------------------------------------ hosts
def hosts(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    termo = _um(params, "q").lower()
    grupo = _um(params, "host_group")

    itens = []
    for registro in modelo.hosts.values():
        if termo and termo not in f"{registro['name']} {registro['technical_name']}".lower():
            continue
        if grupo:
            alvo = modelo.host_groups.get(grupo)
            nome_grupo = alvo["name"] if alvo else grupo
            if nome_grupo not in registro["host_groups"]:
                continue
        itens.append(_resumo_host(modelo, registro))

    itens.sort(key=lambda h: (-h["alerts"], h["name"].lower()))
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 50))
    return {"items": pagina, "pagination": meta, "facets": {"total_unfiltered": len(modelo.hosts)}}


def _resumo_host(modelo: ReadModel, registro: dict[str, Any]) -> dict[str, Any]:
    criticos = sum(registro["severities"].get(nome, 0) for nome in ("Disaster", "High"))
    pendentes = sum(
        1 for fid in registro["family_ids"] if modelo.procedure_of_family(fid)["status"] == "missing"
    )
    return {
        "id": registro["id"],
        "name": registro["name"],
        "technical_name": registro["technical_name"],
        "status": registro["status"],
        "host_groups": registro["host_groups"],
        "alerts": len(registro["alert_ids"]),
        "families": len(registro["family_ids"]),
        "critical": criticos,
        "discovered": registro["discovered"],
        "procedures_missing": pendentes,
        "severities": registro["severities"],
    }


def host_detail(modelo: ReadModel, host_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    registro = modelo.hosts.get(host_id)
    if registro is None:
        raise ApiError(f"Host {host_id} não existe neste snapshot.", 404)

    alertas = [modelo.by_trigger[tid] for tid in registro["alert_ids"] if tid in modelo.by_trigger]
    pagina, meta = paginate(alertas, _int(params, "page", 1), _int(params, "per_page", 50))

    familias = [modelo.families[fid] for fid in registro["family_ids"] if fid in modelo.families]
    familias.sort(key=lambda f: (-len([t for t in f.alert_ids if t in set(registro["alert_ids"])]), f.label))

    itens: dict[str, dict[str, Any]] = {}
    for alerta in alertas:
        for item in alerta["zabbix"].get("items") or []:
            itens.setdefault(item.get("itemid", ""), item)

    # Regras operacionais que tocam este host — mostradas ANTES das famílias
    # técnicas: o host é contexto, a regra é a unidade de trabalho.
    regras_do_host: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for triggerid in registro["alert_ids"]:
        for identificador in modelo.rules_of_alert.get(triggerid, []):
            if identificador in vistos:
                continue
            vistos.add(identificador)
            payload = modelo.rule_payload(identificador)
            if payload:
                regras_do_host.append(payload)
    regras_do_host.sort(key=_ordem_regra)

    return {
        **_resumo_host(modelo, registro),
        "inventory": registro["inventory"],
        "rules_list": regras_do_host[:40],
        "rules": len(regras_do_host),
        "families_list": [f.resumo(modelo.procedure_of_family(f.id)) for f in familias[:50]],
        "items": sorted(itens.values(), key=lambda i: i.get("key_", ""))[:100],
        "dependencies": [
            {"from": a["zabbix"]["description_raw"], **dep}
            for a in alertas for dep in (a["zabbix"].get("dependencies") or [])
        ][:100],
        "alerts_page": {"items": [resumo_alerta(modelo, a) for a in pagina], "pagination": meta},
    }


# ------------------------------------------------------------------ host groups
def host_groups(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    termo = _um(params, "q").lower()
    itens = []
    for registro in modelo.host_groups.values():
        if termo and termo not in registro["name"].lower():
            continue
        itens.append(_resumo_grupo(modelo, registro))
    itens.sort(key=lambda g: (-g["alerts"], g["name"].lower()))
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 100))
    return {"items": pagina, "pagination": meta, "facets": {"total_unfiltered": len(modelo.host_groups)}}


def _resumo_grupo(modelo: ReadModel, registro: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": registro["id"],
        "name": registro["name"],
        # Um host em dois grupos conta uma vez em cada — é o número que o
        # operador espera ao abrir o grupo. A soma dos grupos NÃO é o total do
        # ambiente, e a interface diz isso.
        "hosts": len(registro["host_ids"]),
        "alerts": len(registro["alert_ids"]),
        "families": len(registro["family_ids"]),
        "severities": ordenar_severidades(registro["severities"]),
    }


def host_group_detail(modelo: ReadModel, group_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    registro = modelo.host_groups.get(group_id)
    if registro is None:
        raise ApiError(f"Grupo {group_id} não existe neste snapshot.", 404)

    parametros = dict(params)
    parametros["host_group"] = [group_id]
    filtrados = _filtrar_alertas(modelo, parametros)
    pagina, meta = paginate(filtrados, _int(params, "page", 1), _int(params, "per_page", 50))

    familias = [modelo.families[fid] for fid in registro["family_ids"] if fid in modelo.families]
    familias.sort(key=lambda f: (-len(f.alert_ids), f.label))

    return {
        **_resumo_grupo(modelo, registro),
        "hosts_list": sorted(
            (_resumo_host(modelo, modelo.hosts[hid]) for hid in registro["host_ids"] if hid in modelo.hosts),
            key=lambda h: (-h["alerts"], h["name"].lower()),
        ),
        "families_list": [f.resumo(modelo.procedure_of_family(f.id)) for f in familias[:50]],
        "alerts_page": {"items": [resumo_alerta(modelo, a) for a in pagina], "pagination": meta},
    }


# ----------------------------------------------------------------- procedimentos
def procedures(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    estado = _um(params, "status")
    termo = _um(params, "q")
    if estado and estado not in PROCEDURE_STATUSES:
        raise ApiError(f"status inválido: {estado}. Válidos: {', '.join(PROCEDURE_STATUSES)}")

    agulha = normalize_text(termo)
    itens = []
    contagem = {chave: 0 for chave in PROCEDURE_STATUSES}
    for familia in modelo.families.values():
        procedimento = modelo.procedure_of_family(familia.id)
        contagem[procedimento["status"]] = contagem.get(procedimento["status"], 0) + 1
        if estado and procedimento["status"] != estado:
            continue
        if agulha and agulha not in normalize_text(f"{familia.label} {familia.origin}"):
            continue
        itens.append(familia.resumo(procedimento))

    itens.sort(key=lambda f: (-f["alerts"], f["label"]))
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 50))
    return {
        "items": pagina,
        "pagination": meta,
        "facets": {
            "by_status": [
                {"status": chave, "label": PROCEDURE_LABELS[chave], "value": contagem.get(chave, 0)}
                for chave in PROCEDURE_STATUSES
            ],
            "total_unfiltered": len(modelo.families),
        },
    }


def save_procedure(
    modelo: ReadModel,
    target_id: str,
    corpo: dict[str, Any],
    docs_dir: str,
    *,
    kind: str = "family",
) -> dict[str, Any]:
    """Grava o procedimento local de uma família OU de uma regra operacional.

    ESTA É A ÚNICA ESCRITA DO SISTEMA — e ela vai para `docs/alerts/`, nunca
    para o Zabbix. A ficha continua sendo criada pelo mesmo `AlertDoc` do
    `reconcile`, com a mesma máquina de estados: a interface não pode marcar
    como documentado uma ficha sem os campos mínimos, nem pular estados.

    Regra e família compartilham o repositório de propósito. Uma regra é uma
    unidade de documentação como outra qualquer; separá-las em dois lugares
    duplicaria a máquina de estados e o controle de concorrência.
    """
    if kind == "rule":
        regra = modelo.rules.get(target_id)
        if regra is None:
            raise ApiError(f"Regra {target_id} não existe neste escopo.", 404)
        chave = rule_doc_key(target_id)
        primeiro = regra.alert_ids[0] if regra.alert_ids else None
        rotulo = f"{regra.label} — {regra.group_name}"
    else:
        familia = modelo.families.get(target_id)
        if familia is None:
            raise ApiError(f"Família {target_id} não existe neste snapshot.", 404)
        chave = familia.key
        primeiro = familia.alert_ids[0] if familia.alert_ids else None
        rotulo = familia.label

    repositorio = AlertRepository(docs_dir)
    doc = repositorio.get(chave)
    if doc is None:
        alerta = modelo.by_trigger.get(primeiro) if primeiro else None
        if alerta is None:
            raise ApiError(f"{rotulo} não tem alertas — não há o que documentar.", 400)
        doc = AlertDoc.from_collected_alert(alerta)
        doc.alert_key = chave
        doc.family_key = build_family_key(alerta)
        if kind == "rule":
            doc.doc_level = "rule"

    esperada = corpo.get("expected_revision")
    operacional = corpo.get("operational")
    if not isinstance(operacional, dict):
        raise ApiError("Corpo inválido: 'operational' precisa ser um objeto.", 400)

    novo_estado = str(operacional.get("doc_status") or doc.doc_status)
    if novo_estado not in ALL_STATUSES:
        raise ApiError(f"doc_status inválido: {novo_estado}", 400)

    # O bloco humano é substituído campo a campo, preservando o que a interface
    # não enviou. `ai_suggestion` e `zabbix` não são tocados aqui: as camadas
    # não se misturam nem por descuido.
    atualizado = {**doc.operational}
    for campo, valor in operacional.items():
        if campo in atualizado or campo == "doc_status":
            atualizado[campo] = valor

    try:
        assert_transition(doc.doc_status, novo_estado)
        if novo_estado in ("documented", "reviewed"):
            assert_can_document(atualizado)
    except StatusError as exc:
        raise ApiError(str(exc), 422) from exc

    atualizado["doc_status"] = novo_estado
    doc.operational = atualizado
    doc.touch()

    try:
        repositorio.save(doc, expected_revision=esperada if esperada is not None else None)
    except ConcurrentModificationError as exc:
        raise ApiError(str(exc), 409) from exc

    return {"saved": True, "kind": kind, "id": target_id, "revision": doc.revision,
            "procedure_status": doc.procedure_status}


# ----------------------------------------------------------------------- regras
def _ordem_regra(payload: dict[str, Any]) -> tuple[Any, ...]:
    """Fila de trabalho: o que rende mais documentação primeiro.

    Confirmadas e sem procedimento vêm antes de tudo — são as que já foram
    validadas por uma pessoa e só esperam o texto. Depois, as sugestões de
    confiança alta com mais alertas.
    """
    prioridade_status = {"confirmed": 0, CANDIDATE: 1, "split": 2, "ignored": 3}
    prioridade_conf = {"high": 0, "medium": 1, "low": 2}
    sem_procedimento = (payload.get("procedure") or {}).get("status") == "missing"
    return (
        prioridade_status.get(payload["status"], 9),
        0 if sem_procedimento else 1,
        prioridade_conf.get(payload["confidence"], 9),
        -payload["alerts"],
        payload["label"],
    )


def rules(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    grupo = _um(params, "group")
    estado = _um(params, "status")
    confianca = _um(params, "confidence")
    procedimento = _um(params, "procedure")
    termo = normalize_text(_um(params, "q"))

    if estado and estado not in (CANDIDATE, *DECISIONS):
        raise ApiError(f"status inválido: {estado}. Válidos: {CANDIDATE}, {', '.join(DECISIONS)}")
    if confianca and confianca not in CONFIDENCE_LABELS:
        raise ApiError(f"confidence inválida: {confianca}. Válidas: {', '.join(CONFIDENCE_LABELS)}")

    itens: list[dict[str, Any]] = []
    contagem_status = {chave: 0 for chave in (CANDIDATE, *DECISIONS)}
    contagem_conf = {chave: 0 for chave in CONFIDENCE_LABELS}

    for identificador, regra in modelo.rules.items():
        payload = modelo.rule_payload(identificador)
        if payload is None:
            continue
        contagem_status[payload["status"]] = contagem_status.get(payload["status"], 0) + 1
        contagem_conf[payload["confidence"]] = contagem_conf.get(payload["confidence"], 0) + 1

        if grupo and regra.group_id != grupo:
            continue
        if estado and payload["status"] != estado:
            continue
        if confianca and payload["confidence"] != confianca:
            continue
        if procedimento and (payload.get("procedure") or {}).get("status") != procedimento:
            continue
        if termo and termo not in normalize_text(f"{regra.label} {regra.group_name} {regra.description}"):
            continue
        itens.append(payload)

    itens.sort(key=_ordem_regra)
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 50))
    return {
        "items": pagina,
        "pagination": meta,
        "facets": {
            "by_status": [{"status": c, "label": STATUS_LABELS[c], "value": contagem_status.get(c, 0)}
                          for c in (CANDIDATE, *DECISIONS)],
            "by_confidence": [{"confidence": c, "label": CONFIDENCE_LABELS[c], "value": contagem_conf.get(c, 0)}
                              for c in CONFIDENCE_LABELS],
            "total_unfiltered": len(modelo.rules),
        },
        "note": (
            "Estes são agrupamentos POSSÍVEIS, sugeridos a partir de evidências técnicas. "
            "Nenhum vira regra operacional até que uma pessoa confirme."
        ),
    }


def rule_detail(modelo: ReadModel, rule_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    regra = modelo.rules.get(rule_id)
    if regra is None:
        raise ApiError(f"Regra {rule_id} não existe neste escopo.", 404)

    payload = modelo.rule_payload(rule_id) or {}
    alertas = [modelo.by_trigger[t] for t in regra.alert_ids if t in modelo.by_trigger]
    pagina, meta = paginate(alertas, _int(params, "page", 1), _int(params, "per_page", 25))

    familias = [modelo.families[f] for f in regra.family_ids if f in modelo.families]
    familias.sort(key=lambda f: -len(f.alert_ids))

    # Dependências dentro da regra: o Zabbix já disse que estes triggers se
    # relacionam, e é isso que sustenta boa parte da confiança.
    dependencias = []
    dentro = set(regra.alert_ids)
    for alerta in alertas:
        for dependencia in alerta["zabbix"].get("dependencies") or []:
            destino = str(dependencia.get("triggerid") or "")
            dependencias.append({
                "from": {"id": alerta["zabbix"]["triggerid"], "description": alerta["zabbix"]["description_raw"]},
                "to": {"id": destino, "description": dependencia.get("description", "")},
                "internal": destino in dentro,
            })

    return {
        **payload,
        # `instances` continua sendo a CONTAGEM (vem do payload); a lista
        # paginada tem nome próprio.
        "instances_page": _instancias_da_regra(modelo, regra, params),
        "families_list": [f.resumo(modelo.procedure_of_family(f.id)) for f in familias[:50]],
        "hosts_list": [{"id": h, "name": n} for h, n in sorted(regra.hosts.items(), key=lambda kv: kv[1])],
        "dependencies_list": dependencias[:60],
        "item_prefixes": sorted(({"prefix": k, "alerts": v} for k, v in regra.item_prefixes.items()),
                                key=lambda i: -i["alerts"])[:12],
        "alerts_page": {"items": [resumo_alerta(modelo, a) for a in pagina], "pagination": meta},
    }


def _instancias_da_regra(modelo: ReadModel, regra: Any, params: dict[str, list[str]]) -> dict[str, Any]:
    """Onde a regra está aplicada. Paginada: uma regra pode ter milhares.

    Uma família de LLD com 8.131 alertas tem milhares de instâncias — a tela
    mostra o total e uma página de exemplos, nunca a lista inteira.
    """
    ordenadas = sorted(regra.instances.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    itens = [{"name": nome, "alerts": len(triggers), "alert_ids": triggers[:10]}
             for nome, triggers in ordenadas]
    pagina, meta = paginate(itens, _int(params, "instance_page", 1), _int(params, "instance_per_page", 30))
    return {"total": len(itens), "items": pagina, "pagination": meta}


def rule_instances(modelo: ReadModel, rule_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    regra = modelo.rules.get(rule_id)
    if regra is None:
        raise ApiError(f"Regra {rule_id} não existe neste escopo.", 404)
    return _instancias_da_regra(modelo, regra, params)


def rule_alerts(modelo: ReadModel, rule_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    regra = modelo.rules.get(rule_id)
    if regra is None:
        raise ApiError(f"Regra {rule_id} não existe neste escopo.", 404)

    instancia = _um(params, "instance")
    ids = regra.instances.get(instancia, []) if instancia else regra.alert_ids
    alertas = [modelo.by_trigger[t] for t in ids if t in modelo.by_trigger]
    pagina, meta = paginate(alertas, _int(params, "page", 1), _int(params, "per_page", 50))
    return {"items": [resumo_alerta(modelo, a) for a in pagina], "pagination": meta,
            "instance": instancia or None}


def rule_families(modelo: ReadModel, rule_id: str, _params: dict[str, list[str]]) -> dict[str, Any]:
    regra = modelo.rules.get(rule_id)
    if regra is None:
        raise ApiError(f"Regra {rule_id} não existe neste escopo.", 404)
    familias = [modelo.families[f] for f in regra.family_ids if f in modelo.families]
    familias.sort(key=lambda f: -len(f.alert_ids))
    return {"items": [f.resumo(modelo.procedure_of_family(f.id)) for f in familias],
            "total": len(familias)}


def rule_suggestions(modelo: ReadModel, rule_id: str, _params: dict[str, list[str]]) -> dict[str, Any]:
    """Por que o sistema sugeriu este agrupamento — item 27.

    Só evidências observadas. Nada aqui é diagnóstico, causa ou procedimento:
    a IA não escreve neste projeto, e a heurística tampouco.
    """
    regra = modelo.rules.get(rule_id)
    if regra is None:
        raise ApiError(f"Regra {rule_id} não existe neste escopo.", 404)
    nivel, motivos = regra.confidence()
    return {
        "rule_id": rule_id,
        "confidence": nivel,
        "confidence_label": CONFIDENCE_LABELS[nivel],
        "reasons": motivos,
        "evidence_samples": regra.evidence_samples,
        "item_prefixes": sorted(({"prefix": k, "alerts": v} for k, v in regra.item_prefixes.items()),
                                key=lambda i: -i["alerts"]),
        "disclaimer": (
            "Agrupamento sugerido por heurística determinística e local, a partir de chaves "
            "de item, descrições e dependências entre triggers. Não é um diagnóstico e não "
            "afirma que estes alertas têm a mesma causa."
        ),
    }


def decide_rule(modelo: ReadModel, rule_id: str, corpo: dict[str, Any]) -> dict[str, Any]:
    """Confirma, ignora ou mantém separado um candidato. Escrita LOCAL."""
    if rule_id not in modelo.rules:
        raise ApiError(f"Regra {rule_id} não existe neste escopo.", 404)
    estado = str(corpo.get("status") or "")
    try:
        registro = modelo.decisions.set(
            rule_id, estado, note=str(corpo.get("note") or ""), by=str(corpo.get("by") or ""),
        )
    except DecisionError as exc:
        raise ApiError(str(exc), 400) from exc
    return {"saved": True, "rule_id": rule_id, "status": registro["status"],
            "label": STATUS_LABELS.get(registro["status"], registro["status"])}


# ----------------------------------------------------------------------- grupos
def groups(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    """Os grupos como unidade de TRABALHO: "hoje vou documentar este grupo"."""
    termo = normalize_text(_um(params, "q"))
    itens = []
    for identificador, registro in modelo.host_groups.items():
        if termo and termo not in normalize_text(registro["name"]):
            continue
        itens.append(_resumo_grupo_trabalho(modelo, identificador, registro))
    # Grupos com mais trabalho pendente primeiro.
    itens.sort(key=lambda g: (-g["rules"]["pending"], -g["alerts"], g["name"].lower()))
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 60))
    return {"items": pagina, "pagination": meta, "facets": {"total_unfiltered": len(modelo.host_groups)}}


def _resumo_grupo_trabalho(modelo: ReadModel, group_id: str, registro: dict[str, Any]) -> dict[str, Any]:
    ids = modelo.rules_by_group.get(group_id, [])
    documentadas = em_andamento = pendentes = confirmadas = 0
    for identificador in ids:
        decisao = modelo.decision_of_rule(identificador)
        if decisao["status"] == "ignored":
            continue
        if decisao["status"] == "confirmed":
            confirmadas += 1
        estado = modelo.procedure_of_rule(identificador)["status"]
        if estado in ("documented",):
            documentadas += 1
        elif estado in ("draft", "needs_review"):
            em_andamento += 1
        else:
            pendentes += 1

    ativas = documentadas + em_andamento + pendentes
    return {
        "id": group_id,
        "name": registro["name"],
        "hosts": len(registro["host_ids"]),
        "alerts": len(registro["alert_ids"]),
        "families": len(registro["family_ids"]),
        "severities": ordenar_severidades(registro["severities"]),
        "rules": {
            "total": len(ids),
            "active": ativas,
            "confirmed": confirmadas,
            "documented": documentadas,
            "in_progress": em_andamento,
            "pending": pendentes,
            # O progresso conta REGRAS, não alertas: é a unidade de trabalho.
            "progress": round(documentadas / ativas * 100) if ativas else 0,
        },
    }


def group_detail(modelo: ReadModel, group_id: str, params: dict[str, list[str]]) -> dict[str, Any]:
    registro = modelo.host_groups.get(group_id)
    if registro is None:
        raise ApiError(f"Grupo {group_id} não existe neste escopo.", 404)
    parametros = dict(params)
    parametros["group"] = [group_id]
    return {
        **_resumo_grupo_trabalho(modelo, group_id, registro),
        "rules_page": rules(modelo, parametros),
        "hosts_list": sorted(
            (_resumo_host(modelo, modelo.hosts[h]) for h in registro["host_ids"] if h in modelo.hosts),
            key=lambda h: (-h["alerts"], h["name"].lower()),
        )[:60],
    }


# --------------------------------------------------------------------- colisões
def collisions(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    termo = _um(params, "q").lower()
    itens = []
    for colisao in modelo.collisions:
        if termo and termo not in str(colisao.get("alert_key", "")).lower():
            continue
        ocorrencias = colisao.get("occurrences") or []
        itens.append({
            **colisao,
            "triggers": len(ocorrencias),
            "hosts": sorted({o.get("host", "") for o in ocorrencias if o.get("host")}),
            "severities": sorted({o.get("priority", "") for o in ocorrencias if o.get("priority")}),
            "descriptions": sorted({o.get("description_raw", "") for o in ocorrencias}),
        })
    itens.sort(key=lambda c: -c["triggers"])
    pagina, meta = paginate(itens, _int(params, "page", 1), _int(params, "per_page", 25))
    return {
        "items": pagina,
        "pagination": meta,
        # A interface repete isto na tela: colisão é caso para análise, não
        # veredito de erro de configuração.
        "note": (
            "Uma colisão indica que a mesma alert_key agrupa triggers tecnicamente "
            "diferentes. Isso PODE ser duplicidade no Zabbix, mas também pode ser um "
            "par avisar/agir legítimo. Cada caso precisa de análise humana."
        ),
    }


# ----------------------------------------------------------------------- status
def _scope_info(modelo: ReadModel) -> dict[str, Any]:
    """O escopo ativo e o que ele deixou de fora — sempre visível."""
    return {
        **modelo.scope.to_dict(),
        "alerts_in_scope": len(modelo.alerts),
        "alerts_out_of_scope": len(modelo.out_of_scope),
        "collisions_out_of_scope": max(0, getattr(modelo, "collisions_total", 0) - len(modelo.collisions)),
    }


def _snapshot_info(modelo: ReadModel) -> dict[str, Any]:
    meta = modelo.meta
    escopo = meta.get("scope") or {}
    colecao = meta.get("collection") or {}
    return {
        "name": modelo.snapshot_dir.name,
        "path": str(modelo.snapshot_dir),
        "collected_at": meta.get("collected_at", ""),
        "zabbix_version": meta.get("zabbix_version", ""),
        "scope_label": escopo.get("label", "?"),
        "complete_environment": bool(escopo.get("complete_environment")),
        "partial": bool(colecao.get("partial")),
        "duration_seconds": colecao.get("duration_seconds"),
        "page_size": colecao.get("page_size"),
        "pages": colecao.get("pages"),
        "retries": colecao.get("retries", 0),
        "redaction": meta.get("redaction") or {},
    }


def status(modelo: ReadModel, cache: Any, _params: dict[str, list[str]]) -> dict[str, Any]:
    meta = modelo.meta
    return {
        "snapshot": _snapshot_info(modelo),
        # A página de status descreve a COLETA. `counts` é sempre do ambiente
        # inteiro, escopo nenhum: é o retrato do que existe no Zabbix.
        "environment": modelo.environment,
        "scope": _scope_info(modelo),
        "scopes": cache.scopes.listar(),
        "counts": {
            "alerts": modelo.environment["alerts"],
            "alert_keys": len({a.get("alert_key") for a in modelo.alerts + modelo.out_of_scope}),
            "families": modelo.environment["families"],
            "hosts": modelo.environment["hosts"],
            "host_groups": modelo.environment["host_groups"],
            "collisions": getattr(modelo, "collisions_total", len(modelo.collisions)),
            # 0 templates é um estado válido: o usuário da API pode não ter
            # acesso aos grupos de templates. Não é erro da coleta.
            "templates": (modelo.report.get("counts") or {}).get("templates", 0),
        },
        "collection": meta.get("collection") or {},
        "merge": meta.get("merge") or {},
        "available_snapshots": cache.available_snapshots(),
        "read_only": True,
        "note": (
            "Esta interface lê o snapshot em disco. Ela não possui credencial do "
            "Zabbix e não executa nenhuma operação na API do Zabbix."
        ),
    }


# ------------------------------------------------------------------ busca global
def search(modelo: ReadModel, params: dict[str, list[str]]) -> dict[str, Any]:
    termo = _um(params, "q")
    agulha = normalize_text(termo)
    if not agulha:
        return {"query": termo, "scope": {"id": modelo.scope.id, "label": modelo.scope.label},
                "out_of_scope_alerts": 0, "groups": []}

    limite = _int(params, "limit", 8)
    ids = modelo.search_ids(termo) or []

    alertas = [resumo_alerta(modelo, modelo.by_trigger[t]) for t in ids[:limite]]

    familias = [
        f for f in modelo.families.values() if agulha in normalize_text(f"{f.label} {f.origin}")
    ]
    familias.sort(key=lambda f: -len(f.alert_ids))

    hosts_encontrados = [
        _resumo_host(modelo, h) for h in modelo.hosts.values()
        if agulha in normalize_text(f"{h['name']} {h['technical_name']}")
    ]
    hosts_encontrados.sort(key=lambda h: -h["alerts"])

    grupos = [
        _resumo_grupo(modelo, g) for g in modelo.host_groups.values()
        if agulha in normalize_text(g["name"])
    ]

    procedimentos = []
    for familia in modelo.families.values():
        procedimento = modelo.procedure_of_family(familia.id)
        if not procedimento["exists"]:
            continue
        texto = normalize_text(str(procedimento.get("operational") or ""))
        if agulha in texto:
            procedimentos.append(familia.resumo(procedimento))

    # Quantos resultados existem ALÉM do escopo. A busca não os traz, mas
    # dizer "nada encontrado" quando existem 8.000 fora seria enganoso — e é
    # exatamente o tipo de silêncio que o escopo não pode produzir.
    fora_do_escopo = modelo.count_out_of_scope(termo)

    grupos_resultado = [
        {"kind": "alerts", "label": "Alertas", "total": len(ids), "items": alertas},
        {"kind": "families", "label": "Famílias", "total": len(familias),
         "items": [f.resumo(modelo.procedure_of_family(f.id)) for f in familias[:limite]]},
        {"kind": "hosts", "label": "Hosts", "total": len(hosts_encontrados),
         "items": hosts_encontrados[:limite]},
        {"kind": "host_groups", "label": "Host groups", "total": len(grupos), "items": grupos[:limite]},
        {"kind": "procedures", "label": "Procedimentos", "total": len(procedimentos),
         "items": procedimentos[:limite]},
    ]
    return {
        "query": termo,
        "scope": {"id": modelo.scope.id, "label": modelo.scope.label},
        "out_of_scope_alerts": fora_do_escopo,
        "groups": [g for g in grupos_resultado if g["total"]],
    }
