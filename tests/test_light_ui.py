def test_application_uses_light_design_layer(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert 'content="light"' in page.text
    assert 'href="/static/apple-ui.css?v=' in page.text
    assert 'href="/static/manual-mode.css?v=' in page.text
    assert '/static/connections-enhance.js?v=' in page.text
    assert 'aria-current="page"' in page.text


def test_connections_are_progressive_manual_first_and_not_four_dense_columns(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert "Начните без регистрации приложений" in page.text
    assert page.text.count('class="connection-panel"') == 6
    assert page.text.count('class="connection-disclosure" name="connection-setup"') == 6
    assert "Указать ID вручную" in page.text
    assert "Выберите площадку" in page.text
    assert "Автоматически через официальный API — расширенный режим" in page.text

    css = client.get("/static/apple-ui.css")
    assert css.status_code == 200
    assert "color-scheme: light" in css.text
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css.text
    assert "@media (max-width: 1180px)" in css.text
    assert ".connections-list" in css.text

    manual_css = client.get("/static/manual-mode.css")
    assert manual_css.status_code == 200
    assert ".manual-package-grid" in manual_css.text
    assert ".api-mode-details" in manual_css.text
    assert ".browser-assistant-card" in manual_css.text

    enhancement = client.get("/static/connections-enhance.js")
    assert enhancement.status_code == 200
    assert "document.createElement('article')" in enhancement.text
    assert "livemaster" in enhancement.text
    assert "Нужно только для автоматического API-режима" in enhancement.text
