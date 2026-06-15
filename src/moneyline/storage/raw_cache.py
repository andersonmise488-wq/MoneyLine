"""File-backed cache for per-event market payloads between scan cycles."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moneyline.constants import DATA_DIR
from moneyline.models.schemas import MarketOdds

logger = logging.getLogger(__name__)

RAW_CACHE_DIR = DATA_DIR / "raw" / "markets"


class RawOddsCache:
    """TTL cache for normalized market lists keyed by bookmaker/sport/event."""

    def __init__(self, root: Path | None = None, ttl_seconds: int = 300) -> None:
        self.root = root or RAW_CACHE_DIR
        self.ttl_seconds = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bookmaker: str, sport: str, event_id: str) -> Path:
        safe_id = (
            event_id.replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
            .replace("|", "_")
        )
        return self.root / bookmaker / sport / f"{safe_id}.json"

    def get(self, bookmaker: str, sport: str, event_id: str) -> list[MarketOdds] | None:
        if self.ttl_seconds <= 0:
            return None
        path = self._path(bookmaker, sport, event_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(str(payload["fetched_at"]))
            age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
            if age > self.ttl_seconds:
                return None
            return [MarketOdds.model_validate(row) for row in payload.get("markets", [])]
        except Exception as exc:
            logger.debug("Raw cache read failed %s: %s", path, exc)
            return None

    def put(self, bookmaker: str, sport: str, event_id: str, markets: list[MarketOdds]) -> None:
        path = self._path(bookmaker, sport, event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "markets": [m.model_dump(mode="json") for m in markets],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
