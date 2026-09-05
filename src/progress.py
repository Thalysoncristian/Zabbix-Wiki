"""Progresso da coleta (item 6 da Fase 2).

Uma coleta de dezenas de milhares de objetos não pode parecer travada. O
coletor emite eventos (dicionários) e quem chama decide como mostrá-los — a
CLI imprime no terminal, os testes apenas coletam a lista.

Regra que vale a pena repetir: **o total só é informado quando é conhecido de
verdade**. Como a paginação desta integração descobre a lista de IDs antes de
hidratar (a API do Zabbix não tem `offset`), o total normalmente É conhecido e
a porcentagem é real. Quando não for, a linha simplesmente não mostra
porcentagem — nada é estimado ou inventado.
"""

from __future__ import annotations

import time
from typing import Any, Callable

#: Assinatura do callback de progresso usado pelo coletor.
ProgressHandler = Callable[[dict[str, Any]], None]


def noop(_event: dict[str, Any]) -> None:
    """Handler nulo — usado quando ninguém está olhando."""


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutos, resto = divmod(int(seconds), 60)
    if minutos < 60:
        return f"{minutos}m{resto:02d}s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas}h{minutos:02d}m"


class ConsoleProgress:
    """Imprime os eventos de coleta no terminal, em uma linha por evento."""

    def __init__(self, write: Callable[[str], None] = print, *, clock: Callable[[], float] = time.monotonic):
        self._write = write
        self._clock = clock
        self._start = clock()
        self.events: list[dict[str, Any]] = []

    @property
    def elapsed(self) -> float:
        return self._clock() - self._start

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        linha = self.format(event)
        if linha:
            self._write(f"  · {linha}")

    def format(self, event: dict[str, Any]) -> str:
        tipo = event.get("event")
        decorrido = format_duration(self.elapsed)

        if tipo == "step":
            return f"[{decorrido}] {event.get('message', '')}"

        if tipo == "scope":
            grupos = event.get("host_groups") or []
            alvo = ", ".join(grupos) if grupos else "ambiente inteiro"
            return f"[{decorrido}] Escopo: {alvo} ({event.get('hosts', 0)} hosts)"

        if tipo == "group":
            return (
                f"[{decorrido}] Grupo {event.get('index', '?')}/{event.get('groups', '?')}: "
                f"{event.get('name', '')} — {event.get('hosts', 0)} hosts"
            )

        if tipo == "page":
            total = event.get("total") or 0
            coletados = event.get("collected", 0)
            pedaco = (
                f"{coletados}/{total} ({coletados / total * 100:.0f}%)"
                if total
                else f"{coletados} objetos"  # total desconhecido: sem porcentagem inventada
            )
            return (
                f"[{decorrido}] {event.get('label', '')}: página {event.get('page', '?')} "
                f"(+{event.get('rows', 0)} de {event.get('page_size', 0)} pedidos) — {pedaco}"
            )

        if tipo == "batch_reduced":
            return (
                f"[{decorrido}] ⚠ {event.get('label', '')}: lote {event.get('from_size')} recusado pelo "
                f"servidor — dividindo para {event.get('to_size')} e tentando de novo"
            )

        if tipo == "page_failed":
            ids = event.get("ids") or []
            return (
                f"[{decorrido}] ✗ {event.get('label', '')}: {len(ids)} objeto(s) não coletado(s) "
                f"após todas as tentativas ({event.get('error', '')})"
            )

        if tipo == "phase":
            return f"[{decorrido}] {event.get('name', '')}: {event.get('detail', '')}"

        return ""
