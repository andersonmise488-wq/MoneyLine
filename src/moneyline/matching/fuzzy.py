from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from rapidfuzz import fuzz, process

from moneyline.constants import (
    EVENT_KICKOFF_MATCH_MINUTES,
    EVENT_MATCH_THRESHOLD,
    TEAM_MATCH_THRESHOLD,
)
from moneyline.matching.ids import normalize_parent_match_id
from moneyline.matching.competitions import events_share_competition
from moneyline.matching.confidence import (
    SPORTRADAR_TRIO as SPORTRADAR_BOOKMAKERS,
    MatchConfidence,
    classify_fuzzy_cluster,
    classify_parent_match_cluster,
)
from moneyline.canonical.entities import fixture_id_for
from moneyline.matching.teams import normalize_team
from moneyline.models.schemas import Bookmaker, Event, MatchedEvent, Sport


from moneyline.timezone import as_utc


def pick_competition(events: dict[Bookmaker, Event]) -> str | None:
    for ev in events.values():
        if ev.competition and str(ev.competition).strip():
            return str(ev.competition).strip()
    return None


def event_fingerprint(home: str, away: str, start_time: datetime) -> str:
    """Stable key from normalized teams + kickoff hour bucket."""
    bucket = as_utc(start_time).replace(minute=0, second=0, microsecond=0).isoformat()
    raw = f"{normalize_team(home)}|{normalize_team(away)}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class EventMatcher:
    """Align events across bookmakers using parent_match_id and fuzzy fallback."""

    def __init__(
        self,
        time_window_minutes: int = EVENT_KICKOFF_MATCH_MINUTES,
        event_threshold: int = EVENT_MATCH_THRESHOLD,
        team_threshold: int = TEAM_MATCH_THRESHOLD,
    ) -> None:
        self.time_window = timedelta(minutes=time_window_minutes)
        self.event_threshold = event_threshold
        self.team_threshold = team_threshold

    def match_events(self, events: list[Event]) -> list[MatchedEvent]:
        by_parent: dict[str, dict[Bookmaker, Event]] = {}
        orphans: list[Event] = []

        for ev in events:
            parent_key = normalize_parent_match_id(ev.parent_match_id)
            if parent_key:
                bucket = by_parent.setdefault(parent_key, {})
                bucket[ev.bookmaker] = ev
            else:
                orphans.append(ev)

        clusters: list[MatchedEvent] = []

        for parent_id, group in by_parent.items():
            if len(group) < 2:
                orphans.extend(group.values())
                continue
            if set(group.keys()).issubset(SPORTRADAR_BOOKMAKERS):
                if not self._validate_kickoffs_only(group):
                    orphans.extend(group.values())
                    continue
                clusters.append(
                    self._build_cluster(
                        f"pm_{parent_id}",
                        group,
                        confidence=MatchConfidence.SPORTRADAR_ID,
                    )
                )
                continue
            if not self._validate_group(group):
                orphans.extend(group.values())
                continue
            clusters.append(
                self._build_cluster(
                    f"pm_{parent_id}",
                    group,
                    confidence=classify_parent_match_cluster(group),
                )
            )

        clusters.extend(self._fuzzy_cluster(orphans))
        return clusters

    def _build_cluster(
        self,
        cluster_id: str,
        group: dict[Bookmaker, Event],
        *,
        confidence: MatchConfidence,
    ) -> MatchedEvent:
        rep = next(iter(group.values()))
        teams_swapped: dict[str, bool] = {}
        for bm, ev in group.items():
            _, swapped = self._pair_score(rep, ev)
            teams_swapped[bm.value] = swapped

        start_times = sorted(as_utc(ev.start_time) for ev in group.values())
        canonical_start = start_times[len(start_times) // 2]

        return MatchedEvent(
            cluster_id=cluster_id,
            sport=rep.sport,
            home_team=rep.home_team,
            away_team=rep.away_team,
            start_time=canonical_start,
            competition=pick_competition(group),
            teams_swapped=teams_swapped,
            events=group,
            fixture_id=fixture_id_for(
                sport=rep.sport,
                home=rep.home_team,
                away=rep.away_team,
                start_time=canonical_start,
            ),
            match_confidence=confidence.score,
            match_confidence_kind=confidence.value,
        )

    def _validate_kickoffs_only(self, group: dict[Bookmaker, Event]) -> bool:
        events = list(group.values())
        for i, left in enumerate(events):
            for right in events[i + 1 :]:
                if not self._kickoff_close(left.start_time, right.start_time):
                    return False
        return True

    def _validate_group(self, group: dict[Bookmaker, Event]) -> bool:
        events = list(group.values())
        for i, left in enumerate(events):
            for right in events[i + 1 :]:
                if not self._kickoff_close(left.start_time, right.start_time):
                    return False
                if not events_share_competition(left, right):
                    return False
                score, _ = self._pair_score(left, right)
                if score < self.event_threshold:
                    return False
        return True

    def _kickoff_close(self, left: datetime, right: datetime) -> bool:
        return abs(as_utc(left) - as_utc(right)) <= self.time_window

    def _fuzzy_cluster(self, events: list[Event]) -> list[MatchedEvent]:
        if not events:
            return []

        n = len(events)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for i in range(n):
            for j in range(i + 1, n):
                a, b = events[i], events[j]
                if a.bookmaker == b.bookmaker:
                    continue
                if a.sport != b.sport:
                    continue
                if not self._kickoff_close(a.start_time, b.start_time):
                    continue
                if not events_share_competition(a, b):
                    continue
                score, _ = self._pair_score(a, b)
                if score >= self.event_threshold:
                    union(i, j)

        components: dict[int, list[Event]] = {}
        for idx, ev in enumerate(events):
            root = find(idx)
            components.setdefault(root, []).append(ev)

        clusters: list[MatchedEvent] = []
        for group_events in components.values():
            group: dict[Bookmaker, Event] = {}
            for ev in group_events:
                group[ev.bookmaker] = ev
            if len(group) < 2:
                continue
            rep = group_events[0]
            cid = event_fingerprint(rep.home_team, rep.away_team, rep.start_time)
            fuzzy_confidence = classify_fuzzy_cluster(group)
            clusters.append(
                self._build_cluster(
                    f"fz_{cid}",
                    group,
                    confidence=fuzzy_confidence,
                )
            )
        return clusters

    def _pair_score(self, a: Event, b: Event) -> tuple[float, bool]:
        home_score = fuzz.token_sort_ratio(normalize_team(a.home_team), normalize_team(b.home_team))
        away_score = fuzz.token_sort_ratio(normalize_team(a.away_team), normalize_team(b.away_team))
        swap_home = fuzz.token_sort_ratio(normalize_team(a.home_team), normalize_team(b.away_team))
        swap_away = fuzz.token_sort_ratio(normalize_team(a.away_team), normalize_team(b.home_team))
        direct = (home_score + away_score) / 2
        swapped = (swap_home + swap_away) / 2
        if swapped > direct:
            return swapped, True
        return direct, False

    def best_team_match(self, query: str, choices: list[str]) -> tuple[str, float] | None:
        if not choices:
            return None
        result = process.extractOne(
            normalize_team(query),
            [normalize_team(c) for c in choices],
            scorer=fuzz.token_sort_ratio,
        )
        if result and result[1] >= self.team_threshold:
            idx = result[2]
            return choices[idx], result[1]
        return None
