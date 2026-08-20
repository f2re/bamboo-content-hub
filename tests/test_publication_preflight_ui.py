def test_product_page_loads_publication_preflight_and_manual_modes(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]

    page = client.get(f"/products/{product_id}")

    assert page.status_code == 200
    assert 'data-publish-form' in page.text
    assert 'data-manual-tiktok="true"' in page.text
    assert 'data-manual-youtube="true"' in page.text
    assert '/static/manual-mode-ui.js' in page.text
    assert '/static/publication-preflight.js' in page.text


def test_publication_preflight_script_is_served(client):
    response = client.get("/static/publication-preflight.js")

    assert response.status_code == 200
    assert "Готовность публикации" in response.text
    assert "/api/integrations/${channel}/health" in response.text
    assert "нужно выбрать ровно одно видео" in response.text
    assert "ручной экспорт" in response.text


def test_manual_mode_script_preserves_submit_contract(client):
    response = client.get("/static/manual-mode-ui.js")

    assert response.status_code == 200
    assert "data-tiktok-creator-checked" in response.text
    assert "data-tiktok-privacy" in response.text
    assert "tiktokConsent" in response.text
    assert "youtube_title" in response.text
    assert "serverMode" in response.text
