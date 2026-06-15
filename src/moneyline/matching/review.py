from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moneyline.constants import DATA_DIR, MIN_MATCH_CONFIDENCE_FOR_ARB
from moneyline.matching.confidence import is_sportradar_trio_cluster
from moneyline.models.schemas import MatchedEvent

_REVIEW_FILE = DATA_DIR / "cache" / "match_review_queue.json"
_MAX_ITEMS = 100


def cluster_needs_review(cluster: MatchedEvent) -> bool:
    if is_sportradar_trio_cluster(cluster):
        return False
    return cluster.match_confidence < MIN_MATCH_CONFIDENCE_FOR_ARB


def _serialize_cluster(cluster: MatchedEvent) -> dict[str, Any]:
    return {
        "cluster_id": cluster.cluster_id,
        "sport": cluster.sport.value,
        "home_team": cluster.home_team,
        "away_team": cluster.away_team,
        "competition": cluster.competition,
        "start_time": cluster.start_time.isoformat(),
        "match_confidence": cluster.match_confidence,
        "match_confidence_kind": cluster.match_confidence_kind,
        "fixture_id": cluster.fixture_id,
        "bookmakers": sorted(b.value for b in cluster.events.keys()),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }


class MatchReviewQueue:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _REVIEW_FILE

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return list(data.get("items", []))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"items": items[:_MAX_ITEMS], "updated_at": _now_iso()}, indent=2),
            encoding="utf-8",
        )

    def ingest_clusters(self, clusters: list[MatchedEvent]) -> int:
        items = self._load()
        seen = {item["cluster_id"] for item in items}
        added = 0
        for cluster in clusters:
            if not cluster_needs_review(cluster):
                continue
            if cluster.cluster_id in seen:
                continue
            items.insert(0, _serialize_cluster(cluster))
            seen.add(cluster.cluster_id)
            added += 1
        if added:
            self._save(items)
        return added

    def list_items(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._load()[:limit]

    def dismiss(self, cluster_id: str) -> bool:
        items = [i for i in self._load() if i.get("cluster_id") != cluster_id]
        if len(items) == len(self._load()):
            return False
        self._save(items)
        return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
