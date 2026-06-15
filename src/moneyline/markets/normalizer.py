from __future__ import annotations

import re
from typing import Any

from moneyline.config_loader import get_markets_config
from moneyline.markets.book_maps import canonical_from_book_ids
from moneyline.markets.guard import accept_market_name, should_drop_raw_market
from moneyline.markets.handicap import (
    parse_european_scoreline,
    parse_handicap_line,
    side_from_asian_label,
    side_from_european_label,
)
from moneyline.markets.period import detect_period, market_requires_line
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import (
    Bookmaker,
    MarketOdds,
    OddsOutcome,
    OutcomeSide,
    Sport,
)

_THREE_WAY_MARKET_KEYS = frozenset(
    {"match_result_1x2", "european_handicap", "match_winner", "period_betting", "first_5_innings"}
)
_THREE_WAY_SIDES = frozenset({OutcomeSide.HOME, OutcomeSide.DRAW, OutcomeSide.AWAY})


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


class MarketNormalizer:
    """Map bookmaker-specific markets to canonical MoneyLine keys."""

    def __init__(self) -> None:
        self._markets = get_markets_config()
        self._registry = MarketRegistry()
        self._betika_index: dict[tuple[Sport, str], tuple[str, dict]] = {}
        self._odibets_index: dict[tuple[Sport, str], tuple[str, dict]] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for sport_key, markets in self._markets.items():
            sport = Sport(sport_key)
            for market_key, spec in markets.items():
                for sid in spec.get("betika_sub_type_ids", []):
                    key = (sport, str(sid))
                    existing = self._betika_index.get(key)
                    if existing is None:
                        self._betika_index[key] = (market_key, spec)
                    elif spec.get("live_only") and not existing[1].get("live_only"):
                        continue
                    elif not spec.get("live_only"):
                        self._betika_index[key] = (market_key, spec)
                for name in spec.get("odibets_names", []):
                    self._odibets_index[(sport, _norm(name))] = (market_key, spec)

    def allowed_market_keys(self, sport: Sport) -> set[str]:
        return self._registry.allowed_market_keys(sport)

    def _resolve_sportradar_hit(
        self,
        bookmaker: Bookmaker,
        sport: Sport,
        sub_type_id: str,
        market_name: str,
    ) -> tuple[str, dict] | None:
        key = canonical_from_book_ids(
            bookmaker=bookmaker,
            sport=sport,
            sub_type_id=sub_type_id,
        )
        if key:
            spec = self._markets.get(sport.value, {}).get(key)
            if spec:
                return key, spec
        hit = self._betika_index.get((sport, str(sub_type_id)))
        if hit:
            return hit
        return self._odibets_index.get((sport, _norm(market_name)))

    def normalize_betika_market(
        self,
        sport: Sport,
        sub_type_id: str,
        market_name: str,
        outcomes_raw: list[dict[str, Any]],
        *,
        bookmaker: Bookmaker = Bookmaker.BETIKA,
        is_live: bool = False,
        event_key: str,
    ) -> MarketOdds | None:
        if should_drop_raw_market(market_name):
            return None
        hit = self._resolve_sportradar_hit(
            bookmaker, sport, str(sub_type_id), market_name
        )
        if not hit:
            return None
        market_key, spec = hit
        if not accept_market_name(market_key, market_name, sport):
            return None
        if spec.get("live_only") and not is_live:
            return None
        if not spec.get("live_only") and is_live and market_key.endswith("_live"):
            pass  # live-specific keys handled by live_only flag

        outcomes = self._parse_betika_outcomes(outcomes_raw, spec)
        if not outcomes:
            return None

        line = self._extract_line(outcomes_raw, spec)
        period = detect_period(market_name, market_key, spec)
        return MarketOdds(
            event_key=event_key,
            bookmaker=bookmaker,
            sport=sport,
            market_key=market_key,
            market_display=spec["display"],
            is_live=is_live,
            line=line,
            period=period,
            outcomes=outcomes,
            raw_market_name=market_name,
            sub_type_id=str(sub_type_id),
        )

    def expand_by_line(self, market: MarketOdds) -> list[MarketOdds]:
        """Split Sportradar-style multi-line markets into one row per line."""
        if not market_requires_line(market.market_key):
            return [market]
        by_line: dict[float, list[OddsOutcome]] = {}
        for outcome in market.outcomes:
            line = outcome.line if outcome.line is not None else market.line
            if line is None:
                return [market]
            key = round(float(line), 2)
            by_line.setdefault(key, []).append(outcome)
        if len(by_line) <= 1:
            if by_line:
                only_line = next(iter(by_line))
                return [market.model_copy(update={"line": only_line, "outcomes": by_line[only_line]})]
            return [market]
        expanded = [
            market.model_copy(update={"line": line, "outcomes": outs})
            for line, outs in sorted(by_line.items())
        ]
        if market.market_key in _THREE_WAY_MARKET_KEYS:
            expanded = [
                row
                for row in expanded
                if {o.side for o in row.outcomes} == _THREE_WAY_SIDES
            ]
        return expanded

    def normalize_odibets_market(
        self,
        sport: Sport,
        sub_type_id: str,
        market_name: str,
        outcomes_raw: list[dict[str, Any]],
        *,
        is_live: bool = False,
        event_key: str,
    ) -> MarketOdds | None:
        if should_drop_raw_market(market_name):
            return None
        hit = self._resolve_sportradar_hit(
            Bookmaker.ODIBETS, sport, str(sub_type_id), market_name
        )
        if not hit:
            return None
        market_key, spec = hit
        if not accept_market_name(market_key, market_name, sport):
            return None
        if spec.get("live_only") and not is_live:
            return None

        outcomes = self._parse_odibets_outcomes(outcomes_raw, spec)
        if not outcomes:
            return None

        line = self._extract_line_odibets(outcomes_raw, spec)
        period = detect_period(market_name, market_key, spec)
        return MarketOdds(
            event_key=event_key,
            bookmaker=Bookmaker.ODIBETS,
            sport=sport,
            market_key=market_key,
            market_display=spec["display"],
            is_live=is_live,
            line=line,
            period=period,
            outcomes=outcomes,
            raw_market_name=market_name,
            sub_type_id=str(sub_type_id),
        )

    def _parse_betika_outcomes(
        self, raw: list[dict[str, Any]], spec: dict
    ) -> list[OddsOutcome]:
        allowed = set(spec.get("outcomes", []))
        results: list[OddsOutcome] = []

        for item in raw:
            key = _norm(str(item.get("odd_key", "")))
            display = str(item.get("display") or item.get("outcome_name") or "")
            price = float(item.get("odd_value", 0))
            if price <= 1.0:
                continue

            side = self._map_betika_side(key, display, allowed, item)
            if side is None:
                continue

            line = parse_european_scoreline(str(item.get("special_bet_value", "")))
            if line is None:
                parsed = item.get("parsed_special_bet_value")
                if isinstance(parsed, dict):
                    line = parse_european_scoreline(str(parsed.get("hcp", "")))
            if line is None:
                line = self._parse_line(item.get("special_bet_value"))
            if line is None:
                line = self._line_from_outcome_label(display)
            results.append(
                OddsOutcome(
                    side=side,
                    label=display or key,
                    price=price,
                    line=line,
                    external_outcome_id=str(item.get("outcome_id", "")),
                    raw=item,
                )
            )
        return results

    def _parse_odibets_outcomes(
        self, raw: list[dict[str, Any]], spec: dict
    ) -> list[OddsOutcome]:
        allowed = set(spec.get("outcomes", []))
        results: list[OddsOutcome] = []

        for item in raw:
            key = _norm(str(item.get("outcome_key", "")))
            name = str(item.get("outcome_name", ""))
            price = float(item.get("odd_value", 0))
            if price <= 1.0:
                continue

            side = self._map_odibets_side(key, name, allowed, item)
            if side is None:
                continue

            results.append(
                OddsOutcome(
                    side=side,
                    label=name or key,
                    price=price,
                    line=self._parse_line(item.get("special_bet_value"))
                    or parse_handicap_line(
                        str(item.get("specifiers", "")),
                        str(item.get("special_bet_value", "")),
                    )
                    or self._line_from_outcome_label(name),
                    external_outcome_id=str(item.get("outcome_id", "")),
                    raw=item,
                )
            )
        return results

    def _map_betika_side(
        self, key: str, display: str, allowed: set[str], raw: dict | None = None
    ) -> OutcomeSide | None:
        d = _norm(display)
        outcome_id = str((raw or {}).get("outcome_id", ""))
        if "draw" in allowed:
            euro = side_from_european_label(
                display, outcome_id, allowed=allowed
            )
            if euro is not None:
                return euro
        if outcome_id == "1" or d in ("1", "home"):
            if "home" in allowed:
                return OutcomeSide.HOME
        if outcome_id == "2" or key == "draw" or d in ("x", "draw"):
            if "draw" in allowed:
                return OutcomeSide.DRAW
        if outcome_id == "3" or d in ("2", "away"):
            if "away" in allowed:
                return OutcomeSide.AWAY
        if key == "draw" or d == "x":
            return OutcomeSide.DRAW if "draw" in allowed else None
        if d in ("1", "home") or key.endswith("1"):
            return OutcomeSide.HOME if "home" in allowed else None
        if d in ("2", "away") or key.endswith("2"):
            return OutcomeSide.AWAY if "away" in allowed else None
        if "over" in key or d.startswith("over"):
            return OutcomeSide.OVER if "over" in allowed else None
        if "under" in key or d.startswith("under"):
            return OutcomeSide.UNDER if "under" in allowed else None
        if key in ("yes", "gg") or d == "yes":
            return OutcomeSide.YES if "yes" in allowed else None
        if key in ("no", "ng") or d == "no":
            return OutcomeSide.NO if "no" in allowed else None
        if "home" in allowed and "away" in allowed and len(allowed) == 2:
            # Two-way market: first unmatched home-ish key
            if d == "1":
                return OutcomeSide.HOME
            if d == "2":
                return OutcomeSide.AWAY
        if "score" in allowed:
            return OutcomeSide.SCORE
        if "player" in allowed:
            return OutcomeSide.PLAYER
        return None

    def _map_odibets_side(
        self, key: str, name: str, allowed: set[str], raw: dict | None = None
    ) -> OutcomeSide | None:
        n = _norm(name)
        outcome_id = str((raw or {}).get("outcome_id", ""))
        if "draw" in allowed:
            euro = side_from_european_label(name, outcome_id, allowed=allowed)
            if euro is not None:
                return euro
        asian = side_from_asian_label(name, outcome_id, allowed=allowed)
        if asian is not None:
            return asian
        if outcome_id == "1" or n in ("1", "home") or key == "1":
            if "home" in allowed:
                return OutcomeSide.HOME
        if outcome_id == "2" or "draw" in key or n in ("draw", "x") or key == "x":
            if "draw" in allowed:
                return OutcomeSide.DRAW
        if outcome_id == "3" or n in ("2", "away") or key == "2":
            if "away" in allowed:
                return OutcomeSide.AWAY
        if "draw" in key or n == "draw" or n == "x":
            return OutcomeSide.DRAW if "draw" in allowed else None
        if n in ("1", "home") or "home" in key:
            return OutcomeSide.HOME if "home" in allowed else None
        if n in ("2", "away") or "away" in key:
            return OutcomeSide.AWAY if "away" in allowed else None
        if "over" in key or n.startswith("over"):
            return OutcomeSide.OVER if "over" in allowed else None
        if "under" in key or n.startswith("under"):
            return OutcomeSide.UNDER if "under" in allowed else None
        if "yes" in key or n == "yes":
            return OutcomeSide.YES if "yes" in allowed else None
        if "no" in key or n == "no":
            return OutcomeSide.NO if "no" in allowed else None
        if "score" in allowed:
            return OutcomeSide.SCORE
        if "player" in allowed:
            return OutcomeSide.PLAYER
        return None

    def _parse_line(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("total", "hcp", "handicap", "line"):
                if key in value:
                    parsed = self._parse_line(value[key])
                    if parsed is not None:
                        return parsed
            for v in value.values():
                parsed = self._parse_line(v)
                if parsed is not None:
                    return parsed
            return None
        text = str(value).strip()
        if not text:
            return None
        match = re.search(r"[-+]?\d+\.?\d*", text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
        return None

    def _line_from_outcome_label(self, label: str) -> float | None:
        return self._parse_line(label)

    def _extract_line(self, raw: list[dict], spec: dict) -> float | None:
        if spec.get("line_field") is None:
            return None
        for item in raw:
            line = self._parse_line(item.get("special_bet_value"))
            if line is not None:
                return line
            parsed = item.get("parsed_special_bet_value")
            if isinstance(parsed, dict):
                line = self._parse_line(parsed.get("total") or parsed.get("hcp"))
                if line is not None:
                    return line
        return None

    def _extract_line_odibets(self, raw: list[dict], spec: dict) -> float | None:
        if spec.get("line_field") is None:
            return None
        for item in raw:
            for field in ("specifiers", "special_bet_value", "line"):
                value = item.get(field)
                if value is None:
                    continue
                line = parse_european_scoreline(str(value))
                if line is not None:
                    return line
                line = self._parse_line(value)
                if line is not None:
                    return line
        return None
