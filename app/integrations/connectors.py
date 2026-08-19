from __future__ import annotations

import json
import uuid
from contextlib import ExitStack
from pathlib import Path

import httpx

from .base import (
    ConnectorCapabilities,
    ConnectorHealth,
    PermanentPublishError,
    PublishRequest,
    PublishResult,
    PublishStatus,
    TransientPublishError,
    ensure_valid,
    raise_for_provider,
)


def _chunks(text: str, limit: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


class DemoConnector:
    channel = "demo"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(text=True, images=True, videos=True, max_media=50)

    def validate(self, request: PublishRequest) -> list[str]:
        return []

    async def health(self, request: PublishRequest, client: httpx.AsyncClient | None = None) -> ConnectorHealth:
        return ConnectorHealth(ok=True, message="Демонстрационный канал готов")

    async def publish(self, request: PublishRequest, client: httpx.AsyncClient | None = None) -> PublishResult:
        post_id = f"demo-{uuid.uuid4().hex[:12]}"
        return PublishResult(external_post_id=post_id, external_url=f"/demo/{post_id}")

    async def status(
        self,
        request: PublishRequest,
        external_post_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> PublishStatus:
        return PublishStatus(state="published", external_url=f"/demo/{external_post_id}")


class ManualConnector:
    channel = "livemaster"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            automatic=False,
            text=True,
            images=True,
            videos=True,
            max_media=50,
            notes=("Публикация выполняется вручную: публичного стабильного API не используется.",),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        return []

    async def health(self, request: PublishRequest, client: httpx.AsyncClient | None = None) -> ConnectorHealth:
        return ConnectorHealth(ok=True, message="Доступен ручной экспорт")

    async def publish(self, request: PublishRequest, client: httpx.AsyncClient | None = None) -> PublishResult:
        return PublishResult(manual_action=True, message="Карточка подготовлена для ручной публикации")

    async def status(
        self,
        request: PublishRequest,
        external_post_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> PublishStatus:
        return PublishStatus(state="unknown", message="Статус ручной публикации проверяется оператором")


class TelegramConnector:
    channel = "telegram"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(text=True, images=True, videos=True, max_media=10)

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("bot_token"):
            errors.append("Не задан Telegram bot token")
        if not request.config.get("chat_id"):
            errors.append("Не задан Telegram channel/chat ID")
        if len(request.media) > 10:
            errors.append("Telegram принимает не более 10 медиа в одной публикации")
        unsupported = [item.mime_type for item in request.media if not (item.is_image or item.is_video)]
        if unsupported:
            errors.append("Telegram: неподдерживаемый формат медиа")
        if not request.text.strip() and not request.media:
            errors.append("Пустую публикацию отправить нельзя")
        return errors

    @staticmethod
    def _api(config: dict) -> str:
        return f"https://api.telegram.org/bot{config['bot_token']}"

    async def health(self, request: PublishRequest, client: httpx.AsyncClient | None = None) -> ConnectorHealth:
        ensure_valid(self, request)
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            response = await client.get(f"{self._api(request.config)}/getMe")
            raise_for_provider(response, "Telegram")
            body = response.json()
            result = body.get("result") or {}
            return ConnectorHealth(
                ok=True,
                message="Telegram Bot API доступен",
                details={"bot_username": result.get("username"), "bot_id": result.get("id")},
            )
        except httpx.RequestError as exc:
            raise TransientPublishError(f"Telegram network error: {type(exc).__name__}") from exc
        finally:
            if owned:
                await client.aclose()

    async def _send_text(self, client: httpx.AsyncClient, api: str, chat_id: str, text: str) -> list[str]:
        ids: list[str] = []
        for chunk in _chunks(text, 4096):
            response = await client.post(f"{api}/sendMessage", json={"chat_id": chat_id, "text": chunk})
            raise_for_provider(response, "Telegram")
            result = response.json().get("result") or {}
            if result.get("message_id") is not None:
                ids.append(str(result["message_id"]))
        return ids

    async def publish(self, request: PublishRequest, client: httpx.AsyncClient | None = None) -> PublishResult:
        ensure_valid(self, request)
        api = self._api(request.config)
        chat_id = str(request.config["chat_id"])
        owned = client is None
        client = client or httpx.AsyncClient(timeout=60)
        try:
            message_ids: list[str] = []
            remaining_text = request.text.strip()
            if not request.media:
                message_ids.extend(await self._send_text(client, api, chat_id, remaining_text))
            elif len(request.media) == 1:
                item = request.media[0]
                caption = remaining_text[:1024]
                remaining_text = remaining_text[1024:].lstrip()
                method = "sendPhoto" if item.is_image else "sendVideo"
                file_field = "photo" if item.is_image else "video"
                with open(item.path, "rb") as handle:
                    response = await client.post(
                        f"{api}/{method}",
                        data={"chat_id": chat_id, "caption": caption},
                        files={file_field: (Path(item.path).name, handle, item.mime_type)},
                    )
                raise_for_provider(response, "Telegram")
                result = response.json().get("result") or {}
                if result.get("message_id") is not None:
                    message_ids.append(str(result["message_id"]))
                message_ids.extend(await self._send_text(client, api, chat_id, remaining_text))
            else:
                caption = remaining_text[:1024]
                remaining_text = remaining_text[1024:].lstrip()
                with ExitStack() as stack:
                    files: dict[str, tuple[str, object, str]] = {}
                    media_payload: list[dict] = []
                    for idx, item in enumerate(request.media):
                        handle = stack.enter_context(open(item.path, "rb"))
                        key = f"media_{idx}"
                        files[key] = (Path(item.path).name, handle, item.mime_type)
                        media_payload.append(
                            {
                                "type": "photo" if item.is_image else "video",
                                "media": f"attach://{key}",
                                "caption": caption if idx == 0 else "",
                            }
                        )
                    response = await client.post(
                        f"{api}/sendMediaGroup",
                        data={"chat_id": chat_id, "media": json.dumps(media_payload, ensure_ascii=False)},
                        files=files,
                    )
                raise_for_provider(response, "Telegram")
                result = response.json().get("result") or []
                message_ids.extend(str(row["message_id"]) for row in result if row.get("message_id") is not None)
                message_ids.extend(await self._send_text(client, api, chat_id, remaining_text))
            if not message_ids:
                raise PermanentPublishError("Telegram не вернул идентификатор опубликованного сообщения")
            return PublishResult(external_post_id=message_ids[0])
        except httpx.RequestError as exc:
            raise TransientPublishError(f"Telegram network error: {type(exc).__name__}") from exc
        finally:
            if owned:
                await client.aclose()

    async def status(
        self,
        request: PublishRequest,
        external_post_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> PublishStatus:
        return PublishStatus(
            state="unknown",
            message="Bot API не предоставляет универсальный endpoint чтения сообщения по message_id",
        )


CONNECTORS = {
    "demo": DemoConnector(),
    "livemaster": ManualConnector(),
    "telegram": TelegramConnector(),
}
