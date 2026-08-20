def test_product_page_loads_publication_preflight(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]

    page = client.get(f"/products/{product_id}")

    assert page.status_code == 200
    assert 'data-publish-form' in page.text
    assert '/static/publication-preflight.js' in page.text


def test_publication_preflight_script_is_served(client):
    response = client.get("/static/publication-preflight.js")

    assert response.status_code == 200
    assert "Готовность публикации" in response.text
    assert "/api/integrations/${channel}/health" in response.text
    assert "нужно выбрать ровно одно видео" in response.text
