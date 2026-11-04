from datetime import datetime, timezone


def now_iso() -> str:
    """UTC ISO timestamp stored in the database. The UI may display local time."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_local(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str))
    except ValueError:
        return str(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def today_local() -> str:
    return datetime.now().astimezone().date().isoformat()
