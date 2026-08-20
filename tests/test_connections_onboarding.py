from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.db import SessionLocal
from app.integrations.service import merge_provider_config, public_provider_config
from app.models import IntegrationAccount
from app.oauth import begin_oauth
from app.security import CredentialCipher


def test_connections_page_starts_without_developer_apps_and_keeps_api_advanced(client):
    page = client.get("/connections")
    assert page.status_code == 200
    assert "Начните без регистрации приложений" in page.text
    assert "Без n8n и cookies" in page.text
    assert "Готово без приложения" in page.text
    assert "Использовать без приложения" in page.text or "Уже используется" in page.text
    assert "Автоматически через официальный API — расширенный режим" in page.text
    assert "https://t.me/BotFather" in page.text
    assert "https://console.cloud.google.com/apis/credentials" in page.text
    assert "https://developers.pinterest.com/apps/" in page.text
    assert "https://developers.tiktok.com/" in page.text
    assert "https://developers.facebook.com/apps/" in page.text
    assert "Открыть документацию VK API" in page.text
    assert "Сначала сохраните Client ID и Secret" in page.text


def test_oauth_credentials_can_be_saved_in_encrypted_provider_config():
    settings = Settings(google_client_id=None, google_client_secret=None)

    with SessionLocal() as db:
        account = merge_provider_config(
            db,
            settings,
            "google",
            {
                "connection_mode": "automatic",
                "oauth_client_id": "ui-client",
                "oauth_client_secret": "ui-secret",
            },
        )
        stored = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
        assert stored["connection_mode"] == "automatic"
        assert stored["oauth_client_id"] == "ui-client"
        assert stored["oauth_client_secret"] == "ui-secret"

        public = public_provider_config(db, settings, "google")
        assert public["connection_mode"] == "automatic"
        assert public["oauth_client_id"] == "ui-client"
        assert public["oauth_client_secret"] == ""
        assert public["oauth_client_secret_configured"] is True
        assert public["oauth_ready"] is True

        url = begin_oauth(db, settings, "google")
        params = parse_qs(urlparse(url).query)
        assert params["client_id"] == ["ui-client"]
        assert params["code_challenge_method"] == ["S256"]


def test_changing_oauth_app_credentials_invalidates_old_tokens():
    settings = Settings(google_client_id=None, google_client_secret=None)
    with SessionLocal() as db:
        account = IntegrationAccount(provider="google", account_key="default", status="connected")
        account.encrypted_credentials = CredentialCipher(settings).encrypt_json(
            {
                "connection_mode": "automatic",
                "oauth_client_id": "old-client",
                "oauth_client_secret": "old-secret",
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "youtube_category_id": "22",
            }
        )
        db.add(account)
        db.commit()

        account = merge_provider_config(
            db,
            settings,
            "google",
            {"oauth_client_id": "new-client", "oauth_client_secret": "new-secret"},
        )
        stored = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
        assert stored["connection_mode"] == "automatic"
        assert stored["oauth_client_id"] == "new-client"
        assert stored["oauth_client_secret"] == "new-secret"
        assert stored["youtube_category_id"] == "22"
        assert "access_token" not in stored
        assert "refresh_token" not in stored
        assert account.status == "configured"
