"""Escrita dos snapshots em disco.

Cada execução cria um diretório novo e imutável:

    output/snapshots/YYYYMMDD_HHMMSS/
    ├── raw/
    │   └── zabbix_raw.json      # o que veio do Zabbix (auditoria)
    ├── normalized/
    │   ├── alerts.json          # alertas autocontidos
    │   ├── alert_keys.json      # agrupamento por alert_key
    │   └── collisions.json      # colisões de alert_key detectadas
    └── report.json              # relatório da coleta

Snapshots antigos nunca são sobrescritos.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .collect import RawSnapshot
from .normalize import NormalizedResult


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return path


def new_snapshot_dir(base_dir: str | Path, when: datetime | None = None) -> Path:
    """Cria `output/snapshots/<timestamp>` sem colidir com snapshots existentes."""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    root = Path(base_dir) / "snapshots"
    candidate = root / stamp
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{stamp}_{suffix}"
    candidate.mkdir(parents=True)
    return candidate


def update_latest_pointer(snapshot_dir: Path) -> None:
    """Aponta `output/snapshots/latest` para o snapshot mais recente (best effort)."""
    link = snapshot_dir.parent / "latest"
    try:
        if link.is_symlink() or link.exists():
            if link.is_symlink():
                link.unlink()
            else:
                return
        os.symlink(snapshot_dir.name, link, target_is_directory=True)
    except OSError:
        # Sistemas sem permissão de symlink (ex.: Windows sem dev mode): ignorar.
        pass


def write_snapshot(
    base_dir: str | Path,
    raw: RawSnapshot,
    normalized: NormalizedResult,
    *,
    when: datetime | None = None,
) -> dict[str, Path]:
    """Grava snapshot bruto + normalizado e devolve os caminhos criados."""
    snapshot_dir = new_snapshot_dir(base_dir, when)

    paths = {
        "snapshot_dir": snapshot_dir,
        "raw": write_json(snapshot_dir / "raw" / "zabbix_raw.json", raw.to_dict()),
        "alerts": write_json(
            snapshot_dir / "normalized" / "alerts.json",
            {"meta": raw.meta, "count": len(normalized.alerts), "alerts": normalized.alerts},
        ),
        "alert_keys": write_json(
            snapshot_dir / "normalized" / "alert_keys.json",
            {
                "meta": raw.meta,
                "unique_alert_keys": len(normalized.key_index),
                "keys": [normalized.key_index[k] for k in sorted(normalized.key_index)],
            },
        ),
        "collisions": write_json(
            snapshot_dir / "normalized" / "collisions.json",
            {"meta": raw.meta, "count": len(normalized.collisions), "collisions": normalized.collisions},
        ),
    }
    update_latest_pointer(snapshot_dir)
    return paths
