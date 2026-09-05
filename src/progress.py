"""Progresso da coleta (item 6 da Fase 2).

Uma coleta de dezenas de milhares de objetos não pode parecer travada — mas
também não pode enterrar o operador em texto. Numa coleta real de 18.903
triggers, uma linha por página são **203 linhas** que ninguém lê.

Por isso há dois modos:

* **compacto** (padrão): uma linha por FASE, escrita quando a fase termina.
  Enquanto a fase roda, a mesma linha é reescrita no lugar (só em terminal
  interativo). Dez linhas no total, em vez de duzentas.
* **detalhado** (`-v`): uma linha por página, como antes — para depurar uma
  coleta que está falhando.

Avisos (lote reduzido, objeto não coletado) aparecem nos dois modos, sempre.
Silenciar um problema para caber na tela seria o pior dos dois mundos.

Regra que vale a pena repetir: **o total só é informado quando é conhecido de
verdade**. Como a paginação descobre a lista de IDs antes de hidratar (a API do
Zabbix não tem `offset`), o total normalmente É conhecido e a porcentagem é
real. Quando não for, a linha não mostra porcentagem — nada é estimado.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable

#: Assinatura do callback de progresso usado pelo coletor.
ProgressHandler = Callable[[dict[str, Any]], None]

#: Mensagens de `step` que só repetem o que a linha da fase já diz
#: ("18903 triggers coletados", "78 hosts resolvidos"). No modo compacto elas
#: somem; qualquer coisa que comece com texto — inclusive "Aviso:" — fica.
_RESUMO_DE_CONTAGEM = re.compile(r"^\d[\d.,]*\s")


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
    """Imprime o progresso da coleta no terminal."""

    def __init__(
        self,
        write: Callable[[str], None] = print,
        *,
        clock: Callable[[], float] = time.monotonic,
        verbose: bool = False,
        interactive: bool | None = None,
    ):
        self._write = write
        self._clock = clock
        self._start = clock()
        self.verbose = verbose
        #: Só reescreve a linha no lugar (`\\r`) em terminal de verdade —
        #: num arquivo de log ou num pipe isso viraria lixo binário.
        self._interactive = sys.stdout.isatty() if interactive is None else interactive
        self.events: list[dict[str, Any]] = []

        # Estado da fase em andamento, no modo compacto.
        self._fase: str = ""
        self._fase_inicio: float = clock()
        self._fase_paginas: int = 0
        self._fase_objetos: int = 0
        self._fase_total: int = 0
        self._linha_viva = False
        self._grupos: int = 0

    @property
    def elapsed(self) -> float:
        return self._clock() - self._start

    # ------------------------------------------------------------------ saída
    def _linha(self, texto: str) -> None:
        """Escreve uma linha definitiva, apagando a linha viva se houver."""
        if self._linha_viva:
            self._write("\r\033[K" if self._interactive else "")
            self._linha_viva = False
        self._write(f"  · {texto}")

    def _viva(self, texto: str) -> None:
        """Reescreve a linha de andamento no lugar (só em terminal)."""
        if not self._interactive:
            return
        sys.stdout.write(f"\r\033[K  · {texto}")
        sys.stdout.flush()
        self._linha_viva = True

    def finish(self) -> None:
        """Fecha a última fase — chame ao terminar a coleta."""
        self._fechar_fase()

    # ------------------------------------------------------------- despachante
    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

        if self.verbose:
            linha = self.format(event)
            if linha:
                self._write(f"  · {linha}")
            return

        self._compacto(event)

    def _compacto(self, event: dict[str, Any]) -> None:
        tipo = event.get("event")

        # Avisos nunca são resumidos: são o motivo de existir o progresso.
        if tipo in ("batch_reduced", "page_failed"):
            self._linha(self.format(event))
            return

        if tipo == "page":
            self._acumular(event)
            return

        if tipo == "group":
            self._grupos += 1
            self._viva(f"escopo: {self._grupos} grupo(s) varrido(s)...")
            return

        if tipo == "phase":
            self._viva(f"{event.get('name', '')}: {event.get('detail', '')}")
            return

        self._fechar_fase()

        if tipo == "scope":
            grupos = event.get("host_groups") or []
            alvo = ", ".join(grupos) if grupos else f"ambiente inteiro ({self._grupos} grupos)"
            self._linha(f"escopo: {alvo} — {event.get('hosts', 0)} hosts")
            return

        if tipo == "step":
            mensagem = str(event.get("message", ""))
            if mensagem and not _RESUMO_DE_CONTAGEM.match(mensagem):
                self._linha(mensagem)

    def _acumular(self, event: dict[str, Any]) -> None:
        rotulo = str(event.get("label") or event.get("method") or "")
        if rotulo != self._fase:
            self._fechar_fase()
            self._fase = rotulo
            self._fase_inicio = self._clock()
            self._fase_paginas = 0
            self._fase_objetos = 0

        self._fase_paginas += 1
        self._fase_objetos = event.get("collected", 0)
        self._fase_total = event.get("total") or 0

        restantes = event.get("remaining_pages", 0)
        if self._fase_total:
            pct = self._fase_objetos / self._fase_total * 100
            self._viva(f"{self._fase}: {self._fase_objetos}/{self._fase_total} ({pct:.0f}%), "
                       f"{restantes} página(s) restante(s)")
        else:
            self._viva(f"{self._fase}: {self._fase_objetos} objetos")

    def _fechar_fase(self) -> None:
        if not self._fase:
            return
        duracao = format_duration(self._clock() - self._fase_inicio)
        objetos = "objeto" if self._fase_objetos == 1 else "objetos"
        paginas = "página" if self._fase_paginas == 1 else "páginas"
        self._linha(
            f"{self._fase}: {self._fase_objetos} {objetos} em "
            f"{self._fase_paginas} {paginas} ({duracao})"
        )
        self._fase = ""

    # -------------------------------------------------- formato detalhado (-v)
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
                f"⚠ {event.get('label', '')}: lote {event.get('from_size')} recusado pelo "
                f"servidor — dividindo para {event.get('to_size')} e tentando de novo"
            )

        if tipo == "page_failed":
            ids = event.get("ids") or []
            return (
                f"✗ {event.get('label', '')}: {len(ids)} objeto(s) não coletado(s) "
                f"após todas as tentativas ({event.get('error', '')})"
            )

        if tipo == "phase":
            return f"[{decorrido}] {event.get('name', '')}: {event.get('detail', '')}"

        return ""
