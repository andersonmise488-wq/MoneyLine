from __future__ import annotations

import abc
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from moneyline.config_loader import get_bookmaker_config
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.events.limits import trim_events
from moneyline.events.prematch import filter_prematch_only
from moneyline.events.window import filter_events_in_window
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, Sport


class BookmakerAdapter(abc.ABC):
    """Base adapter for Kenyan bookmaker odds APIs."""

    bookmaker: Bookmaker

    def __init__(self, timeout: float = 30.0) -> None:
        self.config = get_bookmaker_config(self.bookmaker.value)
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        base = dict(self.config.get("headers", {}))
        return base

    async def __aenter__(self) -> BookmakerAdapter:
        self._client = httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Adapter used outside async context manager")
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=8))
    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        resp = await self.client.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=8))
    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        resp = await self.client.post(url, **kwargs)
        resp.raise_for_status()
        return resp

    def sport_param(self, sport: Sport) -> str:
        """Return bookmaker-specific sport identifier."""
        ids = self.config.get("sport_ids") or self.config.get("sport_slugs") or {}
        return str(ids.get(sport.value, ""))

    def resolve_lookahead_hours(self, lookahead_hours: int | None) -> int:
        return lookahead_hours if lookahead_hours is not None else EVENT_LOOKAHEAD_HOURS

    def apply_event_window(
        self,
        events: list[Event],
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        return filter_events_in_window(events, self.resolve_lookahead_hours(lookahead_hours))

    def finalize_prematch_events(
        self,
        events: list[Event],
        limit: int,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        """Apply prematch-only filter, optional count cap, then enforce the lookahead window."""
        prematch = filter_prematch_only(events)
        return self.apply_event_window(trim_events(prematch, limit), lookahead_hours)

    @abc.abstractmethod
    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        ...

    @abc.abstractmethod
    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        ...

    async def health_check(self) -> dict[str, Any]:
        """Quick connectivity probe."""
        endpoints = self.config.get("endpoints", {})
        sport = Sport.SOCCER
        sport_param = self.sport_param(sport)
        results = []

        for name, template in endpoints.items():
            if "{" not in template:
                url = self._resolve_url(template)
            else:
                url = self._resolve_url(
                    template.format(
                        sport_id=sport_param,
                        sport_slug=sport_param,
                        page=0,
                        limit=2,
                        parent_match_id="0",
                        match_id="0",
                        event_id="0",
                    )
                )
            try:
                if template.strip().upper().startswith("POST"):
                    continue
                import time

                t0 = time.perf_counter()
                resp = await self.client.get(url)
                latency = (time.perf_counter() - t0) * 1000
                results.append(
                    {
                        "endpoint": name,
                        "url": url,
                        "status_code": resp.status_code,
                        "ok": resp.status_code == 200 and resp.text[:1] in ("{", "["),
                        "latency_ms": round(latency, 1),
                        "sample_bytes": len(resp.content),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "endpoint": name,
                        "url": url,
                        "status_code": None,
                        "ok": False,
                        "error": str(exc),
                    }
                )
        return {"bookmaker": self.bookmaker.value, "checks": results}

    def _resolve_url(self, template: str) -> str:
        template = template.strip()
        if template.upper().startswith("GET "):
            template = template[4:].strip()
        if template.upper().startswith("POST "):
            template = template[5:].strip()
        if template.startswith("http"):
            return template
        base = self.config["base_url"].rstrip("/")
        return f"{base}{template}"
