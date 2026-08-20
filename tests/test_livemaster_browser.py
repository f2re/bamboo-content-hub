import io
import json
import zipfile

from app.db import SessionLocal
from app.models import Delivery, Product, Publication


def test_livemaster_package_supports_browser_login_and_autofill(client):
    created = client.post(
        "/products",
        data={"name": "Чаша Лес"},
        follow_redirects=False,
    )
    product_id = created.headers["location"].split("/")[-1]

    with SessionLocal() as db:
        product = db.get(Product, product_id)
        product.description = "Авторская керамическая чаша с природной фактурой."
        product.facts = {
            "price": {"amount": 4200, "currency": "RUB"},
            "materials": ["каменная масса", "глазурь"],
            "dimensions": {"height_mm": 90, "diameter_mm": 140},
            "availability": "В наличии",
        }
        product.channel_content = {
            "livemaster": {
                "title": "Керамическая чаша Лес",
                "short_description": "Чаша ручной работы в природных оттенках.",
                "description": "Авторская керамическая чаша с природной фактурой.",
                "keywords": ["керамика", "чаша", "ручная работа"],
            }
        }
        db.commit()

    response = client.post(
        f"/products/{product_id}/publications",
        data={"channels": "livemaster", "action": "publish"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        publication = db.query(Publication).one()
        delivery = db.query(Delivery).one()
        publication_id = publication.id
        delivery_id = delivery.id

    assert client.post(f"/api/publications/{publication_id}/publish").status_code == 200

    page = client.get(f"/publications/{publication_id}/manual/{delivery_id}")
    assert page.status_code == 200
    assert "Авторизация в вашем браузере" in page.text
    assert "Bamboo → заполнить Ярмарку" in page.text
    assert "Скопировать данные для помощника" in page.text
    assert "bamboo-browser-fill/1" in page.text
    assert "Керамическая чаша Лес" in page.text
    assert "каменная масса, глазурь" in page.text
    assert "высота 90 мм, диаметр 140 мм" in page.text
    assert "Фото загрузите из ZIP вручную" in page.text
    assert "/static/livemaster-assistant.js?v=" in page.text

    archive_response = client.get(
        f"/publications/{publication_id}/manual/{delivery_id}/package.zip"
    )
    assert archive_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        assert "publication.txt" in archive.namelist()
        assert "browser-fill.json" in archive.namelist()
        payload = json.loads(archive.read("browser-fill.json"))
        assert payload["schema"] == "bamboo-browser-fill/1"
        assert payload["platform"] == "livemaster"
        assert payload["price"] == 4200
        assert payload["keywords"] == "керамика, чаша, ручная работа"


def test_browser_helper_does_not_read_cookies_or_call_private_endpoints(client):
    script = client.get("/static/livemaster-assistant.js")
    assert script.status_code == 200
    assert "navigator.clipboard.readText" in script.text
    assert "document.cookie" not in script.text
    assert "XMLHttpRequest" not in script.text
    assert "fetch(" not in script.text
    assert "не перезаписано" in script.text


def test_connections_explain_api_requirements_and_browser_mode(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert "/static/connections-enhance.js?v=" in page.text

    script = client.get("/static/connections-enhance.js")
    assert script.status_code == 200
    assert "Ярмарка мастеров" in script.text
    assert "business account" in script.text
    assert "Professional account" in script.text
    assert "developer app" in script.text
    assert "Режим «Без приложения»" in script.text
