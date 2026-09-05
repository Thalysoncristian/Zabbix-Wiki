"""Candidatos a regra operacional: agrupamentos SUGERIDOS, nunca decididos.

## O que é um candidato

Uma unidade que provavelmente merece **um procedimento só**. O escopo é
`(host group, categoria operacional)` — porque é assim que o operador escolhe
o trabalho: "hoje vou documentar disco no grupo Vibe Tecnologia", não "hoje vou
documentar o alerta 23408".

Uma regra reúne várias famílias técnicas. As famílias continuam existindo e
aparecem dentro da regra como evidência de origem — nada é apagado.

## Confiança e motivos

Todo candidato carrega uma confiança (alta/média/baixa) e a lista de motivos
que a produziram. Isso não é enfeite: um agrupamento que ninguém consegue
explicar é um agrupamento que ninguém deveria confirmar.

Sinais usados, todos determinísticos e locais:

    chave de item        estrutural, o mais forte  (`vfs.fs.*` = filesystem)
    descrição            confirma ou desempata
    dependência          o Zabbix já ligou dois triggers: forte
    protótipo de LLD     mesma regra aplicada a N entidades
    instâncias           quantas entidades a regra cobre

A palavra usada na interface é sempre "possível agrupamento". Ele só vira regra
quando uma pessoa confirma — e a decisão dela fica registrada em disco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..keys import short_hash, slugify
from .instances import instance_of
from .taxonomy import CATEGORY_BY_ID, UNCATEGORIZED, Classification, classify

#: Níveis de confiança expostos na interface.
HIGH, MEDIUM, LOW = "high", "medium", "low"
CONFIDENCE_LABELS = {HIGH: "Alta", MEDIUM: "Média", LOW: "Baixa"}

#: Abaixo disto o agrupamento é pequeno demais para valer uma regra própria por
#: si só — ainda aparece, mas com confiança rebaixada.
MIN_ALERTS_FOR_HIGH = 3


@dataclass
class RuleCandidate:
    """Um agrupamento operacional sugerido, com as evidências que o sustentam."""

    id: str
    group_id: str
    group_name: str
    category_id: str
    label: str
    description: str = ""
    alert_ids: list[str] = field(default_factory=list)
    family_ids: set[str] = field(default_factory=set)
    hosts: dict[str, str] = field(default_factory=dict)
    instances: dict[str, list[str]] = field(default_factory=dict)
    severities: dict[str, int] = field(default_factory=dict)
    item_prefixes: dict[str, int] = field(default_factory=dict)
    dependencies_internal: int = 0
    dependencies_total: int = 0
    discovered: int = 0
    both_signals: int = 0
    keyword_only: int = 0
    evidence_samples: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- confiança
    def confidence(self) -> tuple[str, list[str]]:
        """Nível de confiança e os motivos, em texto que o operador lê."""
        motivos: list[str] = []
        pontos = 0
        total = len(self.alert_ids) or 1

        proporcao_forte = self.both_signals / total
        if proporcao_forte >= 0.6:
            pontos += 2
            motivos.append(
                f"{self.both_signals} de {total} alertas confirmados por dois sinais "
                "independentes (chave de item e descrição)"
            )
        elif self.both_signals:
            pontos += 1
            motivos.append(f"{self.both_signals} de {total} alertas confirmados por dois sinais")

        dominante = max(self.item_prefixes.items(), key=lambda kv: kv[1], default=None)
        if dominante and dominante[1] / total >= 0.6:
            pontos += 2
            motivos.append(f"{dominante[1]} de {total} alertas leem itens `{dominante[0]}*` — "
                           "monitoram o mesmo tipo de objeto")

        if self.dependencies_internal:
            pontos += 2
            motivos.append(f"{self.dependencies_internal} dependência(s) entre triggers deste "
                           "agrupamento — o próprio Zabbix já os relaciona")

        if len(self.instances) > 1:
            pontos += 1
            motivos.append(f"{len(self.instances)} instâncias da mesma regra "
                           f"({', '.join(sorted(self.instances)[:4])}…)"
                           if len(self.instances) > 4 else
                           f"{len(self.instances)} instâncias da mesma regra "
                           f"({', '.join(sorted(self.instances))})")

        if len(self.hosts) > 1:
            pontos += 1
            motivos.append(f"a mesma situação aparece em {len(self.hosts)} hosts do grupo")

        if self.keyword_only and self.keyword_only / total > 0.5:
            pontos -= 1
            motivos.append(f"⚠ {self.keyword_only} de {total} alertas foram classificados só pela "
                           "descrição, sem chave de item conhecida")

        if len(self.alert_ids) < MIN_ALERTS_FOR_HIGH:
            pontos -= 1
            motivos.append(f"⚠ agrupamento pequeno ({len(self.alert_ids)} alerta(s)) — "
                           "pode ser um caso isolado, não uma regra")

        if len(self.family_ids) > 1:
            motivos.append(f"reúne {len(self.family_ids)} famílias técnicas que hoje seriam "
                           "documentadas separadamente")

        nivel = HIGH if pontos >= 4 else MEDIUM if pontos >= 2 else LOW
        return nivel, motivos

    def to_dict(self, decision: dict[str, Any] | None = None,
                procedure: dict[str, Any] | None = None) -> dict[str, Any]:
        nivel, motivos = self.confidence()
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "category_id": self.category_id,
            "group": {"id": self.group_id, "name": self.group_name},
            "alerts": len(self.alert_ids),
            "families": len(self.family_ids),
            "hosts": len(self.hosts),
            "host_names": sorted(self.hosts.values())[:12],
            "instances": len(self.instances),
            "instance_names": sorted(self.instances)[:12],
            "dependencies": self.dependencies_internal,
            "discovered": self.discovered,
            "severities": self.severities,
            # A palavra é sempre "possível": só a confirmação humana transforma
            # o candidato numa regra.
            "confidence": nivel,
            "confidence_label": CONFIDENCE_LABELS[nivel],
            "reasons": motivos,
            "evidence_samples": self.evidence_samples[:4],
            "status": (decision or {}).get("status", "candidate"),
            "decided_by": (decision or {}).get("decided_by", ""),
            "decided_at": (decision or {}).get("decided_at"),
            "note": (decision or {}).get("note", ""),
            "procedure": procedure,
        }


def _slug_grupo(nome: str) -> str:
    return slugify(nome, fallback=short_hash(nome))


def build_candidates(
    alerts: list[dict[str, Any]],
    family_of: dict[str, str] | None = None,
) -> dict[str, RuleCandidate]:
    """Gera os candidatos a regra a partir dos alertas de um escopo.

    Um alerta cujo host está em dois grupos entra no candidato de **cada**
    grupo: o operador que abre "Vibe Tecnologia" precisa ver tudo daquele
    grupo. A soma dos grupos, portanto, não é o total do ambiente — a interface
    diz isso.
    """
    family_of = family_of or {}
    candidatos: dict[str, RuleCandidate] = {}
    #: triggerid -> ids de candidatos, para achar dependências internas depois.
    onde_esta: dict[str, list[str]] = {}

    for alerta in alerts:
        zbx = alerta.get("zabbix") or {}
        triggerid = str(zbx.get("triggerid") or "")
        if not triggerid:
            continue

        classificacao = classify(alerta)
        if classificacao.category_id == UNCATEGORIZED:
            # Sem categoria não entra em regra nenhuma: agrupar o que não se
            # entende é pior do que deixar separado.
            continue

        categoria = CATEGORY_BY_ID[classificacao.category_id]
        grupos = zbx.get("host_groups") or ["(sem grupo)"]
        instancia = instance_of(alerta)

        for nome_grupo in grupos:
            identificador = f"{_slug_grupo(nome_grupo)}--{categoria.id}"
            candidato = candidatos.get(identificador)
            if candidato is None:
                candidato = RuleCandidate(
                    id=identificador, group_id=_slug_grupo(nome_grupo), group_name=nome_grupo,
                    category_id=categoria.id, label=categoria.label, description=categoria.description,
                )
                candidatos[identificador] = candidato

            _acumular(candidato, alerta, zbx, triggerid, classificacao, instancia, family_of)
            onde_esta.setdefault(triggerid, []).append(identificador)

    _contar_dependencias(alerts, candidatos, onde_esta)
    return candidatos


def _acumular(candidato: RuleCandidate, alerta: dict[str, Any], zbx: dict[str, Any],
              triggerid: str, classificacao: Classification,
              instancia: dict[str, Any] | None, family_of: dict[str, str]) -> None:
    candidato.alert_ids.append(triggerid)
    if triggerid in family_of:
        candidato.family_ids.add(family_of[triggerid])

    host = zbx.get("host") or {}
    hostid = str(host.get("hostid") or "")
    if hostid:
        candidato.hosts[hostid] = host.get("name") or host.get("host") or ""

    if instancia:
        candidato.instances.setdefault(instancia["name"], []).append(triggerid)

    severidade = (zbx.get("priority") or {}).get("name", "Not classified")
    candidato.severities[severidade] = candidato.severities.get(severidade, 0) + 1

    # Um alerta pode ler vários itens do mesmo prefixo; conta-se o ALERTA, não
    # os itens — senão o motivo sai como "41 de 23 alertas", que não faz sentido.
    prefixos_do_alerta = set()
    for item in zbx.get("items") or []:
        chave = str(item.get("key_") or "").split("[")[0]
        prefixo = chave.rsplit(".", 1)[0] if "." in chave else chave
        if prefixo:
            prefixos_do_alerta.add(prefixo)
    for prefixo in prefixos_do_alerta:
        candidato.item_prefixes[prefixo] = candidato.item_prefixes.get(prefixo, 0) + 1

    candidato.dependencies_total += len(zbx.get("dependencies") or [])
    if zbx.get("discovered"):
        candidato.discovered += 1
    if classificacao.confident:
        candidato.both_signals += 1
    elif classificacao.by_keyword and not classificacao.by_item:
        candidato.keyword_only += 1

    if classificacao.evidence and len(candidato.evidence_samples) < 6:
        amostra = f"{zbx.get('description_raw', '')[:60]} — {classificacao.evidence[0]}"
        if amostra not in candidato.evidence_samples:
            candidato.evidence_samples.append(amostra)


def _contar_dependencias(alerts: list[dict[str, Any]], candidatos: dict[str, RuleCandidate],
                         onde_esta: dict[str, list[str]]) -> None:
    """Dependências cujos dois lados caem no mesmo candidato.

    É o sinal mais forte que existe aqui: o próprio Zabbix já declarou que os
    dois triggers estão relacionados. Uma dependência que sai do agrupamento
    não conta — ela liga duas regras diferentes, o que é outra informação.
    """
    for alerta in alerts:
        zbx = alerta.get("zabbix") or {}
        origem = str(zbx.get("triggerid") or "")
        for dependencia in zbx.get("dependencies") or []:
            destino = str(dependencia.get("triggerid") or "")
            comuns = set(onde_esta.get(origem, [])) & set(onde_esta.get(destino, []))
            for identificador in comuns:
                candidatos[identificador].dependencies_internal += 1
