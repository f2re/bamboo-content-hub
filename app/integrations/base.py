from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx


class PublishError(RuntimeError):
    """Base publishing error safe to expose to the operator."""


class PermanentPublishError(PublishError):
    """Configuration/content error that will not improve on retry."""


class TransientPublishError(PublishError):
    """Remote/network error that may succeed on retry."""


@dataclass(frozen=True)
class MediaInput:
    asset_id: str
    path: str
    mime_type: str
    public_url: str
    alt_text: str = ""
    role: str | None = None

    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith("image/")

    @property
    def is_video(self) -> bool:
        return self.mime_type.startswith("video/")


@dataclass(frozen=True)
class PublishRequest:
    text: str
    media: tuple[MediaInput, ...]
    config: dict
    content: dict = field(default_factory=dict)
    idempotency_key: str = ""


@dataclass(frozen=True)
class ConnectorCapabilities:
    automatic: bool = True
    text: bool = True
    images: bool = False
    videos: bool = False
    max_media: int = 0
    requires_public_media: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConnectorHealth:
    ok: bool
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PublishStatus:
    state: Literal["published", "processing", "failed", "unknown"]
    message: str = ""
    external_url: str | None = None


@dataclass(frozen=True)
class PublishResult:
    external_post_id: str | None = None
    external_url: str | None = None
    manual_action: bool = False
    message: str | None = None


class Connector(Protocol):
    channel: str

    def capabilities(self) -> ConnectorCapabilities: ...

    def validate(self, request: PublishRequest) -> list[str]: ...

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth: ...

    async def publish(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> PublishResult: ...

    async def status(
        self,
        request: PublishRequest,
        external_post_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> PublishStatus: ...


def validation_message(errors: list[str]) -> str:
    return "; ".join(error.strip() for error in errors if error.strip())


def ensure_valid(connector: Connector, request: PublishRequest) -> None:
    errors = connector.validate(request)
    if errors:
        raise PermanentPublishError(validation_message(errors))


def safe_http_error(response: httpx.Response, provider: str) -> str:
    """Build a useful remote API error without leaking request URLs or credentials."""
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("description") or error.get("code") or "")
            else:
                detail = str(body.get("description") or body.get("message") or error or "")
    except (ValueError, TypeError):
        detail = ""
    detail = detail.replace("\n", " ").strip()[:500]
    suffix = f": {detail}" if detail else ""
    return f"{provider} API returned HTTP {response.status_code}{suffix}"


def raise_for_provider(response: httpx.Response, provider: str) -> None:
    if response.is_success:
        return
    message = safe_http_error(response, provider)
    if response.status_code in {408, 409, 425, 429} or response.status_code >= 500:
        raise TransientPublishError(message)
    raise PermanentPublishError(message)
