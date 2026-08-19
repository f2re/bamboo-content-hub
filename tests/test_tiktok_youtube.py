import json
from pathlib import Path

import httpx
import pytest

from app.integrations.base import MediaInput, PublishRequest
from app.integrations.registry import CONNECTORS
from app.integrations.tiktok import TikTokConnector, _utf16_units, _video_chunk_plan
from app.integrations.youtube import YouTubeConnector


def video(path: Path, mime="video/mp4") -> MediaInput:
    return MediaInput(
        asset_id="video-1",
        path=str(path),
        mime_type=mime,
        public_url="https://hub.example/media/public/video",
    )


def image(url: str = "https://hub.example/media/public/photo") -> MediaInput:
    return MediaInput(
        asset_id="image-1",
        path="/tmp/photo.jpg",
        mime_type="image/jpeg",
        public_url=url,
    )


def tiktok_request(media, text="Caption"):
    return PublishRequest(
        text=text,
        media=tuple(media),
        config={
            "access_token": "tt-token",
            "privacy_level": "SELF_ONLY",
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
        },
        content={"title": "Фото", "caption": text},
        idempotency_key="tt-key",
    )


def youtube_request(path: Path):
    return PublishRequest(
        text="Fallback title",
        media=(video(path),),
        config={
            "access_token": "yt-token",
            "youtube_privacy_status": "unlisted",
            "youtube_category_id": "22",
        },
        content={"title": "Bamboo cup", "description": "Making a cup", "tags": ["ceramics", "bamboo"]},
        idempotency_key="yt-key",
    )


def creator_info():
    return {
        "creator_username": "bamboo",
        "creator_nickname": "Bamboo",
        "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
        "comment_disabled": False,
        "duet_disabled": False,
        "stitch_disabled": True,
        "max_video_post_duration_sec": 300,
    }


def tiktok_response(data):
    return {"data": data, "error": {"code": "ok", "message": "", "log_id": "1"}}


def test_registry_discovers_tiktok_and_youtube():
    assert "tiktok" in CONNECTORS
    assert "youtube" in CONNECTORS


def test_tiktok_utf16_and_chunk_plan():
    assert _utf16_units("a") == 1
    assert _utf16_units("😀") == 2
    assert _video_chunk_plan(4 * 1024 * 1024) == (4 * 1024 * 1024, 1)
    assert _video_chunk_plan(40 * 1024 * 1024) == (40 * 1024 * 1024, 1)
    chunk, count = _video_chunk_plan(100 * 1024 * 1024)
    assert chunk == 32 * 1024 * 1024
    assert count == 3


@pytest.mark.asyncio
async def test_tiktok_video_direct_post_upload_and_status(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"123456")
    init_payload = {}
    upload_headers = {}

    async def handler(request):
        if request.url.path == "/v2/post/publish/creator_info/query/":
            return httpx.Response(200, json=tiktok_response(creator_info()))
        if request.url.path == "/v2/post/publish/video/init/":
            init_payload.update(json.loads((await request.aread()).decode()))
            return httpx.Response(
                200,
                json=tiktok_response(
                    {"publish_id": "pub-1", "upload_url": "https://upload.tiktok.test/video"}
                ),
            )
        if request.url.host == "upload.tiktok.test":
            upload_headers.update(request.headers)
            assert await request.aread() == b"123456"
            return httpx.Response(201)
        if request.url.path == "/v2/post/publish/status/fetch/":
            payload = json.loads((await request.aread()).decode())
            assert payload == {"publish_id": "pub-1"}
            return httpx.Response(
                200,
                json=tiktok_response(
                    {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["777"]}
                ),
            )
        raise AssertionError(f"unexpected {request.method} {request.url}")

    connector = TikTokConnector()
    request = tiktok_request((video(clip),))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(request, client)
        status = await connector.status(request, "pub-1", client)
    assert result.processing is True
    assert result.external_post_id == "pub-1"
    assert init_payload["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init_payload["post_info"]["disable_stitch"] is True
    assert init_payload["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": 6,
        "chunk_size": 6,
        "total_chunk_count": 1,
    }
    assert upload_headers["content-range"] == "bytes 0-5/6"
    assert status.state == "published"
    assert "777" in status.message


@pytest.mark.asyncio
async def test_tiktok_photo_direct_post_uses_pull_urls():
    captured = {}

    async def handler(request):
        if request.url.path == "/v2/post/publish/creator_info/query/":
            return httpx.Response(200, json=tiktok_response(creator_info()))
        if request.url.path == "/v2/post/publish/content/init/":
            captured.update(json.loads((await request.aread()).decode()))
            return httpx.Response(200, json=tiktok_response({"publish_id": "photo-pub"}))
        raise AssertionError(request.url.path)

    request = tiktok_request(
        (
            image("https://hub.example/media/public/a"),
            image("https://hub.example/media/public/b"),
        ),
        text="Фото чашки",
    )
    connector = TikTokConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(request, client)
    assert result.processing is True
    assert captured["media_type"] == "PHOTO"
    assert captured["post_mode"] == "DIRECT_POST"
    assert captured["source_info"]["source"] == "PULL_FROM_URL"
    assert len(captured["source_info"]["photo_images"]) == 2


def test_tiktok_requires_explicit_current_privacy_and_public_photo_url():
    request = PublishRequest(
        text="photo",
        media=(image("http://localhost/photo.jpg"),),
        config={"access_token": "tt-token", "privacy_level": ""},
        content={},
    )
    errors = TikTokConnector().validate(request)
    assert any("privacy_level" in error for error in errors)
    assert any("публичному HTTPS" in error for error in errors)


@pytest.mark.asyncio
async def test_youtube_resumable_upload_and_processing_status(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"youtube-video")
    metadata = {}
    upload = {}
    status_calls = 0

    async def handler(request):
        nonlocal status_calls
        if request.url.path == "/upload/youtube/v3/videos" and request.method == "POST":
            metadata.update(json.loads((await request.aread()).decode()))
            assert request.url.params["uploadType"] == "resumable"
            assert request.headers["x-upload-content-length"] == str(len(b"youtube-video"))
            return httpx.Response(200, headers={"Location": "https://upload.youtube.test/session"})
        if request.url.host == "upload.youtube.test":
            upload["body"] = await request.aread()
            upload["content_type"] = request.headers["content-type"]
            return httpx.Response(200, json={"id": "yt-123"})
        if request.url.path == "/youtube/v3/videos":
            status_calls += 1
            if status_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": "yt-123",
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
                            "id": "yt-123",
                            "status": {"uploadStatus": "processed"},
                            "processingDetails": {"processingStatus": "succeeded"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected {request.method} {request.url}")

    connector = YouTubeConnector()
    request = youtube_request(clip)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(request, client)
        processing = await connector.status(request, "yt-123", client)
        complete = await connector.status(request, "yt-123", client)
    assert result.processing is True
    assert result.external_post_id == "yt-123"
    assert metadata["snippet"]["title"] == "Bamboo cup"
    assert metadata["snippet"]["tags"] == ["ceramics", "bamboo"]
    assert metadata["status"]["privacyStatus"] == "unlisted"
    assert upload["body"] == b"youtube-video"
    assert upload["content_type"] == "video/mp4"
    assert processing.state == "processing"
    assert complete.state == "published"
    assert complete.external_url.endswith("watch?v=yt-123")


@pytest.mark.asyncio
async def test_youtube_health_reads_owned_channel():
    async def handler(request):
        assert request.url.path == "/youtube/v3/channels"
        assert request.url.params["mine"] == "true"
        return httpx.Response(
            200,
            json={"items": [{"id": "channel-1", "snippet": {"title": "Bamboo Pottery"}}]},
        )

    connector = YouTubeConnector()
    request = PublishRequest("x", (), {"access_token": "yt-token"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await connector.health(request, client)
    assert health.ok is True
    assert health.details == {"channel_id": "channel-1", "title": "Bamboo Pottery"}
