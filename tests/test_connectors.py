from pathlib import Path

import httpx
import pytest

from app.integrations.base import MediaInput, PermanentPublishError, PublishRequest
from app.integrations.connectors import TelegramConnector, credential_provider


def request(config=None, media=(), text="Текст"):
    return PublishRequest(
        text=text,
        media=tuple(media),
        config=config or {"bot_token": "secret-token", "chat_id": "@bamboo"},
        content={},
        idempotency_key="test-key",
    )


def test_credential_provider_mapping():
    assert credential_provider("instagram") == "meta"
    assert credential_provider("facebook") == "meta"
    assert credential_provider("youtube") == "google"
    assert credential_provider("pinterest") == "pinterest"


def test_telegram_capabilities_and_validation():
    connector = TelegramConnector()
    capabilities = connector.capabilities()
    assert capabilities.images is True
    assert capabilities.videos is True
    assert capabilities.max_media == 10
    errors = connector.validate(request(config={}, text=""))
    assert any("bot token" in error for error in errors)
    assert any("chat ID" in error for error in errors)


@pytest.mark.asyncio
async def test_telegram_uses_send_video_and_splits_long_text(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    media = MediaInput(
        asset_id="1",
        path=str(video),
        mime_type="video/mp4",
        public_url="https://example.invalid/media/1",
    )
    paths = []

    async def handler(http_request):
        paths.append(http_request.url.path)
        if http_request.url.path.endswith("/sendVideo"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}})
        if http_request.url.path.endswith("/sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})
        raise AssertionError(http_request.url.path)

    connector = TelegramConnector()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await connector.publish(request(media=(media,), text="x" * 1200), client)
    assert result.external_post_id == "10"
    assert any(path.endswith("/sendVideo") for path in paths)
    assert any(path.endswith("/sendMessage") for path in paths)


@pytest.mark.asyncio
async def test_telegram_mixed_media_group_uses_photo_and_video(tmp_path):
    image = tmp_path / "photo.jpg"
    video = tmp_path / "clip.mp4"
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    media = (
        MediaInput("1", str(image), "image/jpeg", "https://example.invalid/1"),
        MediaInput("2", str(video), "video/mp4", "https://example.invalid/2"),
    )
    captured = {}

    async def handler(http_request):
        captured["body"] = http_request.content
        return httpx.Response(
            200,
            json={"ok": True, "result": [{"message_id": 20}, {"message_id": 21}]},
        )

    connector = TelegramConnector()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await connector.publish(request(media=media), client)
    assert result.external_post_id == "20"
    assert b'"type": "photo"' in captured["body"]
    assert b'"type": "video"' in captured["body"]


@pytest.mark.asyncio
async def test_telegram_api_error_does_not_leak_bot_token():
    async def handler(http_request):
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    connector = TelegramConnector()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(PermanentPublishError) as exc:
            await connector.health(request(), client)
    message = str(exc.value)
    assert "secret-token" not in message
    assert "Unauthorized" in message
