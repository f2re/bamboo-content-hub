from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import IntegrationAccount, OAuthState
from app.oauth import begin_oauth, consume_state, exchange_code, refresh_account, revoke_account
from app.security import CredentialCipher


def oauth_settings(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    get_settings.cache_clear()
    return get_settings()


def test_state_single_use_and_pkce(monkeypatch):
    settings = oauth_settings(monkeypatch)
    with SessionLocal() as db:
        url = begin_oauth(db, settings, "google")
        params = parse_qs(urlparse(url).query)
        assert params["code_challenge_method"] == ["S256"]
        state = params["state"][0]
        consume_state(db, settings, "google", state)
        with pytest.raises(ValueError):
            consume_state(db, settings, "google", state)


def test_expired_state(monkeypatch):
    settings = oauth_settings(monkeypatch)
    with SessionLocal() as db:
        url = begin_oauth(db, settings, "google")
        state = parse_qs(urlparse(url).query)["state"][0]
        row = db.scalar(select(OAuthState))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(ValueError):
            consume_state(db, settings, "google", state)


@pytest.mark.asyncio
async def test_exchange_and_refresh(monkeypatch):
    settings = oauth_settings(monkeypatch)
    calls = []

    async def handler(request):
        calls.append(request)
        if b"grant_type=refresh_token" in request.content:
            return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "access_token": "old",
                "refresh_token": "r1",
                "expires_in": 1,
                "scope": "x",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with SessionLocal() as db:
            url = begin_oauth(db, settings, "google")
            state = parse_qs(urlparse(url).query)["state"][0]
            account = await exchange_code(db, settings, "google", "code", state, client)
            assert account.status == "connected"
            await refresh_account(db, settings, account, client)
            assert account.status == "connected"
            assert len(calls) == 2


@pytest.mark.asyncio
async def test_oauth_reconnect_and_revoke_preserve_provider_configuration(monkeypatch):
    settings = oauth_settings(monkeypatch)

    async def handler(request):
        return httpx.Response(
            200,
            json={"access_token": "token", "refresh_token": "refresh", "expires_in": 3600},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with SessionLocal() as db:
            account = IntegrationAccount(provider="google", account_key="default", status="configured")
            account.encrypted_credentials = CredentialCipher(settings).encrypt_json(
                {"youtube_privacy_status": "unlisted", "youtube_category_id": "22"}
            )
            db.add(account)
            db.commit()

            url = begin_oauth(db, settings, "google")
            state = parse_qs(urlparse(url).query)["state"][0]
            account = await exchange_code(db, settings, "google", "code", state, client)
            credentials = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
            assert credentials["youtube_privacy_status"] == "unlisted"
            assert credentials["access_token"] == "token"

            await revoke_account(db, settings, "google", client)
            credentials = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
            assert credentials == {
                "youtube_privacy_status": "unlisted",
                "youtube_category_id": "22",
            }
            assert account.status == "configured"
