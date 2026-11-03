"""Local integrity helpers (not cryptographic protection against privileged admins)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


GENESIS_HASH = "0" * 64


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chain_hash(prev_hash: str, payload: dict) -> str:
    return sha256_text(f"{prev_hash}|{canonical_json(payload)}")
