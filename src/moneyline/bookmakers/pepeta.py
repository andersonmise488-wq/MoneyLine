from __future__ import annotations

from moneyline.bookmakers.sportradar_feed import SportradarFeedAdapter
from moneyline.models.schemas import Bookmaker


class PepetaAdapter(SportradarFeedAdapter):
    bookmaker = Bookmaker.PEPETA

    def __init__(self) -> None:
        super().__init__(Bookmaker.PEPETA)
