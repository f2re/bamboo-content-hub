def test_ai_help_is_available(client):
    page = client.get("/static/help.html")
    assert page.status_code == 200
    assert "Один запрос — отдельный текст для каждой площадки" in page.text
    assert "needs_confirmation" in page.text
    assert "TikTok" in page.text
    assert "Ярмарка мастеров" in page.text


def test_ai_page_links_to_help_and_exposes_platform_prompt(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]
    page = client.get(f"/products/{product_id}/ai")
    assert page.status_code == 200
    assert 'href="/static/help.html#ai-workflow"' in page.text
    assert "Instagram —" in page.text
    assert "TikTok —" in page.text
    assert "YouTube —" in page.text
    assert "Ярмарка мастеров —" in page.text
