from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from moneyline.arb.identity import opportunity_fingerprint, opportunity_id
from moneyline.constants import DATA_DIR
from moneyline.models.schemas import ArbitrageOpportunity

logger = logging.getLogger(__name__)

DEDUP_FILE = DATA_DIR / "cache" / "alert_dedup.json"


class AlertDedupStore:
    """Suppress repeat Telegram alerts unless the arb changed."""

    def __init__(self, path: Path | None = None, *, cooldown_minutes: int = 60) -> None:
        self.path = path or DEDUP_FILE
        self.cooldown_minutes = cooldown_minutes

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _parse_sent_at(self, raw: str) -> datetime:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def should_send(self, opp: ArbitrageOpportunity, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        oid = opportunity_id(opp)
        fp = opportunity_fingerprint(opp)
        record = self._load().get(oid)
        if not record:
            return True
        if record.get("fingerprint") != fp:
            return True
        sent_at = self._parse_sent_at(record["sent_at"])
        return now - sent_at >= timedelta(minutes=self.cooldown_minutes)

    def mark_sent(self, opp: ArbitrageOpportunity, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        oid = opportunity_id(opp)
        data = self._load()
        data[oid] = {
            "fingerprint": opportunity_fingerprint(opp),
            "sent_at": now.isoformat(),
        }
        self._prune(data, now=now)
        self._save(data)

    def _prune(self, data: dict[str, dict], *, now: datetime) -> None:
        cutoff = now - timedelta(hours=48)
        for oid in list(data):
            try:
                sent_at = self._parse_sent_at(data[oid]["sent_at"])
            except (KeyError, ValueError):
                del data[oid]
                continue
            if sent_at < cutoff:
                del data[oid]

    def filter_new(self, opportunities: list[ArbitrageOpportunity]) -> list[ArbitrageOpportunity]:
        return [opp for opp in opportunities if self.should_send(opp)]
