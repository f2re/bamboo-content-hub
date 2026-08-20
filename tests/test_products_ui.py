def test_product_creation_is_csp_safe_and_has_no_js_fallback(client):
    page = client.get("/products")
    assert page.status_code == 200
    assert 'href="/new-product"' in page.text
    assert 'data-dialog-open="#new-product"' in page.text
    assert "onclick=" not in page.text
    assert "showModal()" not in page.text
    assert "/static/dialogs.js?v=" in page.text
    assert "'unsafe-inline'" not in page.headers["content-security-policy"]

    fallback = client.get("/new-product")
    assert fallback.status_code == 200
    assert 'action="/products"' in fallback.text
    assert 'name="name"' in fallback.text
    assert "Создать изделие" in fallback.text

    created = client.post(
        "/products",
        data={"name": "Чашка Туман"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"].startswith("/products/")


def test_visible_build_marker_and_version_endpoint(client):
    page = client.get("/products")
    assert 'content="0.3.0"' in page.text
    assert "v0.3.0 · без приложений" in page.text
    assert "manual-first-browser-assist" in page.text

    version = client.get("/health/version")
    assert version.status_code == 200
    assert version.json()["version"] == "0.3.0"
    assert version.json()["feature_marker"] == "manual-first-browser-assist"
