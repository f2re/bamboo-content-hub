from __future__ import annotations

import json
import uuid

import httpx

from .base import PublishResult


class DemoConnector:
    channel = "demo"

    async def publish(self, text: str, media_paths: list[str], config: dict) -> PublishResult:
        post_id = f"demo-{uuid.uuid4().hex[:12]}"
        return PublishResult(external_post_id=post_id, external_url=f"/demo/{post_id}")


class ManualConnector:
    channel = "livemaster"

    async def publish(self, text: str, media_paths: list[str], config: dict) -> PublishResult:
        return PublishResult(manual_action=True, message="Карточка подготовлена для ручной публикации")


class TelegramConnector:
    channel = "telegram"

    async def publish(self, text: str, media_paths: list[str], config: dict) -> PublishResult:
        token = config.get("bot_token")
        chat_id = config.get("chat_id")
        if not token or not chat_id:
            raise ValueError("Telegram bot_token/chat_id are not configured")
        api = f"https://api.telegram.org/bot{token}"
        async with httpx.AsyncClient(timeout=30) as client:
            if not media_paths:
                response = await client.post(f"{api}/sendMessage", json={"chat_id": chat_id, "text": text})
            elif len(media_paths) == 1:
                path = media_paths[0]
                with open(path, "rb") as handle:
                    response = await client.post(
                        f"{api}/sendPhoto",
                        data={"chat_id": chat_id, "caption": text},
                        files={"photo": handle},
                    )
            else:
                if len(media_paths) > 10:
                    raise ValueError("Telegram media group supports at most 10 items")
                files = {}
                media = []
                handles = []
                try:
                    for idx, path in enumerate(media_paths):
                        handle = open(path, "rb")
                        handles.append(handle)
                        key = f"f{idx}"
                        files[key] = handle
                        media.append({"type": "photo", "media": f"attach://{key}", "caption": text if idx == 0 else ""})
                    response = await client.post(f"{api}/sendMediaGroup", data={"chat_id": chat_id, "media": json.dumps(media)}, files=files)
                finally:
                    for handle in handles:
                        handle.close()
            response.raise_for_status()
            body = response.json()
            result = body.get("result")
            message_id = result[0]["message_id"] if isinstance(result, list) else result.get("message_id")
            return PublishResult(external_post_id=str(message_id))


CONNECTORS = {"demo": DemoConnector(), "livemaster": ManualConnector(), "telegram": TelegramConnector()}
