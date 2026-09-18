from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC "now".

    Every timestamp is stored as naive UTC so SQLite (no time zones) and
    Postgres round-trip identically; ``iso()`` adds the ``Z`` on the way out.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="milliseconds") + "Z"


def seconds_until(dt: datetime | None, now: datetime) -> float:
    if dt is None:
        return 0.0
    return max(0.0, (dt - now).total_seconds())
