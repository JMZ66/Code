from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    """只读打开文件计算 SHA-256。"""
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY)
    try:
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    return os.stat(path, follow_symlinks=True).st_size


def assert_unchanged(path: Path, digest: str, size: int) -> None:
    from gcms_kb.errors import OriginalModified

    now = sha256_file(path)
    now_size = file_size(path)
    if now != digest or now_size != size:
        raise OriginalModified(f"原始文件在读取过程中发生变化，已中止：{path}")
