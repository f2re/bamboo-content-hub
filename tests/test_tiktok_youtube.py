from __future__ import annotations

import json

import httpx
import pytest

import app.integrations.youtube as youtube_module
from app.integrations.base import MediaInput, PublishRequest
from app.integrations.registry import CONNECTORS
from app.integrations.tiktok import TikTokConnector, _utf16_units, _video_chunk_plan
from app.integrations.youtube import YouTubeConnector, _next_offset, _tags_length


def tiktok_request(media=(), text="Новая работа", content=None):
    resolved_content = {
        "title": "Фото",
        "caption": text,
        "privacy_level": "SELF_ONLY",
        "commercial_content_toggle": False,
        "brand_content_toggle": False,
        "brand_organic_toggle": False,
        "direct_post_consent": True,
    }
    if content:
        resolved_content.update(content)
    return PublishRequest(
        text=text,
        media=tuple(media),
        config={"access_token": "tiktok-token"},
        content=resolved_content,
        idempotency_key="test-tiktok",
    )


def youtube_request(media=(), content=None):
    resolved_content = {
        "title": "Видео Bamboo",
        "description": "Описание",
        "privacy_status": "private",
        "tags": ["керамика", "Bamboo Pottery"],
    }
    if content:
        resolved_content.update(content)
    return PublishRequest(
        text="Видео Bamboo",
        media=tuple(media),
        config={"access_token": "youtube-token", "youtube_category_id": "22"},
        content=resolved_content,
        idempotency_key="test-youtube",
    )


def creator_response():
    return {
        "data": {
            "creator_username": "bamboo",
            "creator_nickname": "Bamboo Pottery",
            "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
            "comment_disabled": False,
            "duet_disabled": False,
            "stitch_disabled": False,
            "max_video_post_duration_sec": 600,
        },
        "error": {"code": "ok", "message": ""},
    }


def test_registry_contains_tiktok_and_youtube():
    assert isinstance(CONNECTORS["tiktok"], TikTokConnector)
    assert isinstance(CONNECTORS["youtube"], YouTubeConnector)


def test_tiktok_utf16_and_chunk_plan_match_api_rules():
    assert _utf16_units("A😀") == 3
    assert _video_chunk_plan(4 * 1024 * 1024) == (4 * 1024 * 1024, 1)
    assert _video_chunk_plan(64 * 1024 * 1024) == (64 * 1024 * 1024, 1)
    assert _video_chunk_plan(100 * 1024 * 1024) == (32 * 1024 * 1024, 3)


@pytest.mark.asyncio
async def test_tiktok_video_direct_post_and_status(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video!")
    media = MediaInput("1", str(video), "video/mp4", "https://media.example/video.mp4")
    captured = {}

    async def handler(request: httpx.Request):
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        if request.url.path.endswith("/video/init/"):
            captured["init"] = json.loads((await request.aread()).decode())
            return httpx.Response(
                200,
                json={
                    "data": {
                        "publish_id": "publish-1",
                        "upload_url": "https://upload.example/video",
                    },
                    "error": {"code": "ok", "message": ""},
                },
            )
        if request.url.host == "upload.example":
            captured["range"] = request.headers["content-range"]
            captured["body"] = await request.aread()
            return httpx.Response(201)
        if request.url.path.endswith("/status/fetch/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "PUBLISH_COMPLETE",
                        "publicaly_available_post_id": ["post-1"],
                    },
                    "error": {"code": "ok", "message": ""},
                },
            )
        raise AssertionError(str(request.url))

    connector = TikTokConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(tiktok_request((media,)), client)
        status = await connector.status(tiktok_request((media,)), result.external_post_id, client)

    assert result.external_post_id == "publish-1"
    assert result.processing is True
    assert captured["range"] == "bytes 0-5/6"
    assert captured["body"] == b"video!"
    assert captured["init"]["post_info"]["brand_content_toggle"] is False
    assert captured["init"]["source_info"]["total_chunk_count"] == 1
    assert status.state == "published"


@pytest.mark.asyncio
async def test_tiktok_photo_payload_uses_only_photo_fields(tmp_path):
    first = tmp_path / "one.jpg"
    second = tmp_path / "two.webp"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    media = (
        MediaInput("1", str(first), "image/jpeg", "https://media.example/one.jpg"),
        MediaInput("2", str(second), "image/webp", "https://media.example/two.webp"),
    )
    captured = {}

    async def handler(request: httpx.Request):
        if request.url.path.endswith("/creator_info/query/"):
            return httpx.Response(200, json=creator_response())
        if request.url.path.endswith("/content/init/"):
            captured.update(json.loads((await request.aread()).decode()))
            return httpx.Response(
                200,
                json={
                    "data": {"publish_id": "photo-1"},
                    "error": {"code": "ok", "message": ""},
                },
            )
        raise AssertionError(str(request.url))

    connector = TikTokConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(tiktok_request(media), client)

    assert result.external_post_id == "photo-1"
    assert captured["source_info"]["photo_images"] == [
        "https://media.example/one.jpg",
        "https://media.example/two.webp",
    ]
    assert captured["post_info"]["description"] == "Новая работа"
    assert "disable_duet" not in captured["post_info"]
    assert "disable_stitch" not in captured["post_info"]


def test_tiktok_validation_requires_consent_and_commercial_choice(tmp_path):
    image = tmp_path / "one.jpg"
    image.write_bytes(b"one")
    media = MediaInput("1", str(image), "image/jpeg", "https://media.example/one.jpg")
    connector = TikTokConnector()

    no_consent = tiktok_request((media,), content={"direct_post_consent": False})
    assert any("Подтвердите" in error for error in connector.validate(no_consent))

    no_commercial_kind = tiktok_request(
        (media,),
        content={"commercial_content_toggle": True},
    )
    assert any("выберите свой бренд" in error for error in connector.validate(no_commercial_kind))

    branded_private = tiktok_request(
        (media,),
        content={
            "commercial_content_toggle": True,
            "brand_content_toggle": True,
            "privacy_level": "SELF_ONLY",
        },
    )
    assert any("Платное партнёрство" in error for error in connector.validate(branded_private))

    private_url = MediaInput("2", str(image), "image/jpeg", "http://127.0.0.1/one.jpg")
    assert any("HTTPS URL" in error for error in connector.validate(tiktok_request((private_url,))))


@pytest.mark.asyncio
async def test_tiktok_health_returns_creator_controls():
    async def handler(_request):
        return httpx.Response(200, json=creator_response())

    connector = TikTokConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await connector.health(tiktok_request(), client)
    assert health.ok is True
    assert health.details["nickname"] == "Bamboo Pottery"
    assert health.details["privacy_level_options"] == ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]


def test_youtube_range_and_tag_helpers():
    assert _next_offset("bytes=0-999") == 1000
    assert _next_offset("garbage") is None
    assert _tags_length(["one", "two words"]) == len('one,"two words"')


@pytest.mark.asyncio
async def test_youtube_resumable_upload_uses_acknowledged_ranges(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube_module, "UPLOAD_CHUNK_SIZE", 4)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"0123456789")
    media = MediaInput("1", str(video), "video/mp4", "https://media.example/clip.mp4")
    ranges = []

    async def handler(request: httpx.Request):
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": "https://upload.example/session"})
        if request.url.host == "upload.example":
            ranges.append(request.headers.get("content-range"))
            body = await request.aread()
            if body == b"0123":
                return httpx.Response(308, headers={"Range": "bytes=0-3"})
            if body == b"4567":
                return httpx.Response(308, headers={"Range": "bytes=0-7"})
            assert body == b"89"
            return httpx.Response(201, json={"id": "youtube-1"})
        raise AssertionError(str(request.url))

    connector = YouTubeConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(youtube_request((media,)), client)

    assert ranges == ["bytes 0-3/10", "bytes 4-7/10", "bytes 8-9/10"]
    assert result.external_post_id == "youtube-1"
    assert result.external_url.endswith("youtube-1")


@pytest.mark.asyncio
async def test_youtube_recovers_after_server_error(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube_module, "UPLOAD_CHUNK_SIZE", 16)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    media = MediaInput("1", str(video), "video/mp4", "https://media.example/clip.mp4")
    puts = 0

    async def handler(request: httpx.Request):
        nonlocal puts
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": "https://upload.example/session"})
        body = await request.aread()
        if not body:
            return httpx.Response(308)
        puts += 1
        if puts == 1:
            return httpx.Response(503)
        return httpx.Response(201, json={"id": "youtube-recovered"})

    connector = YouTubeConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(youtube_request((media,)), client)
    assert puts == 2
    assert result.external_post_id == "youtube-recovered"


@pytest.mark.asyncio
async def test_youtube_status_and_health(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    media = MediaInput("1", str(video), "video/mp4", "https://media.example/clip.mp4")
    status_calls = 0

    async def handler(request: httpx.Request):
        nonlocal status_calls
        if request.url.path.endswith("/channels"):
            return httpx.Response(
                200,
                json={"items": [{"id": "channel-1", "snippet": {"title": "Bamboo"}}]},
            )
        if request.url.path.endswith("/videos"):
            status_calls += 1
            if status_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "status": {"uploadStatus": "uploaded"},
                                "processingDetails": {"processingStatus": "processing"},
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "status": {"uploadStatus": "processed"},
                            "processingDetails": {"processingStatus": "succeeded"},
                        }
                    ]
                },
            )
        raise AssertionError(str(request.url))

    connector = YouTubeConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await connector.health(youtube_request((media,)), client)
        processing = await connector.status(youtube_request((media,)), "video-1", client)
        published = await connector.status(youtube_request((media,)), "video-1", client)
    assert health.details["title"] == "Bamboo"
    assert processing.state == "processing"
    assert published.state == "published"


def test_youtube_validation_enforces_user_metadata(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    media = MediaInput("1", str(video), "video/mp4", "https://media.example/clip.mp4")
    connector = YouTubeConnector()
    invalid = youtube_request(
        (media,),
        content={
            "title": "<bad>",
            "description": "я" * 2501,
            "privacy_status": "",
            "tags": ["x" * 501],
        },
    )
    errors = connector.validate(invalid)
    assert any("< и >" in error for error in errors)
    assert any("5000 байт" in error for error in errors)
    assert any("видимость YouTube" in error for error in errors)
    assert any("длина тегов" in error for error in errors)
