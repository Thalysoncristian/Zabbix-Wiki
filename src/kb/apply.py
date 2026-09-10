"""Tradução de um item do wiki para o bloco `operational` de uma ficha.

## O que entra, e de onde

Cada campo escrito aponta para a célula do wiki que o originou — a lista fica
em `imported_from.field_sources`, dentro da própria ficha. Seis meses depois,
quem abrir a ficha consegue responder "de onde veio isto?" sem adivinhar.

O que o wiki não diz, a ficha não afirma. `resolution_criteria` é o exemplo
mais visível: nenhum item do catálogo descreve como saber que o problema
acabou, então o campo fica vazio — e é justamente ele que a máquina de estados
exige para marcar a ficha como documentada. A importação, por construção, não
consegue fingir que um alerta está documentado.

## Dois campos lidos do texto em português

`requires_ticket` e `self_resolves` não existem como coluna no wiki; eles são
lidos da frase de ação ("Abrir chamado", "Aguardar a recuperação automática").
São leituras, não fatos, e por isso:

* a frase que os produziu viaja junto, em `field_sources`;
* **nenhum dos dois vira `False`.** "O wiki não menciona chamado" é silêncio,
  não uma decisão de não abrir chamado — e `requires_ticket` é campo obrigatório
  para marcar a ficha como documentada. Gravar `False` por omissão deixaria a
  ficha passar na validação com uma resposta que ninguém deu.

## Não destrutivo por padrão

`merge_operational` só preenche campo vazio. Documentação que a equipe escreveu
não é sobrescrita por uma importação; para trocar, é preciso pedir
explicitamente (`overwrite`), e o resultado diz o que foi escrito e o que foi
preservado.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.models import utc_now
from .catalog import Catalog, CatalogEntry

#: "Aguardar a recuperação automática" — o wiki dizendo que o alerta se resolve
#: sozinho. Ausente não significa que não se resolve: significa silêncio.
_AGUARDAR = re.compile(r"\baguard\w*\b", re.IGNORECASE)

#: Campos que a importação preenche. Fora desta lista nada é tocado — em
#: especial `doc_status`, `reviewed_by` e `reviewed_at`, que são da pessoa.
CAMPOS_IMPORTAVEIS: tuple[str, ...] = (
    "title", "meaning", "probable_cause", "actions", "requires_ticket",
    "self_resolves", "wait_before_ticket_minutes", "routing", "escalation", "notes",
)


def _vazio(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    if isinstance(valor, (list, tuple, dict)):
        return not valor
    return False


def operational_from_entry(entry: CatalogEntry, catalog: Catalog) -> tuple[dict[str, Any], dict[str, str]]:
    """Bloco operacional derivado do item, e a origem de cada campo escrito."""
    fontes: dict[str, str] = {}
    bloco: dict[str, Any] = {}

    def por(campo: str, valor: Any, fonte: str) -> None:
        if _vazio(valor):
            return
        bloco[campo] = valor
        fontes[campo] = fonte

    por("title", entry.name, f"coluna “Alerta” do wiki ({entry.category})")
    por("meaning", entry.description, "coluna “Descrição” da referência técnica do wiki")
    por("probable_cause", entry.probable_cause, "coluna “Causa provável” da referência técnica do wiki")
    por("actions", [entry.action] if entry.action else [],
        "coluna “Ação imediata do operador” do wiki")

    if entry.action:
        if entry.requires_ticket:
            bloco["requires_ticket"] = True
            fontes["requires_ticket"] = f"lido da ação — {entry.ticket_evidence}"
        if _AGUARDAR.search(entry.action):
            bloco["self_resolves"] = True
            fontes["self_resolves"] = (
                f"lido da ação — o wiki manda aguardar antes de agir: “{entry.action}”"
            )

    if entry.sla.wait_minutes is not None:
        bloco["wait_before_ticket_minutes"] = entry.sla.wait_minutes
        fontes["wait_before_ticket_minutes"] = f"coluna “Escalonar em” do wiki: “{entry.sla.raw}”"

    matriz = entry.escalation
    roteamento = {
        # No wiki do NOC a fila e o time são a mesma coisa — a matriz se chama
        # "Fila / Time". Preencher os dois com o mesmo valor é transportar o
        # que está escrito, não duplicar informação inventada.
        "team": entry.team,
        "ticket_queue": entry.team,
        "channel": entry.channel or (matriz.channel if matriz else ""),
    }
    if any(roteamento.values()):
        bloco["routing"] = {k: v for k, v in roteamento.items() if v}
        fontes["routing"] = (
            f"coluna “Fila / Contato” do wiki: “{entry.routing_raw}”"
            + (f"; canal da matriz de acionamento ({matriz.team})" if matriz and not entry.channel else "")
        )

    escalonamento: dict[str, Any] = {}
    if entry.sla.escalate_after_minutes is not None:
        escalonamento["after_minutes"] = entry.sla.escalate_after_minutes
    if matriz and matriz.escalation and matriz.escalation not in ("-", "—"):
        escalonamento["to"] = matriz.escalation
        escalonamento["channel"] = matriz.channel
    if escalonamento:
        bloco["escalation"] = escalonamento
        fontes["escalation"] = (
            f"prazo “{entry.sla.raw}” do wiki"
            + (f" e matriz de acionamento (fila {matriz.team})" if matriz else "")
        )

    observacoes = []
    if entry.reference:
        observacoes.append(f"Referência do wiki: {entry.reference}.")
    if entry.host:
        observacoes.append(f"Host citado no wiki: {entry.host}.")
    if matriz and matriz.schedule:
        observacoes.append(f"Horário de atendimento da fila {matriz.team}: {matriz.schedule}.")
    if entry.severity_label:
        observacoes.append(f"Severidade no wiki: {entry.severity_label}.")
    if observacoes:
        bloco["notes"] = " ".join(observacoes)
        fontes["notes"] = "colunas “Referência”, “Host” e “Sev.” do wiki + matriz de acionamento"

    return bloco, fontes


def imported_from(entry: CatalogEntry, catalog: Catalog, fontes: dict[str, str],
                  *, by: str = "") -> dict[str, Any]:
    """Procedência da importação, gravada dentro da própria ficha."""
    return {
        "source": "wiki-noc",
        "catalog_file": catalog.source_path,
        "catalog_hash": catalog.source_hash,
        "entry_id": entry.id,
        "entry_name": entry.name,
        "category": entry.category,
        "imported_at": utc_now(),
        "imported_by": by,
        "field_sources": fontes,
    }


def merge_operational(
    atual: dict[str, Any],
    novo: dict[str, Any],
    *,
    overwrite: bool = False,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Funde o bloco importado no bloco existente, sem destruir o que há.

    Devolve `(resultado, escritos, preservados)`. Sem `overwrite`, só campo
    vazio recebe valor — o texto que a equipe escreveu vence a importação
    sempre, e o operador vê na resposta o que foi preservado e por quê.
    """
    resultado = dict(atual)
    escritos: list[str] = []
    preservados: list[str] = []

    for campo in CAMPOS_IMPORTAVEIS:
        if campo not in novo:
            continue
        valor_atual = resultado.get(campo)
        if campo == "routing":
            # Roteamento é composto: preencher "channel" não pode apagar um
            # "ticket_category" que alguém escreveu à mão.
            fundido = dict(valor_atual or {})
            mudou = False
            for chave, valor in (novo[campo] or {}).items():
                if overwrite or _vazio(fundido.get(chave)):
                    if fundido.get(chave) != valor:
                        fundido[chave] = valor
                        mudou = True
                elif fundido.get(chave) != valor:
                    preservados.append(f"routing.{chave}")
            if mudou:
                resultado[campo] = fundido
                escritos.append(campo)
            continue
        if campo == "escalation":
            fundido = dict(valor_atual or {})
            mudou = False
            for chave, valor in (novo[campo] or {}).items():
                if overwrite or _vazio(fundido.get(chave)):
                    if fundido.get(chave) != valor:
                        fundido[chave] = valor
                        mudou = True
                elif fundido.get(chave) != valor:
                    preservados.append(f"escalation.{chave}")
            if mudou:
                resultado[campo] = fundido
                escritos.append(campo)
            continue

        if overwrite or _vazio(valor_atual):
            if valor_atual != novo[campo]:
                resultado[campo] = novo[campo]
                escritos.append(campo)
        elif valor_atual != novo[campo]:
            preservados.append(campo)

    return resultado, escritos, preservados


def missing_from_wiki(entry: CatalogEntry) -> list[str]:
    """O que o wiki não diz — mostrado ao operador antes da importação.

    Não é defeito do catálogo: é a diferença entre "ação imediata" e
    "procedimento completo". Enquanto estes campos estiverem vazios, a ficha
    não pode ser marcada como documentada — e isso é o comportamento correto.
    """
    faltando = ["resolution_criteria (como saber que foi resolvido)"]
    if not entry.requires_ticket:
        faltando.append("requires_ticket (a ação do wiki não menciona chamado — "
                        "ausência não é 'não abre')")
    if not entry.description:
        faltando.append("meaning (o que o alerta significa)")
    if not entry.probable_cause:
        faltando.append("probable_cause (causa provável)")
    if not entry.action:
        faltando.append("actions (o que fazer)")
    return faltando
