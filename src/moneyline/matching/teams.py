from __future__ import annotations

import hashlib
import re
import unicodedata

from moneyline.models.schemas import Sport


def normalize_team(name: str) -> str:
    """Strip accents, punctuation, and common suffixes for fuzzy matching."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"\b(fc|sc|cf|afc|united|city|town|athletic|ca|cd)\b", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def alias_key(name: str) -> str:
    """Light normalization for alias lookup — do not strip united/city/fc tokens."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def competition_id_from_name(name: str | None) -> str | None:
    if not name or not str(name).strip():
        return None
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode()).hexdigest()[:12]
