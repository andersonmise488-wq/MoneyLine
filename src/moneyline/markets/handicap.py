from __future__ import annotations

import re

from moneyline.models.schemas import OutcomeSide

# Sportradar / Altenar selection type ids for 3-way European handicap.
EUROPEAN_SELECTION_TYPE_IDS: dict[str, OutcomeSide] = {
    "1711": OutcomeSide.HOME,
    "1712": OutcomeSide.DRAW,
    "1713": OutcomeSide.AWAY,
}

# PalmsBet / Altenar 1x2-style ids on 3-way handicap rows.
EUROPEAN_1X2_SELECTION_TYPE_IDS: dict[str, OutcomeSide] = {
    "1": OutcomeSide.HOME,
    "2": OutcomeSide.DRAW,
    "3": OutcomeSide.AWAY,
}

# Sportradar ids for 2-way Asian handicap.
ASIAN_SELECTION_TYPE_IDS: dict[str, OutcomeSide] = {
    "1714": OutcomeSide.HOME,
    "1715": OutcomeSide.AWAY,
    # BangBet / Sportradar 2-way winner ids
    "4": OutcomeSide.HOME,
    "5": OutcomeSide.AWAY,
}

_SCORELINE = re.compile(r"(\d+)\s*:\s*(\d+)")


def parse_european_scoreline(text: str | None) -> float | None:
    """Convert scoreline handicap like 0:1 to a signed line (-1.0)."""
    if not text:
        return None
    match = _SCORELINE.search(str(text))
    if not match:
        return None
    home, away = int(match.group(1)), int(match.group(2))
    return float(home - away)


# Altenar / PalmsBet yes/no selection type ids.
YES_NO_SELECTION_TYPE_IDS: dict[str, OutcomeSide] = {
    "74": OutcomeSide.YES,
    "76": OutcomeSide.NO,
}


def side_from_yes_no_label(
    label: str,
    selection_type_id: str | int | None,
    *,
    allowed: set[str],
) -> OutcomeSide | None:
    sid = str(selection_type_id or "").strip()
    if sid in YES_NO_SELECTION_TYPE_IDS:
        side = YES_NO_SELECTION_TYPE_IDS[sid]
        if side.value in allowed:
            return side
    text = label.strip().lower()
    if text in ("yes", "gg") and "yes" in allowed:
        return OutcomeSide.YES
    if text in ("no", "ng") and "no" in allowed:
        return OutcomeSide.NO
    return None


def side_from_european_label(
    label: str,
    selection_type_id: str | int | None,
    *,
    allowed: set[str],
) -> OutcomeSide | None:
    sid = str(selection_type_id or "").strip()
    if sid in EUROPEAN_SELECTION_TYPE_IDS:
        side = EUROPEAN_SELECTION_TYPE_IDS[sid]
        if side.value in allowed:
            return side
    if "draw" in allowed and sid in EUROPEAN_1X2_SELECTION_TYPE_IDS:
        side = EUROPEAN_1X2_SELECTION_TYPE_IDS[sid]
        if side.value in allowed:
            return side

    text = label.strip().lower()
    if text in ("1", "home", "w1", "h1") and "home" in allowed:
        return OutcomeSide.HOME
    if text in ("x", "draw", "tie") and "draw" in allowed:
        return OutcomeSide.DRAW
    if text in ("2", "away", "w2", "h2") and "away" in allowed:
        return OutcomeSide.AWAY
    if (text.startswith("1 ") or text.startswith("1(") or text.startswith("1 (")) and "home" in allowed:
        return OutcomeSide.HOME
    if (text.startswith("home") or text.startswith("team 1") or text.startswith("w1")) and "home" in allowed:
        return OutcomeSide.HOME
    if (
        text.startswith("x ")
        or text.startswith("x(")
        or text.startswith("x (")
        or text.startswith("draw")
        or text.startswith("tie")
    ) and "draw" in allowed:
        return OutcomeSide.DRAW
    if (text.startswith("2 ") or text.startswith("2(") or text.startswith("2 (")) and "away" in allowed:
        return OutcomeSide.AWAY
    if (text.startswith("away") or text.startswith("team 2") or text.startswith("w2")) and "away" in allowed:
        return OutcomeSide.AWAY
    return None


def parse_handicap_line(*sources: str | None) -> float | None:
    """Parse handicap line from specifier strings, market names, or SPOV values."""
    for src in sources:
        if not src:
            continue
        text = str(src).strip()
        if not text:
            continue
        euro = parse_european_scoreline(text)
        if euro is not None:
            return euro
        lowered = text.lower()
        if "hcp=" in lowered:
            val = text.split("=", 1)[1].split("&", 1)[0].strip()
            euro = parse_european_scoreline(val)
            if euro is not None:
                return euro
            try:
                return float(val)
            except ValueError:
                continue
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if match:
            try:
                return float(match.group())
            except ValueError:
                continue
    return None


def side_from_asian_label(
    label: str,
    selection_type_id: str | int | None,
    *,
    allowed: set[str],
) -> OutcomeSide | None:
    sid = str(selection_type_id or "").strip()
    if sid in ASIAN_SELECTION_TYPE_IDS:
        side = ASIAN_SELECTION_TYPE_IDS[sid]
        if side.value in allowed:
            return side
    text = label.strip().lower()
    if ("home" in allowed or len(allowed) == 2) and (
        text.startswith("1 ") or text.startswith("1(") or text.startswith("1 (")
    ):
        return OutcomeSide.HOME if "home" in allowed else None
    if ("away" in allowed or len(allowed) == 2) and (
        text.startswith("2 ") or text.startswith("2(") or text.startswith("2 (")
    ):
        return OutcomeSide.AWAY if "away" in allowed else None
    return None
