from __future__ import annotations

from datetime import datetime, timezone


def next_code(prefix: str, seq: int) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}-{day}-{seq:05d}"
