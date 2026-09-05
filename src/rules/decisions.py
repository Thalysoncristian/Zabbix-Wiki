"""Decisões do operador sobre os candidatos a regra.

O sistema sugere; a pessoa decide. Três decisões possíveis:

    confirmed   "isto é uma unidade operacional"     → vira alvo de documentação
    ignored     "isto não é regra nenhuma"           → some da fila de trabalho
    split       "estas coisas ficam separadas"       → volta a ser família técnica

Nenhuma delas altera o snapshot, e todas são reversíveis: a decisão é um
arquivo JSON à parte, e apagá-lo devolve tudo ao estado de candidato.

## Por que um arquivo, e não um banco

São dezenas a poucas centenas de decisões, escritas por uma pessoa por vez,
numa ferramenta local. Um arquivo JSON versionado no git dá algo que um banco
não daria de graça: o histórico de quem confirmou o quê e quando fica no
próprio repositório, junto com os procedimentos.

## Estabilidade das decisões

A decisão é gravada com o **id do candidato** — `<grupo>--<categoria>` — que é
derivado de nomes, não de IDs voláteis do Zabbix. Uma coleta nova reencontra o
mesmo id, e a decisão continua valendo. Se o grupo for renomeado no Zabbix, o
candidato vira outro e a decisão antiga fica órfã; ela é preservada no arquivo
(nunca apagada em silêncio) e simplesmente deixa de casar.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CANDIDATE = "candidate"
CONFIRMED = "confirmed"
IGNORED = "ignored"
SPLIT = "split"

DECISIONS = (CONFIRMED, IGNORED, SPLIT)

STATUS_LABELS = {
    CANDIDATE: "Sugerido",
    CONFIRMED: "Confirmado",
    IGNORED: "Ignorado",
    SPLIT: "Mantido separado",
}

DEFAULT_FILE = "docs/rule_decisions.json"


class DecisionError(ValueError):
    """Decisão inválida."""


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DecisionStore:
    """Lê e grava as decisões. Seguro para uso concorrente do servidor."""

    def __init__(self, caminho: str | Path = DEFAULT_FILE):
        self.path = Path(caminho)
        self._lock = threading.Lock()

    def all(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        decisoes = payload.get("decisions") if isinstance(payload, dict) else None
        return decisoes if isinstance(decisoes, dict) else {}

    def get(self, rule_id: str) -> dict[str, Any] | None:
        return self.all().get(rule_id)

    def set(self, rule_id: str, status: str, *, note: str = "", by: str = "") -> dict[str, Any]:
        if status not in DECISIONS and status != CANDIDATE:
            raise DecisionError(
                f"Decisão inválida: {status!r}. Válidas: {', '.join(DECISIONS)} (ou {CANDIDATE} para desfazer)."
            )
        with self._lock:
            decisoes = self.all()
            if status == CANDIDATE:
                # Desfazer é apagar a decisão: o candidato volta a ser sugestão.
                decisoes.pop(rule_id, None)
                registro = {"status": CANDIDATE}
            else:
                anterior = decisoes.get(rule_id) or {}
                registro = {
                    "status": status,
                    "note": note or anterior.get("note", ""),
                    "decided_by": by or anterior.get("decided_by", ""),
                    "decided_at": _agora(),
                    "previous_status": anterior.get("status", CANDIDATE),
                }
                decisoes[rule_id] = registro
            self._gravar(decisoes)
            return registro

    def _gravar(self, decisoes: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": (
                "Decisões do operador sobre os candidatos a regra operacional. "
                "Este arquivo NÃO altera o snapshot: apagá-lo devolve todos os "
                "agrupamentos ao estado de sugestão."
            ),
            "updated_at": _agora(),
            "decisions": dict(sorted(decisoes.items())),
        }
        # Escrita atômica: um Ctrl+C no meio não deixa o arquivo truncado.
        temporario = self.path.with_suffix(".json.tmp")
        temporario.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporario.replace(self.path)

    def counts(self) -> dict[str, int]:
        contagem = {chave: 0 for chave in (CANDIDATE, *DECISIONS)}
        for registro in self.all().values():
            estado = registro.get("status", CANDIDATE)
            contagem[estado] = contagem.get(estado, 0) + 1
        return contagem

    def mtime(self) -> float:
        """Usado pelo cache do read model para saber que algo mudou."""
        return self.path.stat().st_mtime if self.path.is_file() else 0.0
