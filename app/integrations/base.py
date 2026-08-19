from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PublishResult:
    external_post_id: str | None = None
    external_url: str | None = None
    manual_action: bool = False
    message: str | None = None


class Connector(Protocol):
    channel: str

    async def publish(self, text: str, media_paths: list[str], config: dict) -> PublishResult: ...
