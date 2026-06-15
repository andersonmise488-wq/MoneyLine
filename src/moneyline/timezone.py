from __future__ import annotations

from datetime import datetime, timedelta, timezone

EAT = timezone(timedelta(hours=3))


def to_eat(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(EAT)


def format_eat(dt: datetime, *, with_seconds: bool = False) -> str:
    local = to_eat(dt)
    fmt = "%Y-%m-%d %H:%M:%S EAT" if with_seconds else "%Y-%m-%d %H:%M EAT"
    return local.strftime(fmt)


def format_kickoff_eat(dt: datetime) -> tuple[str, str]:
    """Return (date, time) strings for alert display in EAT."""
    local = to_eat(dt)
    return local.strftime("%a, %d %b %Y"), local.strftime("%H:%M EAT")


def attach_eat_if_naive(dt: datetime) -> datetime:
    """Kenyan bookmakers often return local EAT timestamps without tz info."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EAT)
    return dt


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EAT).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)
