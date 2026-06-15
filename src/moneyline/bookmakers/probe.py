from __future__ import annotations

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, Sport


class ProbeAdapter(BookmakerAdapter):
    """Placeholder adapter for bookmakers pending full API mapping."""

    def __init__(self, bookmaker: Bookmaker) -> None:
        self.bookmaker = bookmaker
        super().__init__()

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        raise NotImplementedError(
            f"{self.bookmaker.value} adapter not yet implemented — run `moneyline probe` "
            "and update config/bookmakers.yaml with captured endpoints."
        )

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        raise NotImplementedError(f"{self.bookmaker.value} markets not yet implemented")
