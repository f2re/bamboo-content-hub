import io

from PIL import Image

from app.config import get_settings
from app.db import SessionLocal
from app.models import MediaAsset, Product


def _new_product(client, name="Чашка Туман"):
    response = client.post("/products", data={"name": name}, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"].split("/")[-1]


def test_product_editor_persists_facts_and_channel_copy(client):
    product_id = _new_product(client)
    response = client.post(
        f"/products/{product_id}",
        data={
            "name": "Чашка Туман",
            "product_type": "Чашка",
            "sku": "CUP-001",
            "collection": "Туман",
            "description": "Ручная керамическая чашка",
            "price_amount": "3200,50",
            "price_currency": "rub",
            "materials": "каменная масса, глазурь",
            "techniques": "гончарный круг, ручная роспись",
            "height_mm": "92",
            "diameter_mm": "88",
            "volume_ml": "420",
            "weight_g": "360",
            "dishwasher": "yes",
            "microwave": "no",
            "food_safe": "yes",
            "availability": "В наличии",
            "instagram_caption": "Тихая чашка для утреннего кофе",
            "instagram_hashtags": "#керамика, ручнаяработа",
            "telegram_text": "Новая чашка из коллекции Туман",
            "youtube_title": "Как появилась чашка Туман",
            "youtube_tags": "керамика, мастерская",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?saved=1")

    with SessionLocal() as db:
        product = db.get(Product, product_id)
        assert product.sku == "CUP-001"
        assert product.facts["price"] == {"amount": 3200.5, "currency": "RUB"}
        assert product.facts["dimensions"]["volume_ml"] == 420.0
        assert product.facts["care"] == {
            "dishwasher": True,
            "microwave": False,
            "food_safe": True,
        }
        assert product.channel_content["instagram"]["hashtags"] == ["керамика", "ручнаяработа"]
        assert product.channel_content["telegram"]["text"].startswith("Новая чашка")
        assert product.channel_content["youtube"]["tags"] == ["керамика", "мастерская"]

    page = client.get(f"/products/{product_id}")
    assert page.status_code == 200
    assert "Сохранить изделие и тексты" in page.text
    assert "Тихая чашка для утреннего кофе" in page.text


def test_image_upload_is_normalized_and_media_can_be_reordered_and_deleted(client):
    product_id = _new_product(client)
    image = Image.new("RGB", (3200, 2400), "white")
    source = io.BytesIO()
    image.save(source, format="PNG")

    response = client.post(
        f"/products/{product_id}/media",
        files={"files": ("iphone-export.png", source.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
    response = client.post(
        f"/products/{product_id}/media",
        files={"files": ("clip.mp4", mp4, "video/mp4")},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        product = db.get(Product, product_id)
        ordered = sorted(product.media, key=lambda item: item.sort_order)
        assert ordered[0].mime_type == "image/jpeg"
        settings = get_settings()
        stored = settings.media_dir / ordered[0].stored_filename
        with Image.open(stored) as optimized:
            assert max(optimized.size) <= 2560
        first_id, second_id = ordered[0].id, ordered[1].id

    response = client.post(
        f"/api/products/{product_id}/media/order",
        json={"ids": [second_id, first_id]},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        ordered = sorted(product.media, key=lambda item: item.sort_order)
        assert [item.id for item in ordered] == [second_id, first_id]

    response = client.delete(f"/api/products/{product_id}/media/{second_id}")
    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(MediaAsset, second_id) is None
        product = db.get(Product, product_id)
        assert len(product.media) == 1


def test_heic_signature_is_accepted_by_media_detector():
    from app.security import detect_media_mime

    assert detect_media_mime(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16) == "image/heic"
