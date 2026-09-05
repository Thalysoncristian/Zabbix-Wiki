"""Escrita dos snapshots em disco.

Cada execução cria um diretório novo e imutável, nomeado pelo instante e pelo
escopo da coleta:

    output/snapshots/YYYYMMDD_HHMMSS__vibe-tecnologia/
    ├── raw/
    │   └── zabbix_raw.json      # o que veio do Zabbix (auditoria)
    ├── normalized/
    │   ├── alerts.json          # alertas autocontidos
    │   ├── alert_keys.json      # agrupamento por alert_key
    │   └── collisions.json      # colisões de alert_key detectadas
    └── report.json              # relatório da coleta

Snapshots antigos **nunca** são sobrescritos: coletar o grupo B amanhã não
apaga a coleta do grupo A de hoje. É isso que permite construir a base aos
poucos e consolidar depois com `python main.py merge`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .collect import RawSnapshot
from .keys import slugify
from .normalize import NormalizedResult

#: Sufixo máximo de escopo no nome do diretório — nome de pasta não pode
#: crescer sem limite quando alguém coleta uma dúzia de grupos de uma vez.
MAX_SCOPE_SUFFIX = 48


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return path


def scope_suffix(meta: dict[str, Any] | None) -> str:
    """Sufixo legível do escopo, para o nome do diretório do snapshot.

    O ambiente inteiro não recebe sufixo (é o caso base). Uma coleta de grupos
    recebe os nomes em slug, para que `ls output/snapshots` já diga o que cada
    coleta cobriu sem abrir um único JSON.
    """
    scope = (meta or {}).get("scope") or {}
    kind = scope.get("kind")
    if kind == "sample":
        return "amostra"
    if kind == "host_groups":
        grupos = [slugify(nome) for nome in scope.get("host_groups") or [] if nome]
        junto = "-".join(g for g in grupos if g)
        if len(junto) > MAX_SCOPE_SUFFIX:
            junto = f"{len(grupos)}-grupos"
        return junto
    if kind == "merged":
        return "consolidado"
    return ""


def new_snapshot_dir(base_dir: str | Path, when: datetime | None = None, *, suffix: str = "") -> Path:
    """Cria `output/snapshots/<timestamp>[__escopo]` sem colidir com os existentes."""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    if suffix:
        stamp = f"{stamp}__{suffix}"
    root = Path(base_dir) / "snapshots"
    candidate = root / stamp
    sequencia = 1
    while candidate.exists():
        sequencia += 1
        candidate = root / f"{stamp}_{sequencia}"
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
    snapshot_dir = new_snapshot_dir(base_dir, when, suffix=scope_suffix(raw.meta))

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


def load_raw_snapshot(path: str | Path) -> dict[str, Any]:
    """Lê o `raw/zabbix_raw.json` de um snapshot (aceita o diretório ou o arquivo)."""
    caminho = Path(path)
    if caminho.is_dir():
        caminho = caminho / "raw" / "zabbix_raw.json"
    if not caminho.is_file():
        raise FileNotFoundError(f"Snapshot bruto não encontrado: {caminho}")
    payload = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError(f"{caminho} não parece um snapshot bruto (falta a chave 'data').")
    return payload


def list_snapshots(base_dir: str | Path) -> list[Path]:
    """Diretórios de snapshot existentes, do mais antigo para o mais recente."""
    raiz = Path(base_dir) / "snapshots"
    if not raiz.is_dir():
        return []
    return sorted(
        (d for d in raiz.iterdir() if d.is_dir() and not d.is_symlink() and (d / "raw" / "zabbix_raw.json").is_file()),
        key=lambda d: d.name,
    )


def write_partial_snapshot(base_dir: str | Path, raw: RawSnapshot, error: str) -> Path:
    """Grava o que deu tempo de coletar quando a coleta foi interrompida.

    Um snapshot parcial é gravado num diretório próprio e marcado como parcial
    nos metadados. Ele **não** vira a base: serve para auditoria e para permitir
    retomar a coleta sem baixar de novo o que já veio. Como cada snapshot é um
    diretório novo, um parcial nunca corrompe a coleta boa anterior.
    """
    meta = dict(raw.meta)
    colecao = dict(meta.get("collection") or {})
    colecao["partial"] = True
    colecao["interrupted_by"] = error[:300]
    meta["collection"] = colecao
    parcial = RawSnapshot(meta=meta, data=raw.data, api_calls=raw.api_calls)

    sufixo = "-".join(x for x in (scope_suffix(meta), "parcial") if x)
    snapshot_dir = new_snapshot_dir(base_dir, suffix=sufixo)
    write_json(snapshot_dir / "raw" / "zabbix_raw.json", parcial.to_dict())
    write_json(
        snapshot_dir / "report.json",
        {
            "meta": meta,
            "counts": {name: len(rows) for name, rows in sorted(raw.data.items())},
            "partial": True,
            "error": error[:1000],
        },
    )
    return snapshot_dir
