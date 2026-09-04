"""Persistência das fichas em `docs/alerts/*.json`.

Os JSONs são a fonte de verdade. Nada de banco nesta versão — mas todo o
acesso passa por aqui, para que trocar o backend depois (SQLite, Postgres)
não obrigue o resto do sistema a saber que existe um filesystem.

    JSON  ->  Repository  ->  AlertIndex  ->  Web / CLI
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterator

from .models import AlertDoc, alert_key_to_filename

logger = logging.getLogger(__name__)

DEFAULT_DOCS_DIR = Path("docs") / "alerts"


class ConcurrentModificationError(RuntimeError):
    """A ficha foi alterada por outra pessoa desde que foi carregada."""


class AlertRepository:
    """Lê e grava fichas operacionais em disco."""

    def __init__(self, docs_dir: str | Path = DEFAULT_DOCS_DIR):
        self.docs_dir = Path(docs_dir)

    # ---------------------------------------------------------------- leitura
    def path_for(self, alert_key: str) -> Path:
        return self.docs_dir / alert_key_to_filename(alert_key)

    def exists(self, alert_key: str) -> bool:
        return self.path_for(alert_key).is_file()

    def get(self, alert_key: str) -> AlertDoc | None:
        caminho = self.path_for(alert_key)
        if not caminho.is_file():
            return None
        return self._load(caminho)

    def all(self) -> Iterator[AlertDoc]:
        if not self.docs_dir.is_dir():
            return
        for caminho in sorted(self.docs_dir.glob("*.json")):
            doc = self._load(caminho)
            if doc is not None:
                yield doc

    def _load(self, caminho: Path) -> AlertDoc | None:
        try:
            payload = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ficha ilegível ignorada (%s): %s", caminho, exc)
            return None
        if not isinstance(payload, dict) or not payload.get("alert_key"):
            logger.warning("Ficha sem alert_key ignorada: %s", caminho)
            return None
        return AlertDoc.from_dict(payload)

    # ------------------------------------------------------------------ escrita
    def save(self, doc: AlertDoc, *, expected_revision: int | None = None) -> Path:
        """Grava a ficha.

        `expected_revision` implementa a proteção contra escrita concorrente
        exigida para o MVP: se alguém salvou a ficha depois que esta cópia foi
        carregada, a gravação é recusada em vez de sobrescrever a alteração da
        outra pessoa em silêncio. Passe a `revision` que veio no `get()`.
        """
        caminho = self.path_for(doc.alert_key)

        if expected_revision is not None:
            atual = self.get(doc.alert_key)
            if atual is not None and atual.revision != expected_revision:
                raise ConcurrentModificationError(
                    f"Esta ficha foi alterada por outra pessoa em {atual.last_modified_at} "
                    f"(revisão {atual.revision}; você carregou a {expected_revision}). "
                    "Recarregue a ficha antes de salvar novamente."
                )

        caminho.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(doc.to_dict(), indent=2, ensure_ascii=False) + "\n"

        # Escrita atômica: um Ctrl+C no meio não deixa a ficha truncada.
        temporario = caminho.with_suffix(".json.tmp")
        temporario.write_text(payload, encoding="utf-8")
        temporario.replace(caminho)
        return caminho

    def count(self) -> int:
        return sum(1 for _ in self.all())
