from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from urllib.parse import quote, urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .config import Settings
from .security import verify_session_token

SESSION_COOKIE = "bamboo_session"


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        events = self._events[key]
        cutoff = now - window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.limiter = SlidingWindowLimiter()
        self.base_origin = self._origin_tuple(settings.app_base_url)

    @staticmethod
    def _origin_tuple(value: str) -> tuple[str, str, int | None] | None:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname:
            return None
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
        return parsed.scheme.lower(), parsed.hostname.lower(), port

    def _same_origin(self, value: str | None) -> bool:
        if not value or self.base_origin is None:
            return False
        try:
            return self._origin_tuple(value) == self.base_origin
        except ValueError:
            return False

    @staticmethod
    def _public_path(path: str) -> bool:
        return (
            path == "/login"
            or path.startswith("/static/")
            or path.startswith("/health/")
            or path.startswith("/oauth/")
            or path.startswith("/webhooks/")
            or path.startswith("/media/public/")
        )

    @staticmethod
    def _client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _rate_limit(self, request: Request) -> Response | None:
        path = request.url.path
        client = self._client_key(request)
        if path == "/login" and request.method == "POST":
            key, limit = f"login:{client}", self.settings.auth_rate_limit_per_minute
        elif path.startswith("/api/oauth/"):
            key, limit = f"oauth:{client}", 30
        elif path.startswith("/oauth/"):
            key, limit = f"oauth-callback:{client}", 60
        elif path.startswith("/webhooks/"):
            key, limit = f"webhook:{client}", 120
        else:
            return None
        if self.limiter.allow(key, max(1, limit)):
            return None
        return PlainTextResponse("Слишком много запросов", status_code=429)

    @staticmethod
    def _wants_html(request: Request) -> bool:
        if request.url.path.startswith("/api/"):
            return False
        accept = request.headers.get("accept", "")
        return "text/html" in accept or not accept

    def _csrf_valid(self, request: Request, expected_token: str) -> bool:
        supplied = request.headers.get("x-csrf-token", "")
        if supplied and hmac.compare_digest(supplied, expected_token):
            return True
        if self._same_origin(request.headers.get("origin")):
            return True
        if self._same_origin(request.headers.get("referer")):
            return True
        return False

    def _headers(self, response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        if self.settings.secure_cookies:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limited = self._rate_limit(request)
        if limited is not None:
            return self._headers(limited)

        request.state.authenticated = self.settings.trusted_lan
        request.state.csrf_token = ""
        path = request.url.path
        public = self._public_path(path)

        if not self.settings.trusted_lan and not public:
            session = verify_session_token(self.settings, request.cookies.get(SESSION_COOKIE))
            if session is None:
                if request.method in {"GET", "HEAD"} and self._wants_html(request):
                    target = quote(path, safe="/")
                    return self._headers(RedirectResponse(f"/login?next={target}", status_code=303))
                return self._headers(JSONResponse({"detail": "Требуется вход"}, status_code=401))
            request.state.authenticated = True
            request.state.csrf_token = session["csrf"]
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not self._csrf_valid(request, session["csrf"]):
                return self._headers(JSONResponse({"detail": "CSRF-проверка не пройдена"}, status_code=403))

        response = await call_next(request)
        return self._headers(response)
