import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.integrations.base import MediaInput, PublishRequest
from app.integrations.pinterest import PinterestConnector
from app.integrations.registry import CONNECTORS
from app.integrations.vk import VKConnector


def media(path, mime="image/jpeg"):
    return MediaInput(
        asset_id="m1",
        path=str(path),
        mime_type=mime,
        public_url="https://hub.example/media/public/token",
        alt_text="Керамическая чашка",
    )


def vk_request(path):
    return PublishRequest(
        text="Новая чашка",
        media=(media(path),),
        config={"access_token": "vk-secret", "owner_id": "-123"},
        idempotency_key="vk-key",
    )


def pinterest_request(path):
    return PublishRequest(
        text="Описание",
        media=(media(path),),
        config={"access_token": "pin-secret", "board_id": "board-1"},
        content={
            "title": "Чашка",
            "description": "Описание",
            "destination_url": "https://example.com/cup",
        },
        idempotency_key="pin-key",
    )


def test_registry_discovers_vk_and_pinterest():
    assert "vk" in CONNECTORS
    assert "pinterest" in CONNECTORS


@pytest.mark.asyncio
async def test_vk_photo_upload_and_wall_post(tmp_path):
    image = tmp_path / "cup.jpg"
    image.write_bytes(b"image")
    calls = []

    async def handler(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/photos.getWallUploadServer"):
            params = parse_qs((await request.aread()).decode())
            assert params["group_id"] == ["123"]
            assert params["v"] == ["5.199"]
            return httpx.Response(
                200,
                json={"response": {"upload_url": "https://upload.vk.test/photo"}},
            )
        if request.url.host == "upload.vk.test":
            return httpx.Response(200, json={"server": 7, "photo": "[]", "hash": "abc"})
        if path.endswith("/photos.saveWallPhoto"):
            params = parse_qs((await request.aread()).decode())
            assert params["group_id"] == ["123"]
            return httpx.Response(200, json={"response": [{"owner_id": -123, "id": 55}]})
        if path.endswith("/wall.post"):
            params = parse_qs((await request.aread()).decode())
            assert params["attachments"] == ["photo-123_55"]
            assert params["from_group"] == ["1"]
            assert params["owner_id"] == ["-123"]
            assert params["guid"] == ["vk-key"]
            return httpx.Response(200, json={"response": {"post_id": 77}})
        raise AssertionError(path)

    transport = httpx.MockTransport(handler)
    connector = VKConnector()
    async with httpx.AsyncClient(transport=transport) as client:
        result = await connector.publish(vk_request(image), client)
    assert result.external_post_id == "-123_77"
    assert result.external_url == "https://vk.com/wall-123_77"
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_vk_status_checks_wall_get_by_id(tmp_path):
    image = tmp_path / "cup.jpg"
    image.write_bytes(b"image")

    async def handler(request):
        if request.url.path.endswith("/wall.getById"):
            params = parse_qs((await request.aread()).decode())
            assert params["posts"] == ["-123_77"]
            return httpx.Response(200, json={"response": [{"id": 77, "owner_id": -123}]})
        raise AssertionError(request.url.path)

    connector = VKConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.status(vk_request(image), "-123_77", client)
    assert result.state == "published"


@pytest.mark.asyncio
async def test_pinterest_creates_image_pin(tmp_path):
    image = tmp_path / "cup.jpg"
    image.write_bytes(b"abc123")
    captured = {}

    async def handler(request):
        if request.url.path == "/v5/pins":
            captured.update(json.loads((await request.aread()).decode()))
            assert request.headers["authorization"] == "Bearer pin-secret"
            return httpx.Response(201, json={"id": "999"})
        raise AssertionError(request.url.path)

    connector = PinterestConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(pinterest_request(image), client)
    assert result.external_post_id == "999"
    assert captured["board_id"] == "board-1"
    assert captured["media_source"]["source_type"] == "image_base64"
    assert captured["media_source"]["data"] == "YWJjMTIz"
    assert captured["link"] == "https://example.com/cup"


@pytest.mark.asyncio
async def test_pinterest_health_and_status(tmp_path):
    image = tmp_path / "cup.jpg"
    image.write_bytes(b"abc")

    async def handler(request):
        if request.url.path == "/v5/boards/board-1":
            return httpx.Response(200, json={"id": "board-1", "name": "Bamboo"})
        if request.url.path == "/v5/pins/999":
            return httpx.Response(200, json={"id": "999"})
        raise AssertionError(request.url.path)

    connector = PinterestConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await connector.health(pinterest_request(image), client)
        status = await connector.status(pinterest_request(image), "999", client)
    assert health.ok is True
    assert health.details["name"] == "Bamboo"
    assert status.state == "published"


def test_vk_and_pinterest_reject_unsupported_video(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    video_media = media(video, "video/mp4")
    vk_errors = VKConnector().validate(
        PublishRequest("text", (video_media,), {"access_token": "x", "owner_id": "1"})
    )
    pin_errors = PinterestConnector().validate(
        PublishRequest("text", (video_media,), {"access_token": "x", "board_id": "1"})
    )
    assert any("изображ" in error for error in vk_errors)
    assert any("изображ" in error for error in pin_errors)
