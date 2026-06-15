from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from moneyline.models.schemas import ArbitrageOpportunity


def opportunity_id(opp: ArbitrageOpportunity) -> str:
    """Stable key for the same fixture + market slot across scans."""
    line_part = "none" if opp.line is None else f"{float(opp.line):.2f}"
    fixture = opp.fixture_id or opp.cluster_id
    return f"{fixture}:{opp.market_key}:{opp.period.value}:{line_part}"


def opportunity_fingerprint(opp: ArbitrageOpportunity) -> str:
    """Changes when prices, legs, or margin shift."""
    leg_parts = sorted(
        f"{leg.get('bookmaker')}:{leg.get('side')}:{float(leg.get('price', 0)):.4f}"
        for leg in opp.legs
    )
    raw = f"{opportunity_id(opp)}|{opp.margin_pct:.4f}|{'|'.join(leg_parts)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def merge_active_opportunities(
    existing: list[ArbitrageOpportunity],
    fresh: list[ArbitrageOpportunity],
    *,
    now: datetime | None = None,
    grace_minutes: int = 20,
) -> list[ArbitrageOpportunity]:
    """Keep arbs visible while prematch; retain recent misses between scans."""
    now = now or datetime.now(timezone.utc)
    grace_cutoff = now - timedelta(minutes=grace_minutes)
    merged: dict[str, ArbitrageOpportunity] = {}

    for opp in fresh:
        merged[opportunity_id(opp)] = opp.model_copy(update={"detected_at": now})

    for opp in existing:
        oid = opportunity_id(opp)
        if oid in merged:
            continue
        if opp.start_time <= now:
            continue
        seen_at = opp.detected_at
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=timezone.utc)
        if seen_at >= grace_cutoff:
            merged[oid] = opp

    return sorted(merged.values(), key=lambda o: o.margin_pct, reverse=True)
