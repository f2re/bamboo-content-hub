def test_application_uses_light_design_layer(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert 'content="light"' in page.text
    assert 'href="/static/apple-ui.css"' in page.text
    assert 'aria-current="page"' in page.text


def test_connections_are_progressive_and_not_four_dense_columns(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert "Подключите площадки один раз" in page.text
    assert page.text.count('class="connection-panel"') == 6
    assert page.text.count('class="connection-disclosure" name="connection-setup"') == 6
    assert "Указать ID вручную" in page.text
    assert "Подключение за 2–3 шага" in page.text

    css = client.get("/static/apple-ui.css")
    assert css.status_code == 200
    assert "color-scheme: light" in css.text
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css.text
    assert "@media (max-width: 1180px)" in css.text
    assert ".connections-list" in css.text
