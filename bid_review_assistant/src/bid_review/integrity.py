"""原始文件 SHA-256 校验：核查前后原文件保持不变。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from bid_review.models import FileIntegrity


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class IntegrityGuard:
    """记录导入前后哈希，确保只读流程未改写原文件。"""

    def __init__(self) -> None:
        self._before: dict[str, tuple[str, int]] = {}

    def snapshot_before(self, paths: list[str | Path]) -> None:
        for path in paths:
            p = Path(path).resolve()
            if not p.is_file():
                raise FileNotFoundError(f"文件不存在: {p}")
            self._before[str(p)] = (sha256_file(p), p.stat().st_size)

    def verify_after(self) -> list[FileIntegrity]:
        results: list[FileIntegrity] = []
        for path, (before, size) in self._before.items():
            after = sha256_file(path)
            results.append(
                FileIntegrity(
                    path=path,
                    filename=Path(path).name,
                    sha256_before=before,
                    sha256_after=after,
                    unchanged=(before == after),
                    size_bytes=size,
                )
            )
        return results
