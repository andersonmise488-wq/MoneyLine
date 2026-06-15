from __future__ import annotations

import asyncio
from typing import Any

from curl_cffi import requests as curl_requests


class CurlClient:
    """Sync HTTP client using curl_cffi browser impersonation (Akamai bypass)."""

    def __init__(self, impersonate: str = "chrome120", headers: dict[str, str] | None = None) -> None:
        self.impersonate = impersonate
        self.headers = headers or {}
        self._session: curl_requests.Session | None = None

    def _session_or_create(self) -> curl_requests.Session:
        if self._session is None:
            self._session = curl_requests.Session(impersonate=self.impersonate)
        return self._session

    def get(self, url: str, **kwargs: Any) -> curl_requests.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self._session_or_create().get(url, headers=headers, **kwargs)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    async def async_get(self, url: str, **kwargs: Any) -> curl_requests.Response:
        return await asyncio.to_thread(self.get, url, **kwargs)
