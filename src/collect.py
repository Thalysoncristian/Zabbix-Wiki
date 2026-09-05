"""Coleta bruta (read-only) dos dados do Zabbix necessários à ficha operacional.

Ordem da coleta e como os relacionamentos são resolvidos:

    trigger  ->  item  ->  host  ->  host group
                              \\->  template
    trigger  ->  template de origem (cadeia `templateid`)
    trigger  ->  protótipo (quando o trigger foi criado por LLD)
    trigger  ->  dependências (nomes resolvidos)

Nada aqui escreve no Zabbix: todas as chamadas passam pela allowlist do
`ZabbixReadOnlyClient`.

## Escala (Fase 2)

O ambiente real tem ~19.000 triggers e uma coleta que tentasse trazer tudo de
uma vez devolvia HTTP 500. A coleta é feita em três estágios, nenhum deles
dependendo de uma requisição gigante:

    1. escopo      hostgroup.get -> host.get por grupo -> hosts deduplicados
    2. descoberta  trigger.get { hostids: lote, output: ["triggerid"] }
                   consulta barata: sem `select*`, só o ID. É ela que dá o
                   TOTAL REAL usado no progresso.
    3. hidratação  trigger.get { triggerids: página, output+selects completos }
                   página configurável, com retry e redução adaptativa de lote.

Por que não `limit`/`offset`: a API do Zabbix aceita `limit`, mas **não tem
`offset`**. Não existe "próxima página" nativa. Paginar por conjunto de IDs é o
mecanismo equivalente que a API realmente oferece — e ainda tem a vantagem de
ser determinístico e retomável, porque a lista de IDs é conhecida antes de
começar a parte cara.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

from .progress import ProgressHandler, noop
from .redact import redact_snapshot_data
from .zabbix_client import ZabbixError, ZabbixReadOnlyClient, ZabbixTransientError

logger = logging.getLogger(__name__)

MAX_TEMPLATE_CHAIN_DEPTH = 10

#: Escopos possíveis de uma coleta — vão para o snapshot e para o relatório,
#: para que uma coleta parcial nunca seja lida como se fosse o ambiente inteiro.
SCOPE_ENVIRONMENT = "environment"
SCOPE_HOST_GROUPS = "host_groups"
SCOPE_SAMPLE = "sample"

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
class CollectionScope:
    """O que esta coleta cobriu — e, principalmente, o que ela NÃO cobriu.

    `complete` só é verdadeiro quando a coleta varreu o ambiente inteiro e
    nenhum objeto ficou para trás. Um snapshot de um grupo, ou uma coleta que
    perdeu páginas, jamais é apresentado como retrato do ambiente.
    """

    kind: str = SCOPE_ENVIRONMENT
    host_groups: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    groups_available: int = 0
    hosts: int = 0
    limit: int | None = None
    only_monitored: bool = False
    include_template_triggers: bool = False
    #: IDs dos hosts do escopo, já deduplicados entre grupos. Fica fora do
    #: `to_dict()` de propósito: é insumo da coleta, não metadado do snapshot.
    host_ids: list[str] = field(default_factory=list, repr=False)

    @property
    def complete(self) -> bool:
        return self.kind == SCOPE_ENVIRONMENT and self.limit is None

    @property
    def label(self) -> str:
        if self.kind == SCOPE_SAMPLE:
            return f"amostra de até {self.limit} triggers"
        if self.kind == SCOPE_HOST_GROUPS:
            return f"{len(self.host_groups)} grupo(s) de hosts: {', '.join(self.host_groups)}"
        return "ambiente inteiro"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "complete_environment": self.complete,
            "host_groups": list(self.host_groups),
            "group_ids": list(self.group_ids),
            "groups_available": self.groups_available,
            "hosts": self.hosts,
            "limit": self.limit,
            "only_monitored": self.only_monitored,
            "include_template_triggers": self.include_template_triggers,
        }


@dataclass
class CollectionStats:
    """Como a coleta se comportou: páginas, retries, falhas, duração."""

    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    page_size: int = 0
    pages: int = 0
    retries: int = 0
    batch_reductions: list[dict[str, Any]] = field(default_factory=list)
    failed_objects: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    resumed_from: str | None = None

    @property
    def partial(self) -> bool:
        """Coleta parcial: alguma página ou fase não terminou."""
        return bool(self.failed_objects or self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 3),
            "page_size": self.page_size,
            "pages": self.pages,
            "retries": self.retries,
            "batch_reductions": self.batch_reductions,
            "failed_objects": self.failed_objects,
            "errors": self.errors,
            "partial": self.partial,
            "resumed_from": self.resumed_from,
        }


#: Atributo pendurado na exceção quando a coleta morre no meio.
#:
#: A alternativa seria embrulhar o erro numa exceção própria — mas isso trocaria
#: o tipo real (um `ZabbixAuthError`, um `KeyboardInterrupt`, um bug de código)
#: por um tipo genérico, e quem trata o erro perderia a informação que importa.
#: Pendurar o snapshot parcial preserva o erro original intacto.
PARTIAL_SNAPSHOT_ATTR = "partial_snapshot"


def partial_snapshot_of(exc: BaseException) -> "RawSnapshot | None":
    """Snapshot parcial de uma coleta interrompida, se houver algo a salvar."""
    snapshot = getattr(exc, PARTIAL_SNAPSHOT_ATTR, None)
    if snapshot is None or not any(snapshot.data.values()):
        return None
    return snapshot


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
    page_size: int | None = None,
    known_trigger_ids: Sequence[str] = (),
    redact_secrets: bool = True,
    on_step: Callable[[str], None] = lambda _msg: None,
    on_progress: ProgressHandler = noop,
) -> RawSnapshot:
    """Executa a coleta do escopo pedido e devolve o snapshot bruto.

    `page_size` controla o tamanho das páginas de hidratação; `None` usa o
    valor do cliente (`ZABBIX_PAGE_SIZE`). `known_trigger_ids` permite retomar
    uma coleta anterior: os IDs listados são somados aos descobertos, mas nunca
    substituem a descoberta — retomar não pode esconder objetos novos.
    """
    inicio = time.monotonic()
    stats = CollectionStats(started_at=utc_now_iso(), page_size=int(page_size or client.page_size))

    def passo(mensagem: str) -> None:
        on_step(mensagem)
        on_progress({"event": "step", "message": mensagem})

    def pagina(evento: dict[str, Any]) -> None:
        if evento.get("event") == "page":
            stats.pages += 1
        on_progress(evento)

    version = client.connect()
    passo(f"Conectado ao Zabbix (API {version}, {client.auth_description})")

    scope = _resolve_scope(client, host_groups, limit, only_monitored, include_template_triggers, passo, on_progress)

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
    filtros: dict[str, Any] = {}
    if not include_template_triggers:
        filtros["templated"] = False
    if only_monitored:
        filtros["monitored"] = True

    # Tudo daqui para baixo pode falhar num ambiente grande. O que já tiver sido
    # coletado é embrulhado em PartialCollectionError para que a CLI consiga
    # gravar o snapshot parcial em vez de perder horas de coleta.
    trigger_ids: list[str] = []
    triggers: list[dict[str, Any]] = []
    expanded: list[dict[str, Any]] = []
    parent_triggers: list[dict[str, Any]] = []
    trigger_prototypes: list[dict[str, Any]] = []
    dependency_triggers: list[dict[str, Any]] = []
    hosts: list[dict[str, Any]] = []
    host_groups_rows: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    def montar(erro: str = "") -> RawSnapshot:
        return _build_snapshot(
            client=client,
            version=version,
            scope=scope,
            stats=stats,
            inicio=inicio,
            limit=limit,
            only_monitored=only_monitored,
            include_template_triggers=include_template_triggers,
            trigger_ids=trigger_ids,
            fatal_error=erro,
            redact_secrets=redact_secrets,
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
        )

    try:
        trigger_ids = _discover_trigger_ids(client, scope, filtros, passo, on_progress)
        retomados = [t for t in dict.fromkeys(str(i) for i in known_trigger_ids) if t not in set(trigger_ids)]
        if retomados:
            # IDs de uma coleta interrompida que não reapareceram na descoberta:
            # não são descartados nem assumidos como existentes — apenas somados,
            # e a hidratação dirá se ainda estão lá.
            trigger_ids = list(trigger_ids) + retomados
            stats.resumed_from = f"{len(known_trigger_ids)} triggers de uma coleta anterior"

        passo(f"{len(trigger_ids)} triggers no escopo (descoberta concluída)")

        triggers = _hydrate_triggers(client, trigger_ids, trigger_params, filtros, optional_selects, page_size, pagina)
        passo(f"{len(triggers)} triggers coletados")

        # Expressões expandidas: mesma consulta, apenas com expandExpression.
        trigger_ids_coletados = _ids(triggers, "triggerid")
        expanded = client.get_by_ids(
            "trigger.get",
            "triggerids",
            trigger_ids_coletados,
            {
                "output": ["triggerid", "expression", "recovery_expression", "description", "opdata", "event_name"],
                "expandExpression": True,
            },
            page_size=page_size,
            on_page=pagina,
            label="expressões expandidas",
        )
        passo(f"{len(expanded)} expressões expandidas")

        # ------------------------------------------- cadeia de templates do trigger
        parent_triggers = _collect_template_chain(
            client, "trigger.get", _ids(triggers, "templateid"), passo, page_size, pagina
        )

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
                    page_size=page_size,
                    on_page=pagina,
                    label="protótipos de trigger",
                )
                trigger_prototypes += _collect_template_chain(
                    client, "triggerprototype.get", _ids(trigger_prototypes, "templateid"), passo, page_size, pagina
                )
                passo(f"{len(trigger_prototypes)} protótipos de trigger (LLD) resolvidos")
            except ZabbixError as exc:
                # Ambiente sem permissão de leitura em protótipos: a coleta continua,
                # apenas a chave dos triggers descobertos cai no fallback host+descrição.
                logger.warning("Não foi possível resolver protótipos de trigger: %s", exc)
                stats.errors.append({"phase": "trigger_prototypes", "error": str(exc)[:300], "fatal": False})
                passo(f"Protótipos de trigger não resolvidos ({exc})")

        # ------------------------------------------------------------- dependências
        dependency_ids = _nested_ids(triggers, "dependencies", "triggerid")
        dependency_triggers = (
            client.get_by_ids(
                "trigger.get",
                "triggerids",
                dependency_ids,
                {"output": ["triggerid", "description", "priority"], "selectHosts": ["hostid", "host", "name"]},
                page_size=page_size,
                on_page=pagina,
                label="dependências",
            )
            if dependency_ids
            else []
        )

        # -------------------------------------------------------------------- hosts
        host_ids = _nested_ids(triggers, "hosts", "hostid")
        hosts = _get_hosts(client, host_ids, page_size, pagina)
        passo(f"{len(hosts)} hosts resolvidos")

        # -------------------------------------------------------------- host groups
        group_ids = _nested_ids(hosts, "hostgroups", "groupid") + _nested_ids(hosts, "groups", "groupid")
        host_groups_rows = (
            client.get_by_ids(
                "hostgroup.get", "groupids", group_ids, {"output": ["groupid", "name"]},
                page_size=page_size, on_page=pagina, label="grupos de hosts",
            )
            if group_ids
            else []
        )
        passo(f"{len(host_groups_rows)} grupos de hosts resolvidos")

        # ---------------------------------------------------------------- templates
        template_ids = (
            _nested_ids(hosts, "parentTemplates", "templateid")
            + _nested_ids(parent_triggers, "hosts", "hostid")
            + _nested_ids(trigger_prototypes, "hosts", "hostid")
        )
        templates = (
            client.get_by_ids(
                "template.get", "templateids", template_ids, {"output": ["templateid", "host", "name"]},
                page_size=page_size, on_page=pagina, label="templates",
            )
            if template_ids
            else []
        )
        passo(f"{len(templates)} templates resolvidos")

        # -------------------------------------------------------------------- itens
        item_ids = _nested_ids(triggers, "items", "itemid")
        items = _get_items(client, item_ids, page_size, pagina)
        passo(f"{len(items)} itens relacionados resolvidos")
    except BaseException as exc:
        # Qualquer falha aqui: o erro sobe como veio, mas leva junto o que já
        # foi coletado. Uma coleta de horas não pode voltar de mãos vazias.
        setattr(exc, PARTIAL_SNAPSHOT_ATTR, montar(str(exc) or exc.__class__.__name__))
        raise

    return montar()


def _build_snapshot(
    *,
    client: ZabbixReadOnlyClient,
    version: str,
    scope: CollectionScope,
    stats: CollectionStats,
    inicio: float,
    limit: int | None,
    only_monitored: bool,
    include_template_triggers: bool,
    trigger_ids: Sequence[str],
    data: dict[str, list[dict[str, Any]]],
    fatal_error: str = "",
    redact_secrets: bool = True,
) -> RawSnapshot:
    """Monta o snapshot a partir do que foi coletado — completo ou parcial.

    A redação de segredos acontece AQUI, antes de qualquer gravação e antes da
    normalização: assim `source_hash` e `expression_signature` já nascem
    calculados sobre o texto redigido, e nenhum segredo chega ao disco nem à
    interface web.
    """
    stats.finished_at = utc_now_iso()
    stats.duration_seconds = time.monotonic() - inicio
    stats.retries = client.retries
    stats.batch_reductions = list(client.batch_reductions)
    stats.failed_objects = list(client.failed_objects)

    meta = {
        "collector_version": "0.2.0",
        "collected_at": utc_now_iso(),
        "collected_at_local": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "zabbix_endpoint": client.endpoint,
        "zabbix_version": version,
        "auth_method": client.auth_description,
        "read_only": True,
        # `filters` é mantido com o formato da Fase 1: o reconcile e os snapshots
        # antigos leem `filters.host_groups`.
        "filters": {
            "host_groups": list(scope.host_groups),
            "limit": limit,
            "only_monitored": only_monitored,
            "include_template_triggers": include_template_triggers,
        },
        "scope": scope.to_dict(),
        "collection": stats.to_dict(),
        "discovered_trigger_ids": list(trigger_ids),
    }
    if redact_secrets:
        data, relatorio = redact_snapshot_data(data)
        meta["redaction"] = relatorio
        if relatorio["values_redacted"]:
            logger.warning(
                "%d valor(es) com aparência de segredo foram redigidos no snapshot",
                relatorio["values_redacted"],
            )
    else:
        meta["redaction"] = {"enabled": False, "values_redacted": 0, "by_collection": {}}

    if fatal_error:
        # Uma coleta que morreu no meio é parcial mesmo que nenhuma página
        # individual tenha falhado: faltam fases inteiras.
        meta["collection"]["partial"] = True
        meta["collection"]["interrupted_by"] = fatal_error[:300]

    return RawSnapshot(meta=meta, data=dict(data), api_calls=list(client.call_log))


# --------------------------------------------------------------------- escopo
def _resolve_scope(
    client: ZabbixReadOnlyClient,
    host_groups: Iterable[str],
    limit: int | None,
    only_monitored: bool,
    include_template_triggers: bool,
    passo: Callable[[str], None],
    on_progress: ProgressHandler,
) -> CollectionScope:
    """Resolve o escopo em grupos e hosts, sempre grupo a grupo.

    Mesmo na coleta do ambiente inteiro os hosts são resolvidos por grupo: é o
    que permite mostrar progresso por grupo e, principalmente, o que evita
    depender de uma única resposta contendo o ambiente todo. Hosts que estão em
    mais de um grupo são deduplicados — senão os triggers deles seriam
    baixados uma vez por grupo.
    """
    pedidos = [g for g in host_groups if g]

    if limit and not pedidos:
        # Coleta de amostra: nem precisa enumerar o ambiente.
        return CollectionScope(
            kind=SCOPE_SAMPLE, limit=limit, only_monitored=only_monitored,
            include_template_triggers=include_template_triggers,
        )

    if pedidos:
        encontrados = client.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": pedidos}}) or []
        faltando = sorted(set(pedidos) - {row.get("name") for row in encontrados})
        if faltando:
            raise ZabbixError(f"Grupos de hosts não encontrados no Zabbix: {', '.join(faltando)}")
        grupos = sorted(encontrados, key=lambda g: str(g.get("name") or ""))
        kind = SCOPE_HOST_GROUPS
        disponiveis = len(grupos)
        passo(f"Filtro por grupos: {', '.join(pedidos)}")
    else:
        grupos = sorted(
            client.call("hostgroup.get", {"output": ["groupid", "name"]}) or [],
            key=lambda g: str(g.get("name") or ""),
        )
        kind = SCOPE_ENVIRONMENT
        disponiveis = len(grupos)
        passo(f"{len(grupos)} grupos de hosts no ambiente — a coleta percorre um grupo por vez")

    scope = CollectionScope(
        kind=kind,
        host_groups=[str(g.get("name") or "") for g in grupos],
        group_ids=_ids(grupos, "groupid"),
        groups_available=disponiveis,
        limit=limit,
        only_monitored=only_monitored,
        include_template_triggers=include_template_triggers,
    )
    scope.host_ids = _resolve_host_ids_by_group(client, grupos, on_progress)
    scope.hosts = len(scope.host_ids)
    on_progress({"event": "scope", "host_groups": scope.host_groups if kind == SCOPE_HOST_GROUPS else [],
                 "hosts": scope.hosts})
    return scope


def _resolve_host_ids_by_group(
    client: ZabbixReadOnlyClient,
    grupos: list[dict[str, Any]],
    on_progress: ProgressHandler,
) -> list[str]:
    """host.get por grupo, com deduplicação global dos hosts."""
    vistos: dict[str, None] = {}
    total = len(grupos)
    for indice, grupo in enumerate(grupos, start=1):
        gid = str(grupo.get("groupid") or "")
        if not gid:
            continue
        linhas = client.call("host.get", {"output": ["hostid"], "groupids": [gid]}) or []
        novos = 0
        for hostid in _ids(linhas, "hostid"):
            if hostid not in vistos:
                vistos[hostid] = None
                novos += 1
        on_progress(
            {
                "event": "group",
                "index": indice,
                "groups": total,
                "name": str(grupo.get("name") or ""),
                "hosts": len(linhas),
                "new_hosts": novos,
            }
        )
    return list(vistos)


# ------------------------------------------------------------------ descoberta
def _discover_trigger_ids(
    client: ZabbixReadOnlyClient,
    scope: CollectionScope,
    filtros: dict[str, Any],
    passo: Callable[[str], None],
    on_progress: ProgressHandler,
) -> list[str]:
    """Lista os IDs dos triggers do escopo com consultas baratas.

    `output: ["triggerid"]` e nenhum `select*`: a resposta é pequena mesmo com
    dezenas de milhares de triggers. É esta lista que vira o total real do
    progresso e a unidade de paginação da hidratação.
    """
    if scope.kind == SCOPE_SAMPLE:
        return client.list_ids(
            "trigger.get", "triggerid",
            {**filtros, "sortfield": "description", "limit": int(scope.limit or 0)},
        )

    host_ids = scope.host_ids
    if not host_ids:
        return []

    return client.discover_ids(
        "trigger.get",
        "triggerid",
        "hostids",
        host_ids,
        filtros,
        chunk_size=client.trigger_batch_size,
        on_page=on_progress,
        label="descoberta de triggers",
    )


def _hydrate_triggers(
    client: ZabbixReadOnlyClient,
    trigger_ids: Sequence[str],
    params: dict[str, Any],
    filtros: dict[str, Any],
    optional_selects: dict[str, Any],
    page_size: int | None,
    on_page: ProgressHandler,
) -> list[dict[str, Any]]:
    """Busca os triggers completos, em páginas de IDs, tolerando selects ausentes."""
    if not trigger_ids:
        return []
    completos = {**params, **filtros, **optional_selects}
    try:
        return client.fetch_in_chunks(
            "trigger.get", "triggerids", list(trigger_ids), completos,
            page_size=page_size, on_page=on_page, label="triggers",
        )
    except ZabbixError as exc:
        if isinstance(exc, ZabbixTransientError):
            raise
        logger.warning("trigger.get com selects de LLD falhou (%s); repetindo sem eles", exc)
        on_page({"event": "step", "message": f"Aviso: selects de LLD indisponíveis nesta versão ({exc})"})
        return client.fetch_in_chunks(
            "trigger.get", "triggerids", list(trigger_ids), {**params, **filtros},
            page_size=page_size, on_page=on_page, label="triggers",
        )


def _collect_template_chain(
    client: ZabbixReadOnlyClient,
    method: str,
    seed_ids: Iterable[str],
    passo: Callable[[str], None],
    page_size: int | None,
    on_page: ProgressHandler,
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
            page_size=page_size,
            on_page=on_page,
            label=f"cadeia de templates ({method})",
        )
        collected.extend(rows)
        seen.update(batch)
        pending = {str(row.get("templateid")) for row in rows if str(row.get("templateid") or "0") != "0"} - seen
        depth += 1

    if depth >= MAX_TEMPLATE_CHAIN_DEPTH and pending:  # pragma: no cover - defensivo
        passo(f"Aviso: cadeia de templates de {method} truncada em {MAX_TEMPLATE_CHAIN_DEPTH} níveis")
    return collected


def _get_hosts(
    client: ZabbixReadOnlyClient,
    host_ids: Iterable[str],
    page_size: int | None = None,
    on_page: ProgressHandler = noop,
) -> list[dict[str, Any]]:
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
        return client.get_by_ids(
            "host.get", "hostids", ids, {**base, select_groups_key: ["groupid", "name"]},
            page_size=page_size, on_page=on_page, label="hosts",
        )
    except ZabbixError as exc:
        if isinstance(exc, ZabbixTransientError):
            raise
        fallback = "selectGroups" if select_groups_key == "selectHostGroups" else "selectHostGroups"
        logger.warning("host.get com %s falhou (%s); tentando %s", select_groups_key, exc, fallback)
        return client.get_by_ids(
            "host.get", "hostids", ids, {**base, fallback: ["groupid", "name"]},
            page_size=page_size, on_page=on_page, label="hosts",
        )


def _get_items(
    client: ZabbixReadOnlyClient,
    item_ids: Iterable[str],
    page_size: int | None = None,
    on_page: ProgressHandler = noop,
) -> list[dict[str, Any]]:
    """item.get pedindo `name_resolved` quando a versão suportar (Zabbix >= 6.4)."""
    ids = list(item_ids)
    if not ids:
        return []

    from .zabbix_client import parse_version

    output = list(ITEM_OUTPUT)
    if parse_version(client.api_version()) >= (6, 4):
        output.append("name_resolved")
    try:
        return client.get_by_ids(
            "item.get", "itemids", ids, {"output": output},
            page_size=page_size, on_page=on_page, label="itens",
        )
    except ZabbixError as exc:
        if isinstance(exc, ZabbixTransientError) or "name_resolved" not in output:
            raise
        logger.warning("item.get com name_resolved falhou (%s); repetindo sem o campo", exc)
        return client.get_by_ids(
            "item.get", "itemids", ids, {"output": ITEM_OUTPUT},
            page_size=page_size, on_page=on_page, label="itens",
        )
