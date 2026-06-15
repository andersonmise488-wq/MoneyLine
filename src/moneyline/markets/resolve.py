from __future__ import annotations

import re

# Lower number wins when two market families share the same normalized alias.
_MARKET_KEY_PRIORITY: dict[str, int] = {
    "match_result_1x2": 10,
    "over_under_goals": 20,
    "btts": 21,
    "draw_no_bet": 22,
    "asian_handicap": 30,
    "european_handicap": 31,
    "puck_line": 32,
    "run_line": 32,
    "spread": 33,
    "game_handicap": 33,
    "set_handicap": 33,
    "corners_totals": 35,
    "team_totals": 36,
    "totals": 40,
    "total_points": 40,
    "total_games": 40,
    "quarter_totals": 41,
    "half_totals": 42,
    "period_betting": 43,
    "first_5_innings": 44,
    "first_5_innings_totals": 44,
    "over_under_runs": 45,
    "innings_totals": 46,
    "moneyline": 80,
    "match_winner": 81,
}

_SHORT_ALIAS_OK = frozenset({"1x2", "dnb", "gg/ng", "2 way", "3 way"})
_MIN_SUBSTRING_LEN = 5


def market_resolution_priority(market_key: str) -> int:
    return _MARKET_KEY_PRIORITY.get(market_key, 50)


def should_replace_market_key(existing_key: str, new_key: str) -> bool:
    """True when new_key should take over an exact alias collision."""
    return market_resolution_priority(new_key) < market_resolution_priority(existing_key)


def pattern_matches_name(pattern: str, key: str) -> bool:
    """Substring match with boundaries — avoids bare 'total' / 'handicap' false hits."""
    if pattern == key:
        return True
    if pattern in _SHORT_ALIAS_OK and pattern == key:
        return True
    if len(pattern) < _MIN_SUBSTRING_LEN and pattern not in _SHORT_ALIAS_OK:
        return False
    escaped = re.escape(pattern)
    if re.search(rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)", key):
        return True
    if len(pattern) >= 8 and pattern in key:
        return True
    return False
