from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import yaml

from moneyline.constants import PROJECT_ROOT
from moneyline.models.schemas import MarketPeriod, Sport

_EQUIV_PATH = PROJECT_ROOT / "config" / "market_equivalence.yaml"


@dataclass(frozen=True)
class MarketSpec:
    """Canonical market identity (BetBurger BetDto / OddsJam market type)."""

    sport: Sport
    market_family: str
    period: MarketPeriod
    line: float | None
    scope: str = ""  # "", "home", "away"
    settlement: str = "regular_time"
    sub_type_id: str = ""

    def spec_id(self) -> str:
        return market_spec_id(
            sport=self.sport,
            market_family=self.market_family,
            period=self.period,
            line=self.line,
            scope=self.scope,
            settlement=self.settlement,
            sub_type_id=self.sub_type_id,
        )


def market_spec_id(
    *,
    sport: Sport,
    market_family: str,
    period: MarketPeriod,
    line: float | None,
    scope: str = "",
    settlement: str = "regular_time",
    sub_type_id: str = "",
) -> str:
    line_part = "" if line is None else f"{line:.2f}"
    raw = "|".join(
        [
            sport.value,
            market_family,
            period.value,
            scope,
            settlement,
            sub_type_id,
            line_part,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@lru_cache
def _equivalence_rules() -> dict:
    if not _EQUIV_PATH.exists():
        return {}
    return yaml.safe_load(_EQUIV_PATH.read_text(encoding="utf-8")) or {}


def periods_blocked(a: MarketPeriod, b: MarketPeriod) -> bool:
    rules = _equivalence_rules().get("blocks", {}).get("period_mismatch", []) or []
    pair = {a.value, b.value}
    for left, right in rules:
        if pair == {left, right}:
            return True
    return False


def market_family_requires_strict_period(market_family: str) -> bool:
    strict = _equivalence_rules().get("blocks", {}).get("strict_period_names", []) or []
    return market_family in strict


def is_blocked_market_family(market_family: str) -> bool:
    blocked = _equivalence_rules().get("blocks", {}).get("market_families", []) or []
    return market_family in blocked


def raw_name_blocked(raw_name: str | None) -> bool:
    """Drop raw labels that signal combo/interval markets before arb grouping."""
    if not raw_name:
        return False
    text = raw_name.lower()
    patterns = _equivalence_rules().get("blocks", {}).get("drop_raw_patterns", []) or []
    return any(str(pattern).lower() in text for pattern in patterns)


def reject_integer_totals_enabled() -> bool:
    rules = _equivalence_rules().get("line_rules", {}) or {}
    return bool(rules.get("reject_integer_totals", False))


def detect_settlement(raw_name: str | None) -> str:
    """Map raw label to canonical settlement (regular_time vs incl_ot, etc.)."""
    text = (raw_name or "").lower()
    if not text.strip():
        return "regular_time"
    settlement_rules = _equivalence_rules().get("settlement", {}) or {}
    for settlement_key, spec in settlement_rules.items():
        if settlement_key == "regular_time":
            continue
        if not isinstance(spec, dict):
            continue
        for alias in spec.get("aliases", []) or []:
            if str(alias).lower() in text:
                return settlement_key
    ot_markers = (
        "incl ot",
        "incl. ot",
        "including overtime",
        "incl overtime",
        "incl. overtime",
        "with overtime",
        "2 way - ot",
        "2-way - ot",
        "incl extra time",
        "including extra time",
    )
    if any(marker in text for marker in ot_markers):
        return "incl_ot"
    return "regular_time"


def line_tolerance() -> float:
    rules = _equivalence_rules().get("line_rules", {}) or {}
    return float(rules.get("line_tolerance", 0.01))
