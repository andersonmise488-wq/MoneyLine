from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from moneyline.constants import CONFIG_DIR
from moneyline.config_loader import get_markets_config
from moneyline.markets.guard import accept_market_name, has_scoreline_handicap, norm, should_drop_raw_market
from moneyline.markets.resolve import pattern_matches_name, should_replace_market_key
from moneyline.models.schemas import Sport


@lru_cache
def get_market_aliases() -> dict[str, Any]:
    path = CONFIG_DIR / "market_aliases.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class MarketRegistry:
    """Canonical sport/market definitions and name resolution."""

    def __init__(self) -> None:
        self._markets = get_markets_config()
        self._aliases = get_market_aliases()
        self._exact: dict[tuple[Sport, str], tuple[str, dict]] = {}
        self._patterns: dict[Sport, list[tuple[str, str, dict]]] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for sport_key, markets in self._markets.items():
            sport = Sport(sport_key)
            patterns: list[tuple[str, str, dict]] = []
            for market_key, spec in markets.items():
                names = {norm(spec["display"])}
                names.update(norm(n) for n in spec.get("odibets_names", []))
                extra = self._aliases.get(sport_key, {}).get(market_key, [])
                names.update(norm(n) for n in extra)
                for name in names:
                    existing = self._exact.get((sport, name))
                    if existing and not should_replace_market_key(existing[0], market_key):
                        patterns.append((market_key, name, spec))
                        continue
                    self._exact[(sport, name)] = (market_key, spec)
                    patterns.append((market_key, name, spec))
            patterns.sort(key=lambda x: len(x[1]), reverse=True)
            self._patterns[sport] = patterns

    def all_sports(self) -> list[Sport]:
        return [Sport(k) for k in self._markets.keys()]

    def allowed_market_keys(self, sport: Sport) -> set[str]:
        return set(self._markets.get(sport.value, {}).keys())

    def market_spec(self, sport: Sport, market_key: str) -> dict | None:
        return self._markets.get(sport.value, {}).get(market_key)

    def _accept(self, market_key: str, market_name: str, sport: Sport) -> bool:
        return accept_market_name(market_key, market_name, sport)

    def resolve(self, sport: Sport, market_name: str) -> tuple[str, dict] | None:
        if should_drop_raw_market(market_name):
            return None
        key = norm(market_name)
        if hit := self._exact.get((sport, key)):
            if not self._accept(hit[0], market_name, sport):
                return None
            return hit
        for market_key, pattern, spec in self._patterns.get(sport, []):
            if pattern_matches_name(pattern, key):
                if not self._accept(market_key, market_name, sport):
                    continue
                return market_key, spec
        if has_scoreline_handicap(market_name):
            if spec := self.market_spec(sport, "european_handicap"):
                if self._accept("european_handicap", market_name, sport):
                    return "european_handicap", spec
        return None

    def filter_allowed(self, sport: Sport, markets: list) -> list:
        allowed = self.allowed_market_keys(sport)
        return [m for m in markets if m.market_key in allowed]
