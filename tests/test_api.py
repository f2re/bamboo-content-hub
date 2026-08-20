import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Product, Publication


def test_health(client):
    assert client.get("/health/ready").status_code == 200


def test_product_ai_publication_flow(client):
    response = client.post("/products", data={"name": "Туман"}, follow_redirects=False)
    assert response.status_code == 303
    product_id = response.headers["location"].split("/")[-1]
    page = client.get(f"/products/{product_id}/ai")
    assert page.status_code == 200
    import re

    request_id = re.search(r"BCP-[0-9]{8}-[A-F0-9]+", page.text).group(0)
    payload = {
        "schema_version": "bamboo-content-pack/1.0",
        "request_id": request_id,
        "product": {"price": {"amount": 3900, "currency": "RUB"}},
        "channels": {
            "telegram": {"text": "Новая чашка", "button_text": "", "button_url": ""}
        },
    }
    response = client.post(
        f"/api/products/{product_id}/ai/import",
        json={"text": json.dumps(payload, ensure_ascii=False)},
    )
    assert response.status_code == 200
    response = client.post(
        f"/products/{product_id}/publications",
        data={"channels": "demo", "action": "publish"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/publications").status_code == 200


def test_connection_settings_are_exposed_and_persisted(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert 'data-integration-form' in page.text
    assert 'name="board_id"' in page.text
    assert 'name="instagram_user_id"' in page.text

    response = client.post(
        "/api/integrations/pinterest/config",
        json={"board_id": "board-42", "board_section_id": "section-7"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "configured"
    assert response.json()["config"]["board_id"] == "board-42"

    response = client.post(
        "/api/integrations/telegram",
        json={"bot_token": "123:secret", "chat_id": "@bamboo"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert response.json()["config"]["bot_token"] == ""
    assert response.json()["config"]["bot_token_configured"] is True

    page = client.get("/connections")
    assert "board-42" in page.text
    assert "section-7" in page.text
    assert "Сохранено — оставьте пустым без изменений" in page.text

    rejected = client.post(
        "/api/integrations/pinterest/config",
        json={"unknown": "value"},
    )
    assert rejected.status_code == 422


def _create_product_with_video(client):
    response = client.post("/products", data={"name": "Видео Bamboo"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]
    mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
    response = client.post(
        f"/products/{product_id}/media",
        files={"files": ("clip.mp4", mp4, "video/mp4")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        publication_product = db.get(Product, product_id)
        media_id = publication_product.media[0].id
    return product_id, media_id


def test_publication_stores_explicit_tiktok_and_youtube_choices_in_automatic_mode(client):
    for provider in ("tiktok", "google"):
        response = client.post(
            f"/api/integrations/{provider}/config",
            json={"connection_mode": "automatic"},
        )
        assert response.status_code == 200

    product_id, media_id = _create_product_with_video(client)

    missing_consent = client.post(
        f"/products/{product_id}/publications",
        data={
            "channels": "tiktok",
            "media_ids": media_id,
            "tiktok_creator_checked": "true",
            "tiktok_privacy_level": "SELF_ONLY",
        },
    )
    assert missing_consent.status_code == 422

    response = client.post(
        f"/products/{product_id}/publications",
        data={
            "channels": ["tiktok", "youtube"],
            "media_ids": media_id,
            "action": "draft",
            "tiktok_creator_checked": "true",
            "tiktok_title": "Новая чашка",
            "tiktok_caption": "Ручная работа",
            "tiktok_privacy_level": "PUBLIC_TO_EVERYONE",
            "tiktok_commercial_content_toggle": "true",
            "tiktok_brand_organic_toggle": "true",
            "tiktok_is_aigc": "true",
            "tiktok_direct_post_consent": "true",
            "youtube_title": "Как мы делаем чашку",
            "youtube_description": "Процесс ручной работы",
            "youtube_privacy_status": "unlisted",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        publication = db.scalar(select(Publication))
        assert publication is not None
        tiktok = publication.channel_content["tiktok"]
        youtube = publication.channel_content["youtube"]
        assert tiktok["direct_post_consent"] is True
        assert tiktok["commercial_content_toggle"] is True
        assert tiktok["brand_organic_toggle"] is True
        assert tiktok["privacy_level"] == "PUBLIC_TO_EVERYONE"
        assert youtube["title"] == "Как мы делаем чашку"
        assert youtube["privacy_status"] == "unlisted"
        assert {delivery.channel for delivery in publication.deliveries} == {"tiktok", "youtube"}


def test_connection_health_endpoint_reports_manual_readiness_and_automatic_failure(client):
    manual = client.get("/api/integrations/tiktok/health")
    assert manual.status_code == 200
    manual_body = manual.json()
    assert manual_body["ok"] is True
    assert manual_body["channel"] == "tiktok"
    assert manual_body["capabilities"]["automatic"] is False
    assert manual_body["capabilities"]["videos"] is True

    response = client.post(
        "/api/integrations/tiktok/config",
        json={"connection_mode": "automatic"},
    )
    assert response.status_code == 200
    automatic = client.get("/api/integrations/tiktok/health")
    assert automatic.status_code == 200
    body = automatic.json()
    assert body["ok"] is False
    assert body["channel"] == "tiktok"
    assert body["capabilities"]["videos"] is True
