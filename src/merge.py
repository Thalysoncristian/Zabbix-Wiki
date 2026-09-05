"""Consolidação de vários snapshots independentes em uma base única.

    Vibe Tecnologia (coletado segunda)
    Zabbix servers  (coletado terça)
    Ativos de Rede  (coletado quarta)
                ↓  merge
    base consolidada

## A decisão que importa aqui

O merge acontece no **snapshot bruto**, não nos alertas já normalizados, e a
normalização é refeita sobre o resultado. Parece um detalhe de implementação,
mas não é: colisões de `alert_key`, famílias e regras multi-host só existem
quando se olha o conjunto todo. Dois grupos coletados em dias diferentes podem
ter a mesma `alert_key` com expressões diferentes — colisão que nenhuma das
duas coletas isoladas conseguiria enxergar. Juntar `alerts.json` prontos
esconderia exatamente o que a base precisa mostrar.

## Deduplicação

Cada tipo de objeto tem seu ID natural (`triggerid`, `hostid`, `itemid`,
`groupid`, `templateid`). O mesmo objeto em dois snapshots vira **uma** entrada,
nunca duas. Quando as duas versões diferem — o trigger mudou de severidade
entre as coletas — vence a coleta mais recente, e a divergência é registrada
como conflito no relatório do merge. Nada é resolvido em silêncio.
"""

from __future__ import annotations

from typing import Any, Iterable

from .collect import RawSnapshot, utc_now_iso

#: Campo de identidade de cada coleção do snapshot bruto.
ID_FIELDS: dict[str, str] = {
    "triggers": "triggerid",
    "triggers_expanded": "triggerid",
    "parent_triggers": "triggerid",
    "trigger_prototypes": "triggerid",
    "dependency_triggers": "triggerid",
    "hosts": "hostid",
    "hostgroups": "groupid",
    "templates": "templateid",
    "items": "itemid",
}

#: Campos que mudam a cada coleta sem significar mudança de configuração.
#: Ficam fora da comparação de conflito para não gerar ruído.
VOLATILE_FIELDS = frozenset({"value", "state", "lastchange", "error", "lastvalue", "prevvalue"})


def _fingerprint(row: dict[str, Any]) -> str:
    from .keys import canonical_json

    return canonical_json({k: v for k, v in sorted(row.items()) if k not in VOLATILE_FIELDS})


def merge_raw_snapshots(payloads: Iterable[dict[str, Any]]) -> tuple[RawSnapshot, dict[str, Any]]:
    """Consolida snapshots brutos, deduplicando por ID.

    Devolve o snapshot consolidado e um resumo do merge (fontes, duplicatas
    encontradas, conflitos). A ordem de entrada define a precedência: o último
    snapshot da lista vence em caso de divergência, então passe do mais antigo
    para o mais recente.
    """
    entradas = list(payloads)
    if not entradas:
        raise ValueError("Nenhum snapshot informado para consolidar.")

    dados: dict[str, dict[str, dict[str, Any]]] = {nome: {} for nome in ID_FIELDS}
    origem: dict[str, dict[str, str]] = {nome: {} for nome in ID_FIELDS}
    conflitos: list[dict[str, Any]] = []
    duplicados: dict[str, int] = {nome: 0 for nome in ID_FIELDS}
    fontes: list[dict[str, Any]] = []
    api_calls: list[dict[str, Any]] = []
    grupos_cobertos: list[str] = []
    versoes: set[str] = set()
    escopos: set[str] = set()
    parciais: list[str] = []

    for indice, payload in enumerate(entradas):
        meta = payload.get("meta") or {}
        scope = meta.get("scope") or {}
        colecao = meta.get("collection") or {}
        rotulo = str(meta.get("collected_at") or f"snapshot #{indice + 1}")
        fontes.append(
            {
                "collected_at": meta.get("collected_at"),
                "zabbix_version": meta.get("zabbix_version"),
                "scope": scope.get("label") or ((meta.get("filters") or {}).get("host_groups") or "ambiente inteiro"),
                "kind": scope.get("kind"),
                "host_groups": scope.get("host_groups") or (meta.get("filters") or {}).get("host_groups") or [],
                "partial": bool(colecao.get("partial")),
                "counts": payload.get("counts") or {},
            }
        )
        if colecao.get("partial"):
            parciais.append(rotulo)
        if meta.get("zabbix_version"):
            versoes.add(str(meta["zabbix_version"]))
        escopos.add(str(scope.get("kind") or "desconhecido"))
        for nome in scope.get("host_groups") or (meta.get("filters") or {}).get("host_groups") or []:
            if nome not in grupos_cobertos:
                grupos_cobertos.append(str(nome))
        api_calls.extend(payload.get("api_calls") or [])

        for colecao_nome, id_field in ID_FIELDS.items():
            for linha in (payload.get("data") or {}).get(colecao_nome) or []:
                identificador = str(linha.get(id_field) or "")
                if not identificador:
                    continue
                anterior = dados[colecao_nome].get(identificador)
                if anterior is None:
                    dados[colecao_nome][identificador] = linha
                    origem[colecao_nome][identificador] = rotulo
                    continue
                duplicados[colecao_nome] += 1
                if _fingerprint(anterior) != _fingerprint(linha):
                    conflitos.append(
                        {
                            "collection": colecao_nome,
                            "id": identificador,
                            "kept_from": rotulo,
                            "replaced_from": origem[colecao_nome][identificador],
                            "field_hint": _campos_divergentes(anterior, linha),
                        }
                    )
                # Precedência: o snapshot mais recente da lista vence.
                dados[colecao_nome][identificador] = linha
                origem[colecao_nome][identificador] = rotulo

    ultimo = entradas[-1].get("meta") or {}
    ambiente_inteiro = all((p.get("meta") or {}).get("scope", {}).get("kind") == "environment" for p in entradas)

    meta_merge = {
        "collector_version": "0.2.0",
        "collected_at": utc_now_iso(),
        "zabbix_endpoint": ultimo.get("zabbix_endpoint", ""),
        "zabbix_version": sorted(versoes)[-1] if versoes else "",
        "auth_method": ultimo.get("auth_method", ""),
        "read_only": True,
        # `filters.host_groups` continua sendo o escopo lido pelo reconcile:
        # a união dos grupos das coletas de origem.
        "filters": {
            "host_groups": grupos_cobertos,
            "limit": None,
            "only_monitored": False,
            "include_template_triggers": False,
        },
        "scope": {
            "kind": "merged",
            "label": (
                "ambiente inteiro (consolidado)"
                if ambiente_inteiro
                else f"{len(grupos_cobertos)} grupo(s) consolidados: {', '.join(grupos_cobertos)}"
            ),
            # Um merge de grupos NÃO é o ambiente inteiro. Dizer o contrário
            # seria apresentar uma coleta parcial como retrato completo.
            "complete_environment": ambiente_inteiro and not parciais,
            "host_groups": grupos_cobertos,
            "sources": len(entradas),
        },
        "merge": {
            "sources": fontes,
            "duplicates_deduplicated": {k: v for k, v in duplicados.items() if v},
            "conflicts": conflitos,
            "partial_sources": parciais,
            "zabbix_versions": sorted(versoes),
        },
    }

    consolidado = RawSnapshot(
        meta=meta_merge,
        data={nome: list(linhas.values()) for nome, linhas in dados.items()},
        api_calls=api_calls,
    )
    resumo = {
        "sources": fontes,
        "counts": {nome: len(linhas) for nome, linhas in consolidado.data.items()},
        "duplicates_deduplicated": {k: v for k, v in duplicados.items() if v},
        "conflicts": conflitos,
        "partial_sources": parciais,
        "host_groups": grupos_cobertos,
        "complete_environment": meta_merge["scope"]["complete_environment"],
    }
    return consolidado, resumo


def _campos_divergentes(anterior: dict[str, Any], atual: dict[str, Any]) -> list[str]:
    """Nomes dos campos que mudaram entre as duas versões do mesmo objeto."""
    campos = set(anterior) | set(atual)
    return sorted(
        campo
        for campo in campos
        if campo not in VOLATILE_FIELDS and anterior.get(campo) != atual.get(campo)
    )
