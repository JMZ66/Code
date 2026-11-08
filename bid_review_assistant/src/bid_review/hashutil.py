"""SHA-256 校验：核查前后原文件必须保持不变。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_unchanged(path: str | Path, expected_sha256: str) -> bool:
    return sha256_file(path) == expected_sha256
