"""Vínculos confirmados entre o catálogo do NOC e os alvos do sistema.

Mesma forma do `rule_decisions.json`: um arquivo JSON versionado no git, ao
lado dos procedimentos. O histórico de quem ligou qual item do wiki a qual
família ou regra fica no repositório, e apagar o arquivo devolve tudo ao estado
de sugestão — nenhuma ficha já escrita é perdida por isso.

Estados de um item do catálogo:

    (sem registro)  ainda não avaliado — aparece na fila com as sugestões
    linked          uma pessoa ligou o item a um ou mais alvos
    manual          o item não existe no Zabbix e virou ficha manual
    rejected        avaliado e descartado: "isto não corresponde a nada aqui"
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PENDING = "pending"
LINKED = "linked"
MANUAL = "manual"
REJECTED = "rejected"

STATUSES = (LINKED, MANUAL, REJECTED)

STATUS_LABELS = {
    PENDING: "Não avaliado",
    LINKED: "Vinculado",
    MANUAL: "Ficha manual",
    REJECTED: "Descartado",
}

KINDS = ("family", "rule")

DEFAULT_FILE = "docs/kb_links.json"


class LinkError(ValueError):
    """Vínculo inválido."""


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LinkStore:
    """Lê e grava os vínculos. Seguro para uso concorrente do servidor."""

    def __init__(self, caminho: str | Path = DEFAULT_FILE):
        self.path = Path(caminho)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ leitura
    def all(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        vinculos = payload.get("links") if isinstance(payload, dict) else None
        return vinculos if isinstance(vinculos, dict) else {}

    def get(self, entry_id: str) -> dict[str, Any]:
        return self.all().get(entry_id) or {"status": PENDING, "targets": []}

    def targets_of(self, entry_id: str) -> list[dict[str, Any]]:
        return list(self.get(entry_id).get("targets") or [])

    def entries_for_target(self, kind: str, target_id: str) -> list[str]:
        """Quais itens do wiki estão ligados a esta família/regra."""
        saida = []
        for entry_id, registro in self.all().items():
            for alvo in registro.get("targets") or []:
                if alvo.get("kind") == kind and alvo.get("id") == target_id:
                    saida.append(entry_id)
                    break
        return sorted(saida)

    def counts(self) -> dict[str, int]:
        contagem = {chave: 0 for chave in (PENDING, *STATUSES)}
        for registro in self.all().values():
            estado = registro.get("status", PENDING)
            contagem[estado] = contagem.get(estado, 0) + 1
        return contagem

    def mtime(self) -> float:
        return self.path.stat().st_mtime if self.path.is_file() else 0.0

    # ------------------------------------------------------------------ escrita
    def link(self, entry_id: str, kind: str, target_id: str, label: str = "",
             *, by: str = "", note: str = "") -> dict[str, Any]:
        """Registra um vínculo confirmado. Um item pode valer para vários alvos."""
        if kind not in KINDS:
            raise LinkError(f"Tipo de alvo inválido: {kind!r}. Válidos: {', '.join(KINDS)}.")
        if not target_id:
            raise LinkError("Vínculo sem alvo.")
        with self._lock:
            vinculos = self.all()
            registro = vinculos.get(entry_id) or {"targets": []}
            alvos = [a for a in registro.get("targets") or []
                     if not (a.get("kind") == kind and a.get("id") == target_id)]
            alvos.append({"kind": kind, "id": target_id, "label": label,
                          "linked_by": by, "linked_at": _agora()})
            registro.update({"status": LINKED, "targets": alvos,
                             "note": note or registro.get("note", ""),
                             "decided_by": by or registro.get("decided_by", ""),
                             "decided_at": _agora()})
            vinculos[entry_id] = registro
            self._gravar(vinculos)
            return registro

    def unlink(self, entry_id: str, kind: str, target_id: str) -> dict[str, Any]:
        """Desfaz um vínculo. A ficha já escrita continua onde está.

        Remover o vínculo não apaga documentação: se alguém escreveu por cima do
        que veio do wiki, esse texto é conhecimento da equipe agora. O que
        desaparece é a ligação, não o conteúdo.
        """
        with self._lock:
            vinculos = self.all()
            registro = vinculos.get(entry_id)
            if registro is None:
                return {"status": PENDING, "targets": []}
            alvos = [a for a in registro.get("targets") or []
                     if not (a.get("kind") == kind and a.get("id") == target_id)]
            if alvos:
                registro["targets"] = alvos
                registro["decided_at"] = _agora()
                vinculos[entry_id] = registro
            else:
                vinculos.pop(entry_id, None)
                registro = {"status": PENDING, "targets": []}
            self._gravar(vinculos)
            return registro

    def set_status(self, entry_id: str, status: str, *, by: str = "", note: str = "",
                   doc_key: str = "") -> dict[str, Any]:
        """Marca o item como descartado, como ficha manual, ou volta ao início."""
        if status not in STATUSES and status != PENDING:
            raise LinkError(
                f"Estado inválido: {status!r}. Válidos: {', '.join(STATUSES)} (ou {PENDING} para desfazer)."
            )
        with self._lock:
            vinculos = self.all()
            if status == PENDING:
                vinculos.pop(entry_id, None)
                registro = {"status": PENDING, "targets": []}
            else:
                anterior = vinculos.get(entry_id) or {}
                registro = {
                    "status": status,
                    "targets": anterior.get("targets") or [],
                    "note": note or anterior.get("note", ""),
                    "decided_by": by or anterior.get("decided_by", ""),
                    "decided_at": _agora(),
                    "previous_status": anterior.get("status", PENDING),
                }
                if doc_key or anterior.get("doc_key"):
                    registro["doc_key"] = doc_key or anterior["doc_key"]
                vinculos[entry_id] = registro
            self._gravar(vinculos)
            return registro

    def _gravar(self, vinculos: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": (
                "Vínculos entre o catálogo do NOC (docs/knowledge/catalogo-noc.md) e as "
                "famílias/regras observadas na coleta. Este arquivo NÃO altera o snapshot "
                "nem apaga fichas: removê-lo devolve todos os itens ao estado de sugestão."
            ),
            "updated_at": _agora(),
            "links": dict(sorted(vinculos.items())),
        }
        temporario = self.path.with_suffix(".json.tmp")
        temporario.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporario.replace(self.path)
