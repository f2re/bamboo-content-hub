import io
import zipfile

import pytest

from app.config import Settings
from app.db import SessionLocal
from app.integrations.service import (
    channel_health,
    merge_provider_config,
    provider_connection_mode,
    public_provider_config,
)
from app.models import Delivery, DeliveryStatus, MediaAsset, Product, Publication, PublicationStatus


def _new_product(client, name="Чашка Туман"):
    response = client.post("/products", data={"name": name}, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"].split("/")[-1]


@pytest.mark.asyncio
async def test_complex_channels_default_to_ready_manual_mode():
    settings = Settings(
        google_client_id=None,
        google_client_secret=None,
        vk_client_id=None,
        vk_client_secret=None,
    )
    with SessionLocal() as db:
        assert provider_connection_mode(db, settings, "vk") == "manual"
        assert public_provider_config(db, settings, "vk")["connection_mode"] == "manual"
        health = await channel_health(db, settings, "vk")
        assert health["ok"] is True
        assert health["details"]["connection_mode"] == "manual"
        assert health["capabilities"]["automatic"] is False
        assert health["capabilities"]["images"] is True


def test_manual_mode_can_replace_automatic_without_deleting_oauth_credentials():
    settings = Settings(google_client_id=None, google_client_secret=None)
    with SessionLocal() as db:
        account = merge_provider_config(
            db,
            settings,
            "google",
            {
                "connection_mode": "automatic",
                "oauth_client_id": "client",
                "oauth_client_secret": "secret",
            },
        )
        assert account.status == "configured"
        account = merge_provider_config(db, settings, "google", {"connection_mode": "manual"})
        assert account.status == "connected"
        public = public_provider_config(db, settings, "google")
        assert public["connection_mode"] == "manual"
        assert public["oauth_client_id"] == "client"
        assert public["oauth_client_secret_configured"] is True


def test_vk_manual_publication_builds_package_and_can_be_completed(client):
    product_id = _new_product(client)
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        product.channel_content = {
            "vk": {
                "text": "Новая чашка из коллекции Туман",
                "hashtags": ["керамика", "bamboopottery"],
            }
        }
        db.commit()

    response = client.post(
        f"/products/{product_id}/publications",
        data={"channels": "vk", "action": "publish"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        publication = db.query(Publication).one()
        publication_id = publication.id
        delivery = db.query(Delivery).one()
        delivery_id = delivery.id

    response = client.post(f"/api/publications/{publication_id}/publish")
    assert response.status_code == 200

    with SessionLocal() as db:
        publication = db.get(Publication, publication_id)
        delivery = db.get(Delivery, delivery_id)
        assert publication.status == PublicationStatus.awaiting_manual.value
        assert delivery.status == DeliveryStatus.manual_action.value
        assert delivery.external_url.endswith(f"/manual/{delivery.id}")

    page = client.get(f"/publications/{publication_id}/manual/{delivery_id}")
    assert page.status_code == 200
    assert "Скопировать текст" in page.text
    assert "Новая чашка из коллекции Туман" in page.text
    assert "Скачать всё одним ZIP" in page.text

    archive_response = client.get(
        f"/publications/{publication_id}/manual/{delivery_id}/package.zip"
    )
    assert archive_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        assert archive.namelist() == ["publication.txt"]
        text = archive.read("publication.txt").decode("utf-8")
        assert "#керамика" in text
        assert "#bamboopottery" in text

    complete = client.post(
        f"/publications/{publication_id}/manual/{delivery_id}/complete",
        data={"published_url": "https://vk.com/wall-1_2"},
        follow_redirects=False,
    )
    assert complete.status_code == 303

    with SessionLocal() as db:
        publication = db.get(Publication, publication_id)
        delivery = db.get(Delivery, delivery_id)
        assert publication.status == PublicationStatus.completed.value
        assert delivery.status == DeliveryStatus.published.value
        assert delivery.external_url == "https://vk.com/wall-1_2"


def test_youtube_manual_mode_does_not_require_api_privacy_field(client):
    product_id = _new_product(client, "Видео о чашке")
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        asset = MediaAsset(
            product_id=product.id,
            original_filename="process.mp4",
            stored_filename="manual-test-process.mp4",
            mime_type="video/mp4",
            media_type="video",
            file_size=100,
            checksum="f" * 64,
            sort_order=0,
        )
        db.add(asset)
        product.channel_content = {
            "youtube": {
                "title": "Как появилась чашка Туман",
                "description": "Короткий рассказ о процессе.",
                "tags": ["керамика"],
            }
        }
        db.commit()
        asset_id = asset.id

    response = client.post(
        f"/products/{product_id}/publications",
        data={
            "channels": "youtube",
            "media_ids": asset_id,
            "action": "draft",
            "youtube_title": "Как появилась чашка Туман",
            "youtube_description": "Короткий рассказ о процессе.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        publication = db.query(Publication).one()
        assert publication.channel_content["youtube"]["title"] == "Как появилась чашка Туман"
        assert "privacy_status" not in publication.channel_content["youtube"]
