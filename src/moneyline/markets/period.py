from __future__ import annotations

import re

from moneyline.models.schemas import MarketPeriod

_PERIOD_FROM_NAME: list[tuple[MarketPeriod, re.Pattern[str]]] = [
    (MarketPeriod.SECOND_HALF, re.compile(r"\b(2nd|second)\s+half\b|\b2h\b|\bhalf\s*2\b", re.I)),
    (MarketPeriod.FIRST_HALF, re.compile(r"\b(1st|first)\s+half\b|\b1h\b|\bhalf\s*1\b", re.I)),
    (MarketPeriod.SECOND_PERIOD, re.compile(r"\b(2nd|second)\s+period\b|\bperiod\s*2\b|\bp2\b", re.I)),
    (MarketPeriod.THIRD_PERIOD, re.compile(r"\b(3rd|third)\s+period\b|\bperiod\s*3\b|\bp3\b", re.I)),
    (MarketPeriod.FIRST_PERIOD, re.compile(r"\b(1st|first)\s+period\b|\bperiod\s*1\b|\bp1\b", re.I)),
    (MarketPeriod.FOURTH_QUARTER, re.compile(r"\b(4th|fourth)\s+quarter\b|\bq4\b|\b4q\b", re.I)),
    (MarketPeriod.THIRD_QUARTER, re.compile(r"\b(3rd|third)\s+quarter\b|\bq3\b|\b3q\b", re.I)),
    (MarketPeriod.SECOND_QUARTER, re.compile(r"\b(2nd|second)\s+quarter\b|\bq2\b|\b2q\b", re.I)),
    (MarketPeriod.FIRST_QUARTER, re.compile(r"\b(1st|first)\s+quarter\b|\bq1\b|\b1q\b", re.I)),
    (MarketPeriod.FULL_TIME, re.compile(r"\bfull\s*time\b|\bft\b|\bmatch\b|\b90\s*min", re.I)),
]

_DEFAULT_PERIOD_BY_MARKET_KEY: dict[str, MarketPeriod] = {
    "half_totals": MarketPeriod.FIRST_HALF,
    "quarter_totals": MarketPeriod.FIRST_QUARTER,
    "period_betting": MarketPeriod.FIRST_PERIOD,
    "first_5_innings": MarketPeriod.FULL_TIME,
}

_MARKET_KEYS_REQUIRING_LINE: set[str] = {
    "asian_handicap",
    "european_handicap",
    "over_under_goals",
    "corners_totals",
    "game_handicap",
    "total_games",
    "spread",
    "totals",
    "quarter_totals",
    "half_totals",
    "team_totals",
    "set_handicap",
    "total_points",
    "over_under_runs",
    "session_betting",
    "innings_totals",
    "run_line",
    "puck_line",
    "period_betting",
}


def period_from_name(market_name: str) -> MarketPeriod | None:
    text = market_name or ""
    if re.search(r"half\s*time\s*/\s*full|halftime\s*/\s*fulltime", text, re.I):
        return None
    for period, pattern in _PERIOD_FROM_NAME:
        if period == MarketPeriod.FULL_TIME:
            continue
        if pattern.search(text):
            return period
    # SportPesa: "Total Goals Over/Under - Half Time" = 1st-half totals (not HT/FT combo).
    if re.search(r"\bhalf\s*time\b", text, re.I):
        return MarketPeriod.FIRST_HALF
    if re.search(r"\bfull\s*time\b|\bft\b", text, re.I):
        return MarketPeriod.FULL_TIME
    return None


def detect_period(
    market_name: str,
    market_key: str = "",
    spec: dict | None = None,
) -> MarketPeriod:
    """Resolve market period from raw label, with market-key defaults."""
    from moneyline.markets.guard import is_interval_market

    if is_interval_market(market_name):
        # Interval windows (e.g. 1–10 min) are not valid arb periods.
        return MarketPeriod.FULL_TIME

    from_name = period_from_name(market_name)
    if from_name is not None:
        # BTTS without an explicit half/period in the name is always full match.
        if market_key == "btts" and from_name != MarketPeriod.FULL_TIME:
            if not re.search(r"\b(1st|first|2nd|second)\s+half\b", market_name, re.I):
                return MarketPeriod.FULL_TIME
        return from_name

    if spec and spec.get("default_period"):
        try:
            return MarketPeriod(str(spec["default_period"]))
        except ValueError:
            pass

    default = _DEFAULT_PERIOD_BY_MARKET_KEY.get(market_key)
    if default:
        return default

    return MarketPeriod.FULL_TIME


def period_label(period: MarketPeriod) -> str:
    labels = {
        MarketPeriod.FULL_TIME: "Full Time",
        MarketPeriod.FIRST_HALF: "1st Half",
        MarketPeriod.SECOND_HALF: "2nd Half",
        MarketPeriod.FIRST_PERIOD: "1st Period",
        MarketPeriod.SECOND_PERIOD: "2nd Period",
        MarketPeriod.THIRD_PERIOD: "3rd Period",
        MarketPeriod.FIRST_QUARTER: "1st Quarter",
        MarketPeriod.SECOND_QUARTER: "2nd Quarter",
        MarketPeriod.THIRD_QUARTER: "3rd Quarter",
        MarketPeriod.FOURTH_QUARTER: "4th Quarter",
    }
    return labels.get(period, period.value.replace("_", " ").title())


def market_requires_line(market_key: str, spec: dict | None = None) -> bool:
    if spec and spec.get("line_field"):
        return True
    return market_key in _MARKET_KEYS_REQUIRING_LINE


def format_line(line: float | None) -> str:
    if line is None:
        return "-"
    if line == int(line):
        return str(int(line))
    return f"{line:.2f}".rstrip("0").rstrip(".")


def resolve_outcome_label(label: str, line: float | None) -> str:
    """Replace bookmaker template placeholders in outcome labels."""
    if "{" not in label:
        return label
    line_text = format_line(line) if line is not None else ""
    text = label
    for placeholder in ("{formattedHandicap}", "{handicap}", "{line}"):
        text = text.replace(placeholder, line_text)
    return text


def label_has_unresolved_template(label: str) -> bool:
    return "{" in label or "}" in label
