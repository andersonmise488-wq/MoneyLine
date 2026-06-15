from __future__ import annotations

from moneyline.bookmakers.sportradar_feed import SportradarFeedAdapter
from moneyline.models.schemas import Bookmaker


class BetikaAdapter(SportradarFeedAdapter):
    bookmaker = Bookmaker.BETIKA

    def __init__(self) -> None:
        super().__init__(Bookmaker.BETIKA)

    async def fetch_sports(self) -> list[dict]:
        url = self._resolve_url(self.config["endpoints"]["sports"])
        resp = await self._get(url)
        return resp.json().get("data", [])
