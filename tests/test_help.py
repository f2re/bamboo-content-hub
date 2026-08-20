from app.db import SessionLocal
from app.models import MediaAsset, Product


def test_help_covers_ai_and_connection_workflows(client):
    page = client.get("/static/help.html")
    assert page.status_code == 200
    assert "Открыл изделие → скопировал → вставил" in page.text
    assert "Ничего дописывать" in page.text
    assert "needs_confirmation" in page.text
    assert "TikTok" in page.text
    assert "Ярмарка мастеров" in page.text
    assert "Статического промпта для копирования нет специально" in page.text
    assert "Скопировать основу" not in page.text
    assert "Официальная ссылка → callback → подключить" in page.text
    assert "ID найдутся автоматически" in page.text
    assert 'href="/connections"' in page.text


def test_ai_page_exposes_ready_runtime_prompt_and_media_mapping(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        db.add(
            MediaAsset(
                product_id=product.id,
                original_filename="process.jpg",
                stored_filename="test-process.jpg",
                mime_type="image/jpeg",
                media_type="image",
                file_size=123,
                checksum="a" * 64,
                sort_order=0,
            )
        )
        db.commit()

    page = client.get(f"/products/{product_id}/ai")
    assert page.status_code == 200
    assert 'href="/static/help.html#ai-workflow"' in page.text
    assert "Полный рабочий запрос" in page.text
    assert "Скопировать готовый запрос" in page.text
    assert "Ничего дописывать или собирать вручную не нужно" in page.text
    assert "Обновить из карточки" in page.text
    assert "image_1" in page.text
    assert "process.jpg" in page.text
    assert "Правила подготовки контента:" in page.text
    assert "needs_confirmation[].value/proof/confirmed" in page.text
    assert "Instagram —" in page.text
    assert "TikTok —" in page.text
    assert "YouTube —" in page.text
    assert "Ярмарка мастеров —" in page.text
    assert "/static/ai-confirmation.js" in page.text
