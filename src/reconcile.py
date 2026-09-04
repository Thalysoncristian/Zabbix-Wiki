"""Reconciliação: snapshot coletado -> fichas em `docs/alerts/`.

O que este módulo **nunca** faz:

* apagar documentação humana;
* sobrescrever o bloco `operational`;
* rebaixar o `doc_status` de uma ficha documentada por conta própria (só a
  marca como `review_needed`, que é um pedido de revisão, não uma perda).

O que ele faz a cada coleta:

    alerta novo no Zabbix          -> cria ficha `undocumented`  (🆕 novo alerta)
    fato técnico mudou             -> `documented`/`reviewed` -> `review_needed`
    alerta sumiu da coleta         -> marca `present_in_zabbix: false`, mantém tudo
    alerta voltou                  -> marca presente de novo

A comparação usa `source_hash` — só o fato técnico. Editar a ficha nunca
dispara `review_needed`, e mudar o `triggerid` (trigger recriado no Zabbix)
nunca faz a documentação ser perdida, porque a identidade é a `alert_key`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .core.models import (
    LEVEL_FAMILY,
    LEVEL_INSTANCE,
    AlertDoc,
    build_family_key,
    compute_family_hash,
    utc_now,
)
from .core.repository import AlertRepository
from .core.status import DOCUMENTED_STATUSES, REVIEW_NEEDED


@dataclass
class ReconcileResult:
    """O que a reconciliação fez — cada item é uma ficha tocada."""

    created: list[str] = field(default_factory=list)
    marked_review_needed: list[dict[str, str]] = field(default_factory=list)
    technical_updated: list[str] = field(default_factory=list)
    disappeared: list[str] = field(default_factory=list)
    reappeared: list[str] = field(default_factory=list)
    unchanged: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "created": len(self.created),
            "marked_review_needed": len(self.marked_review_needed),
            "technical_updated": len(self.technical_updated),
            "disappeared": len(self.disappeared),
            "reappeared": len(self.reappeared),
            "unchanged": self.unchanged,
        }


def group_by_doc_level(alerts: Iterable[dict[str, Any]], *, family_threshold: int = 2) -> dict[str, str]:
    """Decide o nível de ficha de cada alerta: instância ou família.

    Uma família com muitas instâncias (serviços do Windows, pontos de montagem,
    chamados descobertos) não deve virar N fichas idênticas — o procedimento é
    da família. Já um alerta que é o único da sua família vira ficha própria,
    que é o caso dos triggers escritos à mão para um host específico.

    Devolve `alert_key -> doc_level`.
    """
    familias: dict[str, list[dict[str, Any]]] = {}
    for alerta in alerts:
        familias.setdefault(build_family_key(alerta), []).append(alerta)

    nivel: dict[str, str] = {}
    for membros in familias.values():
        chaves_distintas = {a["alert_key"] for a in membros}
        alvo = LEVEL_FAMILY if len(chaves_distintas) >= family_threshold else LEVEL_INSTANCE
        for alerta in membros:
            nivel[alerta["alert_key"]] = alvo
    return nivel


def family_representative(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Escolhe o alerta que representa tecnicamente a família.

    O bloco `zabbix` da ficha de família precisa mostrar *algo* concreto. Usamos
    a instância de descrição mais curta — normalmente a menos poluída por
    valores descobertos — de forma determinística.
    """
    return min(alerts, key=lambda a: (len(a["zabbix"].get("description_raw", "")), a["alert_key"]))


def reconcile(
    alerts: list[dict[str, Any]],
    repository: AlertRepository,
    *,
    family_threshold: int = 2,
    prune_missing: bool = True,
    scope_host_groups: Iterable[str] = (),
) -> ReconcileResult:
    """Aplica um snapshot normalizado sobre as fichas existentes.

    `scope_host_groups` deve receber o filtro de grupos usado na coleta. Sem
    isso, uma coleta de um grupo só marcaria como "sumidas do Zabbix" todas as
    fichas dos outros grupos — que simplesmente não estavam no escopo daquela
    execução. Vazio significa coleta do ambiente inteiro.
    """
    resultado = ReconcileResult()
    niveis = group_by_doc_level(alerts, family_threshold=family_threshold)

    # Agrupa o que vai virar ficha: família (uma ficha para N alertas) ou
    # instância (uma ficha por alerta).
    fichas: dict[str, dict[str, Any]] = {}
    for alerta in alerts:
        if niveis[alerta["alert_key"]] == LEVEL_FAMILY:
            chave = build_family_key(alerta)
            fichas.setdefault(chave, {"level": LEVEL_FAMILY, "alerts": []})["alerts"].append(alerta)
        else:
            fichas[alerta["alert_key"]] = {"level": LEVEL_INSTANCE, "alerts": [alerta]}

    vistas: set[str] = set()
    for chave, grupo in fichas.items():
        membros = grupo["alerts"]
        representante = family_representative(membros) if grupo["level"] == LEVEL_FAMILY else membros[0]
        vistas.add(chave)
        _aplicar(chave, grupo["level"], representante, membros, repository, resultado)

    if prune_missing:
        _marcar_ausentes(repository, vistas, resultado, set(scope_host_groups))

    return resultado


def _aplicar(
    chave: str,
    nivel: str,
    representante: dict[str, Any],
    membros: list[dict[str, Any]],
    repository: AlertRepository,
    resultado: ReconcileResult,
) -> None:
    zbx = dict(representante["zabbix"])
    if nivel == LEVEL_FAMILY:
        # O bloco técnico da ficha de família mostra uma instância concreta como
        # amostra, mas a comparação de mudança usa o hash da família.
        zbx["family_source_hash"] = compute_family_hash(membros)
        zbx["representative_of_family"] = True
        zbx["family_instance_count"] = len({a["alert_key"] for a in membros})

    instancias = sorted(
        (
            {
                "alert_key": a["alert_key"],
                "triggerid": a["zabbix"]["triggerid"],
                "host": a["zabbix"]["host"]["name"] or a["zabbix"]["host"]["host"],
                "description": a["zabbix"]["description_raw"],
            }
            for a in membros
        ),
        key=lambda i: (i["host"], i["description"]),
    )

    existente = repository.get(chave)

    if existente is None:
        doc = AlertDoc.from_collected_alert(representante, doc_level=nivel)
        doc.zabbix = zbx
        doc.alert_key = chave
        doc.family_key = build_family_key(representante)
        doc.instances = instancias
        repository.save(doc)
        resultado.created.append(chave)
        return

    hash_anterior = existente.source_hash
    # Os dois lados da comparação precisam ser do mesmo tipo: hash de família
    # numa ficha de família, hash de instância numa ficha de instância.
    hash_atual = zbx.get("family_source_hash") if nivel == LEVEL_FAMILY else zbx.get("source_hash")

    # O bloco técnico é sempre substituído: ele é um fato, não uma opinião.
    existente.zabbix = zbx
    existente.instances = instancias
    existente.doc_level = nivel
    existente.family_key = build_family_key(representante)
    existente.last_seen_at = zbx.get("collected_at") or utc_now()

    if not existente.present_in_zabbix:
        existente.present_in_zabbix = True
        resultado.reappeared.append(chave)

    if hash_anterior and hash_atual and hash_anterior != hash_atual:
        resultado.technical_updated.append(chave)
        # Documentação validada + fato técnico diferente = precisa de revisão
        # humana. O conteúdo permanece; só o estado muda.
        if existente.doc_status in DOCUMENTED_STATUSES:
            existente.operational["doc_status"] = REVIEW_NEEDED
            resultado.marked_review_needed.append(
                {"alert_key": chave, "from_hash": hash_anterior, "to_hash": hash_atual}
            )
    else:
        resultado.unchanged += 1

    existente.touch()
    repository.save(existente)


def _marcar_ausentes(
    repository: AlertRepository,
    vistas: set[str],
    resultado: ReconcileResult,
    escopo: set[str],
) -> None:
    """Alerta que sumiu do Zabbix: a ficha é preservada, apenas sinalizada.

    Sumir da coleta não significa que o conhecimento perdeu valor — o trigger
    pode ter sido recriado ou desabilitado temporariamente.

    Só são avaliadas as fichas dentro do escopo da coleta. Numa coleta
    filtrada por grupo, as fichas dos demais grupos não estavam sendo
    procuradas e portanto não "sumiram".
    """
    for doc in repository.all():
        if doc.alert_key in vistas or doc.scope != "zabbix" or not doc.present_in_zabbix:
            continue
        if escopo and not escopo.intersection((doc.zabbix or {}).get("host_groups") or []):
            continue
        doc.present_in_zabbix = False
        doc.touch()
        repository.save(doc)
        resultado.disappeared.append(doc.alert_key)
