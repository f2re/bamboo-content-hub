from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.security import (
    create_session_token,
    detect_media_mime,
    hash_admin_password,
    verify_admin_password,
    verify_session_token,
)
from app.web_security import SESSION_COOKIE, SecurityMiddleware


def secure_settings(tmp_path):
    password_hash = hash_admin_password("correct horse battery staple")
    settings = Settings(
        _env_file=None,
        app_base_url="http://localhost",
        app_timezone="Europe/Helsinki",
        database_url=f"sqlite:///{tmp_path / 'security.db'}",
        data_dir=tmp_path,
        media_dir=tmp_path / "media",
        secret_key="s" * 48,
        master_key="m" * 48,
        trusted_lan=False,
        admin_password_hash=password_hash,
        scheduler_enabled=False,
    )
    settings.validate_runtime_security()
    settings.ensure_dirs()
    return settings


def test_password_and_signed_session_roundtrip(tmp_path):
    settings = secure_settings(tmp_path)
    assert verify_admin_password(settings.admin_password_hash, "correct horse battery staple")
    assert not verify_admin_password(settings.admin_password_hash, "wrong password")
    token, csrf = create_session_token(settings)
    payload = verify_session_token(settings, token)
    assert payload is not None
    assert payload["csrf"] == csrf
    assert verify_session_token(settings, token + "x") is None


def test_public_mode_fails_closed_without_required_secrets(tmp_path):
    settings = Settings(
        _env_file=None,
        app_base_url="http://localhost",
        data_dir=tmp_path,
        media_dir=tmp_path / "media",
        secret_key="x" * 16,
        trusted_lan=False,
    )
    try:
        settings.validate_runtime_security()
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("unsafe public configuration must fail")
    assert "SECRET_KEY" in message
    assert "MASTER_KEY" in message
    assert "ADMIN_PASSWORD_HASH" in message


def test_middleware_requires_session_and_csrf(tmp_path):
    settings = secure_settings(tmp_path)
    test_app = FastAPI()
    test_app.add_middleware(SecurityMiddleware, settings=settings)

    @test_app.get("/protected")
    def protected_get():
        return {"ok": True}

    @test_app.post("/protected")
    def protected_post():
        return {"ok": True}

    client = TestClient(test_app, base_url="http://localhost")
    response = client.get("/protected", headers={"accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")

    token, csrf = create_session_token(settings)
    client.cookies.set(SESSION_COOKIE, token)
    response = client.get("/protected")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    assert client.post("/protected").status_code == 403
    assert client.post("/protected", headers={"x-csrf-token": csrf}).status_code == 200
    assert client.post("/protected", headers={"origin": "http://localhost"}).status_code == 200
    assert client.post("/protected", headers={"origin": "https://evil.example"}).status_code == 403


def test_media_signature_allowlist_rejects_active_content():
    assert detect_media_mime(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") is None
    assert detect_media_mime(b"<html><script>alert(1)</script></html>") is None
    assert detect_media_mime(b"\x89PNG\r\n\x1a\n" + b"x" * 32) == "image/png"
    assert detect_media_mime(b"\xff\xd8\xff" + b"x" * 32) == "image/jpeg"
    assert detect_media_mime(b"\x00\x00\x00\x18ftypmp42" + b"x" * 32) == "video/mp4"
