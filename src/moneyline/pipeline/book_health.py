from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moneyline.constants import DATA_DIR
from moneyline.models.schemas import Bookmaker

logger = logging.getLogger(__name__)

_HEALTH_FILE = DATA_DIR / "cache" / "book_health.json"
_COOLDOWN_MINUTES = 15


class BookHealthTracker:
    """Skip bookmakers after repeated fetch failures (circuit breaker)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _HEALTH_FILE

    def _failure_threshold(self) -> int:
        from moneyline.config.settings import get_settings

        return max(1, get_settings().book_circuit_breaker_failures)

    def prune_expired_cooldowns(self, *, now: datetime | None = None) -> list[str]:
        """Clear stale cooldown_until fields after cooldown expires."""
        now = now or datetime.now(timezone.utc)
        data = self._load()
        cleared: list[str] = []
        for name, row in list(data.items()):
            until_raw = row.get("cooldown_until")
            if not until_raw:
                continue
            try:
                bm = Bookmaker(name)
            except ValueError:
                continue
            if self.is_available(bm, now=now):
                row["cooldown_until"] = None
                row["failures"] = 0
                data[name] = row
                cleared.append(name)
        if cleared:
            self._save(data)
            logger.info("Book health: cleared expired cooldown for %s", ", ".join(cleared))
        return cleared

    def reset(self, bookmaker: Bookmaker) -> None:
        """Clear circuit-breaker state for a bookmaker (e.g. after a code fix)."""
        data = self._load()
        data[bookmaker.value] = {
            "failures": 0,
            "cooldown_until": None,
            "last_ok": _now_iso(),
        }
        self._save(data)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def is_available(self, bookmaker: Bookmaker, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        row = self._load().get(bookmaker.value, {})
        until_raw = row.get("cooldown_until")
        if not until_raw:
            return True
        try:
            until = datetime.fromisoformat(until_raw)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return now >= until

    def record_success(self, bookmaker: Bookmaker) -> None:
        data = self._load()
        data[bookmaker.value] = {"failures": 0, "cooldown_until": None, "last_ok": _now_iso()}
        self._save(data)

    def record_failure(self, bookmaker: Bookmaker, error: str) -> None:
        data = self._load()
        row = data.get(bookmaker.value, {"failures": 0})
        failures = int(row.get("failures", 0)) + 1
        row["failures"] = failures
        row["last_error"] = error[:200]
        row["last_fail"] = _now_iso()
        if failures >= self._failure_threshold():
            until = datetime.now(timezone.utc).timestamp() + _COOLDOWN_MINUTES * 60
            row["cooldown_until"] = datetime.fromtimestamp(until, tz=timezone.utc).isoformat()
            logger.warning(
                "Circuit breaker: %s paused for %s min after %s failures",
                bookmaker.value,
                _COOLDOWN_MINUTES,
                failures,
            )
        data[bookmaker.value] = row
        self._save(data)

    def snapshot(self) -> dict[str, Any]:
        return self._load()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
