from __future__ import annotations

from moneyline.alerts.dedup import AlertDedupStore
from moneyline.config.settings import Settings, get_settings
from moneyline.models.schemas import ArbitrageOpportunity
from moneyline.web.filters import filter_all_arbs, filter_premium_arbs, filter_public_arbs


def filter_realistic_for_feed(
    opportunities: list[ArbitrageOpportunity],
    *,
    settings: Settings | None = None,
) -> list[ArbitrageOpportunity]:
    settings = settings or get_settings()
    return filter_all_arbs(
        opportunities,
        min_margin_pct=settings.web_scan_min_margin_pct,
    )


def filter_public_feed(
    opportunities: list[ArbitrageOpportunity],
    *,
    settings: Settings | None = None,
) -> list[ArbitrageOpportunity]:
    settings = settings or get_settings()
    return filter_public_arbs(opportunities, max_margin_pct=settings.web_public_max_margin_pct)


def filter_premium_feed(
    opportunities: list[ArbitrageOpportunity],
    *,
    settings: Settings | None = None,
) -> list[ArbitrageOpportunity]:
    settings = settings or get_settings()
    return filter_premium_arbs(
        opportunities,
        min_margin_pct=settings.web_public_max_margin_pct + 0.01,
    )


def filter_telegram_alerts(
    opportunities: list[ArbitrageOpportunity],
    *,
    settings: Settings | None = None,
    deduplicate: bool = True,
) -> list[ArbitrageOpportunity]:
    settings = settings or get_settings()
    floor = settings.alert_min_margin_pct
    eligible = [o for o in opportunities if o.margin_pct > floor]
    if not deduplicate:
        return sorted(eligible, key=lambda o: o.margin_pct, reverse=True)
    store = AlertDedupStore(cooldown_minutes=settings.alert_dedup_minutes)
    fresh = store.filter_new(eligible)
    return sorted(fresh, key=lambda o: o.margin_pct, reverse=True)
