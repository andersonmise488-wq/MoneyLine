from __future__ import annotations

from enum import Enum

from moneyline.constants import MIN_MATCH_CONFIDENCE_FOR_ARB
from moneyline.matching.competitions import canonical_competition_id, events_share_competition
from moneyline.matching.teams import competition_id_from_name
from moneyline.models.schemas import Bookmaker, Event, MatchedEvent

SPORTRADAR_TRIO = frozenset({Bookmaker.BETIKA, Bookmaker.ODIBETS, Bookmaker.PEPETA})


class MatchConfidence(str, Enum):
    SPORTRADAR_ID = "sportradar_id"          # 1.0
    BETRADAR_ID = "betradar_id"              # 0.95
    FUZZY_COMPETITION = "fuzzy_competition"  # 0.90
    FUZZY_ONLY = "fuzzy_only"                # 0.80

    @property
    def score(self) -> float:
        return {
            MatchConfidence.SPORTRADAR_ID: 1.0,
            MatchConfidence.BETRADAR_ID: 0.95,
            MatchConfidence.FUZZY_COMPETITION: 0.90,
            MatchConfidence.FUZZY_ONLY: 0.80,
        }[self]


def classify_parent_match_cluster(group: dict[Bookmaker, Event]) -> MatchConfidence:
    books = set(group.keys())
    if books and books.issubset(SPORTRADAR_TRIO):
        return MatchConfidence.SPORTRADAR_ID
    return MatchConfidence.BETRADAR_ID


def classify_fuzzy_cluster(group: dict[Bookmaker, Event]) -> MatchConfidence:
    rep = next(iter(group.values()))
    competition_ids = {
        canonical_competition_id(rep.sport, ev.competition)
        or competition_id_from_name(ev.competition)
        for ev in group.values()
    }
    competition_ids.discard(None)
    if len(competition_ids) == 1:
        return MatchConfidence.FUZZY_COMPETITION
    return MatchConfidence.FUZZY_ONLY


def is_sportradar_trio_cluster(cluster: MatchedEvent) -> bool:
    books = set(cluster.events.keys())
    return (
        len(books) >= 2
        and books.issubset(SPORTRADAR_TRIO)
        and cluster.match_confidence_kind == MatchConfidence.SPORTRADAR_ID.value
        and cluster.cluster_id.startswith("pm_")
    )


def cluster_allows_arbitrage(cluster: MatchedEvent) -> bool:
    """P0 gate: require match confidence >= 0.90, except Sportradar trio ID clusters."""
    if cluster.match_confidence >= MIN_MATCH_CONFIDENCE_FOR_ARB:
        return True
    if is_sportradar_trio_cluster(cluster):
        return True
    # Same-competition fuzzy matches (0.88) are reliable enough for non-soccer books.
    if (
        cluster.match_confidence_kind == MatchConfidence.FUZZY_COMPETITION.value
        and cluster.match_confidence >= MatchConfidence.FUZZY_COMPETITION.score
    ):
        return True
    return False
