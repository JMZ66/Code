from datetime import datetime, timezone


def now_iso() -> str:
    """UTC ISO timestamp; UI may display as local."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
