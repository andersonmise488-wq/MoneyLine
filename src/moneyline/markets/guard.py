"""Strict market-name guard: reject cross-period and cross-market contamination.

Every raw bookmaker label must pass accept_market_name() after pattern resolution.
When in doubt, reject — false negatives beat false arbs.
"""
from __future__ import annotations

import re

from moneyline.models.schemas import Sport

# ── shared normalisation ──────────────────────────────────────────────────────

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


# ── global contamination signals ──────────────────────────────────────────────

# Two market families joined (explicit separators only — not "/" inside "over/under").
_COMBO_DUAL = re.compile(
    r"(?:"
    r"1x2|match result|final result|outcome|winner|double chance|draw no bet|"
    r"handicap|btts|both teams(?:\s+to)?\s+score|total(?:\s+goals)?|over/under|"
    r"correct score|half time|full time"
    r")"
    r".{0,40}"
    r"(?:\s&\s|\s+and\s+|\s\+\s+|\s/\s)"
    r".{0,40}"
    r"(?:"
    r"1x2|match result|final result|outcome|winner|double chance|draw no bet|"
    r"handicap|btts|both teams(?:\s+to)?\s+score|total(?:\s+goals)?|over/under|"
    r"correct score|half time|full time|goals|over|under|score"
    r")",
    re.I,
)
_COMBO_AND_TAIL = re.compile(
    r"\band\b\s+("
    r"total|both teams|btts|goals|over|under|handicap|1x2|score|double chance"
    r")",
    re.I,
)
_HTFT = re.compile(
    r"half\s*time\s*[-–/]\s*full\s*time|ht\s*/\s*ft|halftime\s*[/\s-]+\s*fulltime",
    re.I,
)
_GOAL_COMBO = re.compile(
    r"\{?!?goalnr\}|goal\s*&|&\s*1x2|1x2\s*&|result\s*\+|final result\s*\+",
    re.I,
)
_OR_COMBO = re.compile(
    r"\b(draw|1|2|home|away)\s+or\s+(both teams|btts)",
    re.I,
)
_INTERVAL = re.compile(
    r"\b\d+\s*-\s*\d+\s*min|\b\d+\s*minutes?\s*[-–]|\bfrom\s+\d+\s+to\s+\d+|\b\d+\s*min\b",
    re.I,
)
_SET_PERIOD = re.compile(r"\b(1st|2nd|3rd|4th|5th)\s+set\b", re.I)
_INNING = re.compile(r"\b\d+(st|nd|rd|th)\s+innings?\b|\binnings?\s+\d+\b", re.I)
_SCORELINE = re.compile(r"(\d+)\s*:\s*(\d+)")

_GLOBAL_REJECT = frozenset(
    {
        "halftime/fulltime",
        "half time/full time",
        "ht/ft",
        "multigoal",
        "correct score",
        "exact goal",
        "odd/even",
        "odd even",
        "to win both halves",
        "score in both halves",
        "win both halves",
        "in both halves",
        "both halves over",
        "mozzart combinations",
        "combinations",
        "outcome and total",
        "outcome & total",
    }
)

# ── helpers ───────────────────────────────────────────────────────────────────

def has_scoreline_handicap(name: str) -> bool:
    key = norm(name)
    return "handicap" in key and bool(_SCORELINE.search(key))


def is_interval_market(name: str) -> bool:
    return bool(_INTERVAL.search(name or ""))


def is_combo_market(name: str) -> bool:
    """True if raw label combines two or more bet types (never arbed)."""
    key = norm(name)
    if not key:
        return False
    if "&" in key or " + " in key or key.count("+") >= 2:
        return True
    if _COMBO_DUAL.search(key):
        return True
    if _COMBO_AND_TAIL.search(key):
        return True
    if _HTFT.search(key):
        return True
    if _GOAL_COMBO.search(key):
        return True
    if _OR_COMBO.search(key):
        return True
    if "combination" in key:
        return True
    if "both teams" in key and any(t in key for t in ("corner", "card", "booking")):
        return True
    if re.search(r"\d+\+", key) and "both teams" in key:
        return True
    if " or " in key and any(
        t in key
        for t in (
            "both teams",
            "btts",
            "total",
            "1x2",
            "double chance",
            "draw",
        )
    ):
        return True
    if re.search(r"\b\d+\s*or\s+more\b", key) and "both teams" in key:
        return True
    return False


def should_drop_raw_market(name: str) -> bool:
    """Drop before any pattern resolution (combo, interval, HT/FT, etc.)."""
    return is_globally_rejected(name)


def is_globally_rejected(name: str) -> bool:
    key = norm(name)
    if is_interval_market(name):
        return True
    if is_combo_market(name):
        return True
    return any(token in key for token in _GLOBAL_REJECT)


def _strip_half_prefix(key: str) -> str:
    return re.sub(r"^(1st|2nd|first|second)\s+half\s*[-–]\s*", "", key).strip()


# ── per-family validators ─────────────────────────────────────────────────────

def valid_match_result_1x2(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    block = (
        "corner",
        "booking",
        "card",
        "shot",
        "handicap",
        "no bet",
        "double chance",
        "winning",
        "first corner",
        "last corner",
        "goal &",
        "btts",
        "both teams",
        "total goal",
        "over/under",
        "over under",
    )
    if any(token in key for token in block):
        return False
    if re.search(r"1x2\s*\(", key):
        return False
    if re.search(r"\d+up\)", key) or re.search(r"\(\d+up\)", key):
        return False
    return True


def valid_btts(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    has_btts = (
        "both teams to score" in key
        or "both teams score" in key
        or key == "gg/ng"
        or key.endswith("gg/ng)")
    )
    if not has_btts:
        return False
    block = (
        "corner",
        "card",
        "booking",
        " or ",
        "2 or more",
        "3 or more",
    )
    if any(token in key for token in block):
        return False
    if re.search(r"\d+\+", key):
        return False
    remainder = _strip_half_prefix(key)
    allowed = (
        "both teams to score",
        "both teams score",
        "gg/ng",
        "both teams to score (gg/ng)",
    )
    return remainder in allowed or remainder.startswith("both teams to score (gg/ng)")


def valid_draw_no_bet(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    is_dnb = (
        "draw no bet" in key
        or "dnb" in key
        or "money back" in key
        or ("who will win" in key and "draw" in key)
    )
    if not is_dnb:
        return False
    if is_combo_market(name):
        return False
    if any(t in key for t in ("corner", "card", "booking", "handicap", "1x2", "total")):
        return False
    return True


def valid_over_under_goals(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    block = (
        "corner",
        "card",
        "booking",
        "handicap",
        "1x2",
        "double chance",
        "both teams",
        "btts",
        "no bet",
        "home team",
        "away team",
        "team 1",
        "team 2",
        "odd/even",
        "odd even",
    )
    if any(token in key for token in block):
        return False
    if "{home}" in key or "{away}" in key:
        return False
    return True


def valid_team_totals(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    team_signal = (
        "home team",
        "away team",
        "team 1",
        "team 2",
        "home total",
        "away total",
        "home o/u",
        "away o/u",
        "competitor1",
        "competitor2",
        "competitor 1",
        "competitor 2",
        "{home}",
        "{away}",
    )
    if not any(t in key for t in team_signal):
        return False
    if any(t in key for t in ("corner", "card", "booking", "handicap", "1x2", "both teams")):
        return False
    return True


def valid_asian_handicap(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    if "european" in key or "euro handicap" in key or "3-way handicap" in key:
        return False
    if re.search(r"\beuro\b", key) and "handicap" in key:
        return False
    if "handicap 1x2" in key or "handicap 1 x 2" in key:
        return False
    if "3 way" in key or "3-way" in key or "3 way" in key:
        return False
    if has_scoreline_handicap(name):
        return False
    if "2-way" in key or "2 way" in key:
        return True
    if "asian" in key:
        return True
    return "handicap" in key


def valid_european_handicap(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    if "asian" in key or "2-way" in key or "2 way" in key:
        return False
    if has_scoreline_handicap(name):
        return True
    if "handicap" in key and any(
        token in key
        for token in (
            "3-way",
            "3 way",
            "3way",
            "(3 way)",
            "1x2",
            "1 x 2",
        )
    ):
        return True
    return (
        "european" in key
        or "euro handicap" in key
        or "goals handicap 3 way" in key
    )


_TEAM_CORNER_TOTAL = re.compile(
    r"(?:"
    r"\b[12]\s+total\s+corners\b|"
    r"\b(home|away)(\s+team)?\s+total\s+corners\b|"
    r"\bteam\s+[12]\b.*\bcorner"
    r")",
    re.I,
)


def valid_corners_totals(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    if "corner" not in key:
        return False
    if _TEAM_CORNER_TOTAL.search(key):
        return False
    remainder = _strip_half_prefix(key)
    if remainder != key and _TEAM_CORNER_TOTAL.search(remainder):
        return False
    # Team-named labels like "SSC Napoli total corners" — only bare match totals allowed.
    tc = "total corners"
    pos = key.rfind(tc)
    if pos > 0:
        prefix = key[:pos].strip(" -–")
        if prefix and not re.fullmatch(r"(1st|2nd|first|second)\s+half", prefix):
            return False
    return True


def valid_two_way_winner(name: str) -> bool:
    """Moneyline / match winner (no draw)."""
    key = norm(name)
    if is_globally_rejected(name):
        return False
    block = (
        "handicap",
        "total",
        "over/under",
        "over under",
        "double chance",
        "draw",
        "corner",
        "card",
        "set betting",
        "correct score",
        "both teams",
    )
    if any(token in key for token in block):
        return False
    if re.search(r"\b3\s*way\b|\b1x2\b", key) and "moneyline" not in key:
        return False
    return True


def valid_three_way_winner(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    if any(t in key for t in ("handicap", "total", "over/under", "corner", "card", "both teams")):
        return False
    return True


def valid_spread_or_puck_line(name: str) -> bool:
    return valid_asian_handicap(name)


def valid_line_total(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    if any(t in key for t in ("handicap", "1x2", "corner", "card", "both teams", "double chance")):
        return False
    if "home team" in key or "away team" in key:
        return False
    return True


def valid_set_or_period_market(name: str, *, market_key: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    if is_interval_market(name):
        return False
    if market_key == "period_betting":
        return bool(re.search(r"\bperiod\b|\b1st\b|\b2nd\b|\b3rd\b", key))
    if market_key in ("set_handicap", "correct_set_score", "next_game_winner"):
        return bool(_SET_PERIOD.search(key) or "set" in key or market_key == "next_game_winner")
    return True


def valid_innings_market(name: str) -> bool:
    key = norm(name)
    if is_globally_rejected(name):
        return False
    return bool(_INNING.search(key) or "innings" in key or "session" in key)


# ── dispatch table ────────────────────────────────────────────────────────────

_VALIDATORS: dict[str, object] = {
    "match_result_1x2": valid_match_result_1x2,
    "btts": valid_btts,
    "draw_no_bet": valid_draw_no_bet,
    "over_under_goals": valid_over_under_goals,
    "team_totals": valid_team_totals,
    "asian_handicap": valid_asian_handicap,
    "european_handicap": valid_european_handicap,
    "corners_totals": valid_corners_totals,
    "moneyline": valid_two_way_winner,
    "match_winner": valid_two_way_winner,
    "spread": valid_spread_or_puck_line,
    "puck_line": valid_spread_or_puck_line,
    "game_handicap": valid_asian_handicap,
    "set_handicap": valid_asian_handicap,
    "run_line": valid_spread_or_puck_line,
    "totals": valid_line_total,
    "total_games": valid_line_total,
    "total_points": valid_line_total,
    "over_under_runs": valid_line_total,
    "quarter_totals": valid_line_total,
    "half_totals": valid_line_total,
    "innings_totals": valid_innings_market,
    "first_5_innings_totals": valid_innings_market,
    "session_betting": valid_innings_market,
    "period_betting": lambda n: valid_set_or_period_market(n, market_key="period_betting"),
    "set_betting": lambda n: valid_set_or_period_market(n, market_key="set_betting"),
    "correct_set_score": lambda n: valid_set_or_period_market(n, market_key="correct_set_score"),
    "next_game_winner": lambda n: valid_set_or_period_market(n, market_key="next_game_winner"),
}

# Sport-specific overrides for 3-way vs 2-way winner keys
_THREE_WAY_WINNER_KEYS = frozenset({"match_winner"})


def accept_market_name(market_key: str, market_name: str, sport: Sport) -> bool:
    """Return True only if raw_name is a clean instance of market_key."""
    if not market_name or not market_key:
        return False
    if is_globally_rejected(market_name):
        return False

    if market_key in _THREE_WAY_WINNER_KEYS and sport in (Sport.HANDBALL, Sport.VOLLEYBALL):
        return valid_three_way_winner(market_name)

    validator = _VALIDATORS.get(market_key)
    if validator is None:
        return False
    if callable(validator):
        ok = validator(market_name)
    else:
        ok = False

    if not ok:
        return False

    return True


def reject_reason(market_key: str, market_name: str, sport: Sport) -> str | None:
    """Diagnostic: why a name was rejected (None = accepted)."""
    if accept_market_name(market_key, market_name, sport):
        return None
    if is_interval_market(market_name):
        return "interval_window"
    if is_combo_market(market_name):
        return "combo_market"
    if is_globally_rejected(market_name):
        return "global_reject"
    return f"failed_{market_key}"
