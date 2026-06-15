from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import yaml

from moneyline.constants import PROJECT_ROOT
from moneyline.matching.teams import alias_key, normalize_team
from moneyline.models.schemas import Sport
from moneyline.timezone import as_utc

_ALIASES_PATH = PROJECT_ROOT / "config" / "team_aliases.yaml"


@dataclass(frozen=True)
class Fixture:
    """Canonical cross-book fixture (OddsJam/BetBurger-style entity)."""

    fixture_id: str
    sport: Sport
    canonical_home: str
    canonical_away: str
    start_time: datetime
    competition_id: str | None = None


@dataclass(frozen=True)
class BookEventLink:
    """Maps a book-native event to a canonical fixture."""

    bookmaker: str
    external_id: str
    fixture_id: str
    raw_home: str
    raw_away: str
    parent_match_id: str | None
    confidence_kind: str


@lru_cache
def _team_alias_index() -> dict[tuple[str, str], str]:
    """(sport, alias_key) -> canonical_id."""
    if not _ALIASES_PATH.exists():
        return {}
    raw = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    index: dict[tuple[str, str], str] = {}
    for sport_key, teams in raw.items():
        if not isinstance(teams, dict):
            continue
        for canonical_name, spec in teams.items():
            if not isinstance(spec, dict):
                continue
            cid = str(spec.get("canonical_id", ""))
            if not cid:
                continue
            index[(sport_key, alias_key(canonical_name))] = cid
            for alias in spec.get("aliases", []) or []:
                index[(sport_key, alias_key(str(alias)))] = cid
    return index


def normalize_team_canonical(name: str, *, sport: Sport) -> str:
    """Resolve team/player to canonical_id or normalized fallback."""
    key = alias_key(name)
    cid = _team_alias_index().get((sport.value, key))
    if cid:
        return cid
    return normalize_team(name)


def canonical_team_id(name: str, *, sport: Sport) -> str:
    return normalize_team_canonical(name, sport=sport)


def fixture_id_for(
    *,
    sport: Sport,
    home: str,
    away: str,
    start_time: datetime,
) -> str:
    """Stable fixture key: sport + canonical teams + kickoff hour bucket."""
    bucket = as_utc(start_time).replace(minute=0, second=0, microsecond=0).isoformat()
    ch = normalize_team_canonical(home, sport=sport)
    ca = normalize_team_canonical(away, sport=sport)
    raw = f"{sport.value}|{ch}|{ca}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
