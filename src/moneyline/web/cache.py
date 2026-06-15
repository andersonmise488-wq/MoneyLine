from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from moneyline.constants import DATA_DIR
from moneyline.models.schemas import ArbitrageOpportunity

CACHE_DIR = DATA_DIR / "cache"
CACHE_FILE = CACHE_DIR / "arbs_latest.json"


@dataclass
class ScanSnapshot:
    opportunities: list[ArbitrageOpportunity]
    scanned_at: datetime | None
    scanning: bool
    error: str | None
    min_margin_pct: float
    max_events: int
    max_markets: int
    diagnostics: dict | None = None

    @property
    def total(self) -> int:
        return len(self.opportunities)


class ScanCache:
    @staticmethod
    def _ensure_dir() -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def load() -> ScanSnapshot:
        ScanCache._ensure_dir()
        if not CACHE_FILE.exists():
            return ScanSnapshot(
                opportunities=[],
                scanned_at=None,
                scanning=False,
                error=None,
                min_margin_pct=3.0,
                max_events=0,
                max_markets=0,
            )

        try:
            raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            scanned_at = None
            if raw.get("scanned_at"):
                scanned_at = datetime.fromisoformat(raw["scanned_at"])
            opps = [
                ArbitrageOpportunity.model_validate(item)
                for item in raw.get("opportunities", [])
            ]
            return ScanSnapshot(
                opportunities=opps,
                scanned_at=scanned_at,
                scanning=bool(raw.get("scanning", False)),
                error=raw.get("error"),
                min_margin_pct=float(raw.get("min_margin_pct", 3.0)),
                max_events=int(raw.get("max_events", 0)),
                max_markets=int(raw.get("max_markets", 0)),
                diagnostics=raw.get("diagnostics"),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            return ScanSnapshot(
                opportunities=[],
                scanned_at=None,
                scanning=False,
                error="Cache file corrupted",
                min_margin_pct=3.0,
                max_events=0,
                max_markets=0,
            )

    @staticmethod
    def save(
        opportunities: list[ArbitrageOpportunity],
        *,
        scanned_at: datetime,
        scanning: bool = False,
        error: str | None = None,
        min_margin_pct: float = 3.0,
        max_events: int = 0,
        max_markets: int = 0,
        diagnostics: dict | None = None,
        scan_started_at: datetime | None = None,
    ) -> None:
        ScanCache._ensure_dir()
        started = scan_started_at
        if scanning and started is None:
            started = datetime.now(timezone.utc)
        elif not scanning:
            started = None
        payload = {
            "scanned_at": scanned_at.isoformat(),
            "scan_started_at": started.isoformat() if started else None,
            "scanning": scanning,
            "error": error,
            "min_margin_pct": min_margin_pct,
            "max_events": max_events,
            "max_markets": max_markets,
            "diagnostics": diagnostics,
            "opportunities": [opp.model_dump(mode="json") for opp in opportunities],
        }
        CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def mark_scanning(
        *,
        min_margin_pct: float,
        max_events: int,
        max_markets: int,
        clear_opportunities: bool = False,
    ) -> None:
        existing = ScanCache.load()
        ScanCache.save(
            [] if clear_opportunities else existing.opportunities,
            scanned_at=existing.scanned_at or datetime.now(timezone.utc),
            scanning=True,
            error=None,
            min_margin_pct=min_margin_pct,
            max_events=max_events,
            max_markets=max_markets,
            diagnostics=existing.diagnostics,
        )

    @staticmethod
    def is_stale(scanned_at: datetime | None, interval_minutes: int) -> bool:
        if scanned_at is None:
            return True
        age = datetime.now(timezone.utc) - scanned_at
        return age.total_seconds() >= interval_minutes * 60

    @staticmethod
    def recover_stuck_scanning(*, max_minutes: int = 45) -> bool:
        """Clear orphaned scanning=true left by a killed process."""
        ScanCache._ensure_dir()
        if not CACHE_FILE.exists():
            return False
        try:
            raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        if not raw.get("scanning"):
            return False
        now = datetime.now(timezone.utc)
        anchor = raw.get("scan_started_at") or raw.get("scanned_at")
        if anchor is None:
            stuck = True
        else:
            started = datetime.fromisoformat(anchor)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            stuck = (now - started).total_seconds() >= max_minutes * 60
        if not stuck:
            return False
        snapshot = ScanCache.load()
        ScanCache.save(
            snapshot.opportunities,
            scanned_at=snapshot.scanned_at or now,
            scanning=False,
            error=snapshot.error,
            min_margin_pct=snapshot.min_margin_pct,
            max_events=snapshot.max_events,
            max_markets=snapshot.max_markets,
            diagnostics=snapshot.diagnostics,
        )
        return True
