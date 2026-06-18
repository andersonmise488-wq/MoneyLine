"""Production security middleware for the MoneyLine API."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from moneyline.config.settings import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["X-XSS-Protection"] = "0"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limit for sensitive routes."""

    def __init__(self, app, *, max_requests: int = 30, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = [t for t in self._hits[key] if t >= window_start]
        if len(hits) >= self.max_requests:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path.startswith("/stanbic/callback") or path.startswith("/ws/"):
            key = f"{self._client_key(request)}:{path}"
            if not self._allow(key):
                return Response("Too many requests", status_code=429)
        return await call_next(request)


def configure_cors(app) -> None:
    from fastapi.middleware.cors import CORSMiddleware

    settings = get_settings()
    origins = settings.allowed_origins()
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
