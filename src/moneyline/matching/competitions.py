from __future__ import annotations

from functools import lru_cache

import yaml

from moneyline.constants import PROJECT_ROOT
from moneyline.matching.teams import alias_key, competition_id_from_name
from moneyline.models.schemas import Event, Sport

_ALIASES_PATH = PROJECT_ROOT / "config" / "competition_aliases.yaml"


@lru_cache
def _alias_index() -> dict[tuple[str, str], str]:
    if not _ALIASES_PATH.exists():
        return {}
    raw = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    index: dict[tuple[str, str], str] = {}
    for sport_key, entries in raw.items():
        if not isinstance(entries, dict):
            continue
        for canonical, spec in entries.items():
            canon_key = alias_key(canonical)
            index[(sport_key, canon_key)] = canonical
            for alias in spec.get("aliases", []) or []:
                index[(sport_key, alias_key(str(alias)))] = canonical
    return index


def canonical_competition_name(sport: Sport, name: str | None) -> str | None:
    if not name or not str(name).strip():
        return None
    key = alias_key(str(name))
    hit = _alias_index().get((sport.value, key))
    return hit or str(name).strip()


def canonical_competition_id(sport: Sport, name: str | None) -> str | None:
    canonical = canonical_competition_name(sport, name)
    if not canonical:
        return None
    return competition_id_from_name(canonical)


def events_share_competition(left: Event, right: Event) -> bool:
    """True when both events resolve to the same competition bucket."""
    left_id = canonical_competition_id(left.sport, left.competition)
    right_id = canonical_competition_id(right.sport, right.competition)
    if left_id and right_id:
        return left_id == right_id
    left_hash = competition_id_from_name(left.competition)
    right_hash = competition_id_from_name(right.competition)
    if left_hash and right_hash:
        return left_hash == right_hash
    return True
