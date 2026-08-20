def test_ai_help_is_available(client):
    page = client.get("/static/help.html")
    assert page.status_code == 200
    assert "Открыл изделие → скопировал → вставил" in page.text
    assert "Ничего дописывать" in page.text
    assert "needs_confirmation" in page.text
    assert "TikTok" in page.text
    assert "Ярмарка мастеров" in page.text
    assert "Статического промпта для копирования нет специально" in page.text
    assert "Скопировать основу" not in page.text


def test_ai_page_exposes_ready_runtime_prompt_and_media_mapping(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]
    mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
    upload = client.post(
        f"/products/{product_id}/media",
        files={"files": ("process.mp4", mp4, "video/mp4")},
        follow_redirects=False,
    )
    assert upload.status_code == 303

    page = client.get(f"/products/{product_id}/ai")
    assert page.status_code == 200
    assert 'href="/static/help.html#ai-workflow"' in page.text
    assert "Полный рабочий запрос" in page.text
    assert "Скопировать готовый запрос" in page.text
    assert "Ничего дописывать или собирать вручную не нужно" in page.text
    assert "Обновить из карточки" in page.text
    assert "image_1" in page.text
    assert "process.mp4" in page.text
    assert "Контракт ответа:" in page.text
    assert "Instagram —" in page.text
    assert "TikTok —" in page.text
    assert "YouTube —" in page.text
    assert "Ярмарка мастеров —" in page.text
