from __future__ import annotations

import re


def normalize_parent_match_id(value: str | None) -> str | None:
    """Normalize Sportradar-style parent IDs across bookmaker formats."""
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():
        return text
    match = re.search(r"sr:match:(\d+)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r":match:(\d+)", text, re.I)
    if match:
        return match.group(1)
    return text
