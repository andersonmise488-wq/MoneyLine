from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Sport(str, Enum):
    SOCCER = "soccer"
    TENNIS = "tennis"
    BASKETBALL = "basketball"
    VOLLEYBALL = "volleyball"
    HANDBALL = "handball"
    BASEBALL = "baseball"
    CRICKET = "cricket"
    ICE_HOCKEY = "ice_hockey"


class Bookmaker(str, Enum):
    BETIKA = "betika"
    ODIBETS = "odibets"
    SPORTPESA = "sportpesa"
    MOZZARTBET = "mozzartbet"
    BETPAWA = "betpawa"
    SPORTYBET = "sportybet"
    BANGBET = "bangbet"
    PEPETA = "pepeta"
    SHABIKI = "shabiki"
    PALMSBET = "palmsbet"


class OutcomeSide(str, Enum):
    HOME = "home"
    AWAY = "away"
    DRAW = "draw"
    OVER = "over"
    UNDER = "under"
    YES = "yes"
    NO = "no"
    SCORE = "score"
    PLAYER = "player"


class MarketPeriod(str, Enum):
    FULL_TIME = "full_time"
    FIRST_HALF = "1st_half"
    SECOND_HALF = "2nd_half"
    FIRST_PERIOD = "1st_period"
    SECOND_PERIOD = "2nd_period"
    THIRD_PERIOD = "3rd_period"
    FIRST_QUARTER = "1st_quarter"
    SECOND_QUARTER = "2nd_quarter"
    THIRD_QUARTER = "3rd_quarter"
    FOURTH_QUARTER = "4th_quarter"


class Event(BaseModel):
    """Normalized sporting event."""

    event_key: str
    bookmaker: Bookmaker
    external_id: str
    parent_match_id: str | None = None
    sport: Sport
    home_team: str
    away_team: str
    competition: str | None = None
    start_time: datetime
    is_live: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class OddsOutcome(BaseModel):
    """Single priced outcome within a market."""

    side: OutcomeSide
    label: str
    price: float
    line: float | None = None
    external_outcome_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MarketOdds(BaseModel):
    """Normalized market with outcomes."""

    event_key: str
    bookmaker: Bookmaker
    sport: Sport
    market_key: str
    market_display: str
    is_live: bool = False
    line: float | None = None
    period: MarketPeriod = MarketPeriod.FULL_TIME
    outcomes: list[OddsOutcome]
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    raw_market_name: str | None = None
    sub_type_id: str | None = None


class MatchedEvent(BaseModel):
    """Cross-bookmaker event cluster."""

    cluster_id: str
    sport: Sport
    home_team: str
    away_team: str
    start_time: datetime
    competition: str | None = None
    teams_swapped: dict[str, bool] = Field(default_factory=dict)
    events: dict[Bookmaker, Event]
    fixture_id: str = ""
    match_confidence: float = 1.0
    match_confidence_kind: str = "sportradar_id"


class ArbitrageOpportunity(BaseModel):
    """Detected surebet / arb."""

    cluster_id: str
    sport: Sport
    market_key: str
    market_display: str
    period: MarketPeriod = MarketPeriod.FULL_TIME
    line: float | None = None
    home_team: str
    away_team: str
    competition: str | None = None
    start_time: datetime
    margin_pct: float
    implied_sum: float
    legs: list[dict[str, Any]]
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    fixture_id: str = ""
    match_confidence: float = 1.0
    market_spec_id: str = ""


class ProbeResult(BaseModel):
    """Endpoint health check result."""

    bookmaker: Bookmaker
    endpoint: str
    url: str
    status_code: int | None
    ok: bool
    latency_ms: float | None
    sample_bytes: int | None
    error: str | None = None
    notes: str | None = None
