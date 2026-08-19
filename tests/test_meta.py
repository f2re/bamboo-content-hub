import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.integrations.base import MediaInput, PublishRequest
from app.integrations.meta import FacebookConnector, InstagramConnector
from app.integrations.registry import CONNECTORS


def image(url="https://hub.example/media/public/image"):
    return MediaInput(
        asset_id="img1",
        path="/tmp/image.jpg",
        mime_type="image/jpeg",
        public_url=url,
        alt_text="Чашка",
    )


def video(url="https://hub.example/media/public/video"):
    return MediaInput(
        asset_id="vid1",
        path="/tmp/video.mp4",
        mime_type="video/mp4",
        public_url=url,
    )


def config():
    return {
        "access_token": "user-token",
        "facebook_page_id": "page-1",
        "instagram_user_id": "ig-1",
    }


def ig_request(media):
    return PublishRequest(
        text="Новая чашка",
        media=tuple(media),
        config=config(),
        content={"caption": "Новая чашка"},
        idempotency_key="ig-key",
    )


def fb_request(media=(), text="Пост"):
    return PublishRequest(
        text=text,
        media=tuple(media),
        config=config(),
        content={"text": text},
        idempotency_key="fb-key",
    )


def page_response():
    return {
        "id": "page-1",
        "name": "Bamboo",
        "access_token": "page-token",
        "instagram_business_account": {"id": "ig-1"},
    }


def test_registry_discovers_meta_channels():
    assert "instagram" in CONNECTORS
    assert "facebook" in CONNECTORS


def test_meta_rejects_non_public_media_url():
    request = ig_request((image("http://localhost:8080/media/public/x"),))
    errors = InstagramConnector().validate(request)
    assert any("публичному HTTPS URL" in error for error in errors)


@pytest.mark.asyncio
async def test_instagram_image_container_then_publish_status():
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/page-1"):
            assert request.headers["authorization"] == "Bearer user-token"
            return httpx.Response(200, json=page_response())
        if path.endswith("/ig-1/media") and request.method == "POST":
            data = parse_qs((await request.aread()).decode())
            assert data["image_url"] == ["https://hub.example/media/public/image"]
            assert data["caption"] == ["Новая чашка"]
            assert request.headers["authorization"] == "Bearer page-token"
            return httpx.Response(200, json={"id": "container-1"})
        if path.endswith("/container-1"):
            return httpx.Response(200, json={"id": "container-1", "status_code": "FINISHED", "status": "Ready"})
        if path.endswith("/ig-1/media_publish"):
            data = parse_qs((await request.aread()).decode())
            assert data["creation_id"] == ["container-1"]
            return httpx.Response(200, json={"id": "media-9"})
        if path.endswith("/media-9"):
            return httpx.Response(200, json={"id": "media-9", "permalink": "https://instagram.com/p/abc/"})
        raise AssertionError(f"unexpected {request.method} {path}")

    connector = InstagramConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(ig_request((image(),)), client)
        assert result.processing is True
        assert result.external_post_id == "container-1"
        status = await connector.status(ig_request((image(),)), "container-1", client)
    assert status.state == "published"
    assert status.external_url == "https://instagram.com/p/abc/"
    assert ("POST", "/v23.0/ig-1/media_publish") in calls


@pytest.mark.asyncio
async def test_instagram_reel_uses_video_container():
    captured = {}

    async def handler(request):
        if request.url.path.endswith("/page-1"):
            return httpx.Response(200, json=page_response())
        if request.url.path.endswith("/ig-1/media"):
            captured.update(parse_qs((await request.aread()).decode()))
            return httpx.Response(200, json={"id": "reel-container"})
        raise AssertionError(request.url.path)

    connector = InstagramConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(ig_request((video(),)), client)
    assert result.processing is True
    assert captured["media_type"] == ["REELS"]
    assert captured["video_url"] == ["https://hub.example/media/public/video"]
    assert captured["share_to_feed"] == ["true"]


@pytest.mark.asyncio
async def test_instagram_image_carousel_creates_children_and_parent():
    children = []
    parent_data = {}

    async def handler(request):
        if request.url.path.endswith("/page-1"):
            return httpx.Response(200, json=page_response())
        if request.url.path.endswith("/ig-1/media"):
            data = parse_qs((await request.aread()).decode())
            if data.get("media_type") == ["CAROUSEL"]:
                parent_data.update(data)
                return httpx.Response(200, json={"id": "parent-1"})
            children.append(data)
            return httpx.Response(200, json={"id": f"child-{len(children)}"})
        raise AssertionError(request.url.path)

    connector = InstagramConnector()
    request = ig_request(
        (
            image("https://hub.example/media/public/a"),
            image("https://hub.example/media/public/b"),
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(request, client)
    assert result.external_post_id == "parent-1"
    assert len(children) == 2
    assert all(row["is_carousel_item"] == ["true"] for row in children)
    assert parent_data["children"] == ["child-1,child-2"]


@pytest.mark.asyncio
async def test_facebook_multi_image_page_post():
    photo_count = 0
    feed = {}

    async def handler(request):
        nonlocal photo_count
        path = request.url.path
        if path.endswith("/page-1") and request.method == "GET":
            return httpx.Response(200, json=page_response())
        if path.endswith("/page-1/photos"):
            data = parse_qs((await request.aread()).decode())
            photo_count += 1
            assert data["published"] == ["false"]
            return httpx.Response(200, json={"id": f"photo-{photo_count}"})
        if path.endswith("/page-1/feed"):
            feed.update(parse_qs((await request.aread()).decode()))
            return httpx.Response(200, json={"id": "page-1_777"})
        raise AssertionError(f"unexpected {request.method} {path}")

    request = fb_request(
        (
            image("https://hub.example/media/public/a"),
            image("https://hub.example/media/public/b"),
        )
    )
    connector = FacebookConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.publish(request, client)
    assert photo_count == 2
    assert json.loads(feed["attached_media[0]"][0]) == {"media_fbid": "photo-1"}
    assert json.loads(feed["attached_media[1]"][0]) == {"media_fbid": "photo-2"}
    assert result.external_post_id == "page-1_777"
    assert result.external_url.endswith("/page-1/posts/777")


@pytest.mark.asyncio
async def test_meta_health_resolves_page_token_and_instagram_account():
    async def handler(request):
        if request.url.path.endswith("/page-1"):
            return httpx.Response(200, json=page_response())
        if request.url.path.endswith("/ig-1"):
            return httpx.Response(200, json={"id": "ig-1", "username": "bamboopottery"})
        raise AssertionError(request.url.path)

    connector = InstagramConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await connector.health(ig_request((image(),)), client)
    assert health.ok is True
    assert health.details["username"] == "bamboopottery"
