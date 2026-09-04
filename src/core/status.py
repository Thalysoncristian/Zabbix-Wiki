"""Máquina de estados de `doc_status`.

    undocumented ──> pending_review ──> documented ──> reviewed
                                            │             │
                                            └──────┬──────┘
                                                   ↓
                                            review_needed
                                        (o Zabbix mudou o alerta)

Regras:

* A documentação antiga **nunca** é apagada automaticamente. `review_needed`
  sinaliza que o fato técnico mudou; o conteúdo humano permanece intacto.
* `not_applicable` é um destino válido de qualquer estado (alerta que o NOC
  decidiu não documentar — ruído, trigger desabilitado, teste).
* Marcar como `documented` exige campos mínimos preenchidos: é o que impede
  salvar um rascunho e fingir que o alerta está documentado.
"""

from __future__ import annotations

from typing import Any

UNDOCUMENTED = "undocumented"
PENDING_REVIEW = "pending_review"
DOCUMENTED = "documented"
REVIEWED = "reviewed"
REVIEW_NEEDED = "review_needed"
NOT_APPLICABLE = "not_applicable"

ALL_STATUSES: tuple[str, ...] = (
    UNDOCUMENTED,
    PENDING_REVIEW,
    DOCUMENTED,
    REVIEWED,
    REVIEW_NEEDED,
    NOT_APPLICABLE,
)

#: Estados que representam documentação já considerada válida.
DOCUMENTED_STATUSES: frozenset[str] = frozenset({DOCUMENTED, REVIEWED})

#: Transições permitidas. `not_applicable` é alcançável de qualquer estado.
TRANSITIONS: dict[str, frozenset[str]] = {
    UNDOCUMENTED: frozenset({PENDING_REVIEW, DOCUMENTED, NOT_APPLICABLE}),
    PENDING_REVIEW: frozenset({UNDOCUMENTED, DOCUMENTED, NOT_APPLICABLE}),
    DOCUMENTED: frozenset({PENDING_REVIEW, REVIEWED, REVIEW_NEEDED, NOT_APPLICABLE}),
    REVIEWED: frozenset({PENDING_REVIEW, DOCUMENTED, REVIEW_NEEDED, NOT_APPLICABLE}),
    REVIEW_NEEDED: frozenset({PENDING_REVIEW, DOCUMENTED, REVIEWED, NOT_APPLICABLE}),
    NOT_APPLICABLE: frozenset({UNDOCUMENTED, PENDING_REVIEW, DOCUMENTED}),
}

#: Campos mínimos para uma ficha poder ser marcada como `documented`.
REQUIRED_FOR_DOCUMENTED: tuple[tuple[str, str], ...] = (
    ("meaning", "o que o alerta significa"),
    ("requires_ticket", "se precisa abrir chamado"),
    ("resolution_criteria", "como saber que foi resolvido"),
)

#: Quando `requires_ticket` é verdadeiro, o roteamento também é obrigatório:
#: de nada adianta saber que abre chamado sem saber para qual equipe/fila.
REQUIRED_ROUTING_FOR_TICKET: tuple[tuple[str, str], ...] = (
    ("team", "equipe dona do problema"),
    ("ticket_queue", "fila do chamado"),
)


class StatusError(ValueError):
    """Transição de estado inválida ou campos mínimos ausentes."""


def can_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    if target not in ALL_STATUSES:
        raise StatusError(f"Status desconhecido: {target!r}. Válidos: {', '.join(ALL_STATUSES)}")
    if not can_transition(current, target):
        permitidos = ", ".join(sorted(TRANSITIONS.get(current, frozenset()))) or "nenhum"
        raise StatusError(f"Transição inválida: {current} -> {target}. A partir de {current}: {permitidos}")


def missing_fields_for_documented(operational: dict[str, Any]) -> list[str]:
    """Campos que faltam para a ficha poder ser marcada como documentada."""
    faltando: list[str] = []

    for campo, descricao in REQUIRED_FOR_DOCUMENTED:
        valor = operational.get(campo)
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            faltando.append(f"{campo} ({descricao})")

    if operational.get("requires_ticket"):
        routing = operational.get("routing") or {}
        for campo, descricao in REQUIRED_ROUTING_FOR_TICKET:
            valor = routing.get(campo)
            if not valor or (isinstance(valor, str) and not valor.strip()):
                faltando.append(f"routing.{campo} ({descricao})")

    return faltando


def assert_can_document(operational: dict[str, Any]) -> None:
    faltando = missing_fields_for_documented(operational)
    if faltando:
        raise StatusError("Campos mínimos ausentes para marcar como documentado: " + "; ".join(faltando))
