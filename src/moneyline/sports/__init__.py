"""Canonical sport list for scanning, matching, and alerts."""

from __future__ import annotations

from moneyline.config_loader import get_sports_config
from moneyline.models.schemas import Sport


def supported_sports() -> list[Sport]:
    """All sports from config/sports.yaml that exist in the Sport enum."""
    cfg = get_sports_config()
    sports: list[Sport] = []
    for key in cfg:
        try:
            sports.append(Sport(key))
        except ValueError:
            continue
    return sports


# Single source of truth for full-system scans (collector, scanner, alerts feed).
SUPPORTED_SPORTS: list[Sport] = supported_sports()
