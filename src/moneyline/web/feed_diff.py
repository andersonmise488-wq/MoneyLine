from __future__ import annotations

from dataclasses import dataclass, field

from moneyline.arb.identity import opportunity_fingerprint, opportunity_id
from moneyline.models.schemas import ArbitrageOpportunity


@dataclass
class ArbFeedDiff:
    """Track arb fingerprints between broadcasts for incremental dashboard updates."""

    _fingerprints: dict[str, str] = field(default_factory=dict)

    @property
    def has_baseline(self) -> bool:
        return bool(self._fingerprints)

    def compute(
        self,
        opportunities: list[ArbitrageOpportunity],
    ) -> tuple[list[ArbitrageOpportunity], list[ArbitrageOpportunity], list[str]]:
        current: dict[str, tuple[str, ArbitrageOpportunity]] = {}
        for opp in opportunities:
            oid = opportunity_id(opp)
            current[oid] = (opportunity_fingerprint(opp), opp)

        added: list[ArbitrageOpportunity] = []
        updated: list[ArbitrageOpportunity] = []
        removed: list[str] = []

        for oid, (fp, opp) in current.items():
            prev = self._fingerprints.get(oid)
            if prev is None:
                added.append(opp)
            elif prev != fp:
                updated.append(opp)

        for oid in self._fingerprints:
            if oid not in current:
                removed.append(oid)

        self._fingerprints = {oid: fp for oid, (fp, _) in current.items()}
        return added, updated, removed

    def reset(self) -> None:
        self._fingerprints.clear()
