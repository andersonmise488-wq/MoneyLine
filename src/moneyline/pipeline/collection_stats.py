from __future__ import annotations

from dataclasses import dataclass, field

from moneyline.constants import SPORT_MIN_EVENTS


@dataclass
class BookmakerSportStats:
    bookmaker: str
    sport: str
    events: int = 0
    events_with_markets: int = 0
    markets: int = 0
    skipped: bool = False
    error: str | None = None


@dataclass
class CollectionStats:
    by_key: dict[str, BookmakerSportStats] = field(default_factory=dict)

    def set_row(
        self,
        *,
        bookmaker: str,
        sport: str,
        events: int,
        events_with_markets: int,
        markets: int,
        skipped: bool = False,
        error: str | None = None,
    ) -> None:
        key = f"{bookmaker}:{sport}"
        self.by_key[key] = BookmakerSportStats(
            bookmaker=bookmaker,
            sport=sport,
            events=events,
            events_with_markets=events_with_markets,
            markets=markets,
            skipped=skipped,
            error=error,
        )

    def to_dict(self) -> dict[str, dict]:
        return {
            key: {
                "bookmaker": row.bookmaker,
                "sport": row.sport,
                "events": row.events,
                "events_with_markets": row.events_with_markets,
                "markets": row.markets,
                "skipped": row.skipped,
                "error": row.error,
            }
            for key, row in self.by_key.items()
        }

    def weak_bookmakers(
        self,
        *,
        min_events: int = SPORT_MIN_EVENTS,
        match_first_markets: bool = True,
    ) -> list[str]:
        """Flag books with fetch errors or thin soccer coverage (primary KE market)."""
        _ = match_first_markets
        weak: set[str] = set()
        soccer_events: dict[str, int] = {}

        for row in self.by_key.values():
            if row.skipped:
                continue
            if row.error:
                weak.add(row.bookmaker)
                continue
            if row.sport == "soccer":
                soccer_events[row.bookmaker] = row.events

        for bookmaker, count in soccer_events.items():
            if count < min_events:
                weak.add(bookmaker)

        return sorted(weak)
