import httpx
import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.integrations.service import (
    channel_health,
    merge_provider_config,
    provider_config_fields,
)
from app.models import IntegrationAccount
from app.security import CredentialCipher


def _oauth_account(provider: str, credentials: dict):
    settings = get_settings()
    with SessionLocal() as db:
        account = IntegrationAccount(
            provider=provider,
            account_key="default",
            status="connected",
            encrypted_credentials=CredentialCipher(settings).encrypt_json(credentials),
        )
        db.add(account)
        db.commit()


@pytest.mark.asyncio
async def test_meta_health_offers_page_picker_and_discovers_instagram():
    _oauth_account("meta", {"access_token": "meta-token"})

    async def handler(request):
        assert request.url.path == "/v23.0/me/accounts"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "page-1",
                        "name": "Bamboo Pottery",
                        "instagram_business_account": {"id": "ig-1", "username": "bamboo"},
                    },
                    {"id": "page-2", "name": "Без Instagram"},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client, SessionLocal() as db:
        result = await channel_health(db, get_settings(), "instagram", client=client)

    assert result["ok"] is False
    assert result["details"]["select_field"] == "facebook_page_id"
    assert result["details"]["options"] == [
        {"value": "page-1", "label": "Bamboo Pottery · @bamboo"}
    ]


def test_meta_page_change_clears_old_manual_instagram_id():
    settings = get_settings()
    cipher = CredentialCipher(settings)
    with SessionLocal() as db:
        account = IntegrationAccount(
            provider="meta",
            account_key="default",
            status="connected",
            encrypted_credentials=cipher.encrypt_json(
                {
                    "access_token": "meta-token",
                    "facebook_page_id": "old-page",
                    "instagram_user_id": "old-ig",
                }
            ),
        )
        db.add(account)
        db.commit()

        merge_provider_config(db, settings, "meta", {"facebook_page_id": "new-page"})
        credentials = cipher.decrypt_json(account.encrypted_credentials)

    assert credentials["facebook_page_id"] == "new-page"
    assert "instagram_user_id" not in credentials
    assert [field["name"] for field in provider_config_fields("meta")] == ["facebook_page_id"]


@pytest.mark.asyncio
async def test_pinterest_health_offers_board_picker_without_manual_id():
    _oauth_account("pinterest", {"access_token": "pin-token"})

    async def handler(request):
        assert request.url.path == "/v5/boards"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "board-1", "name": "Керамика"},
                    {"id": "board-2", "name": "Новинки"},
                ],
                "bookmark": None,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client, SessionLocal() as db:
        result = await channel_health(db, get_settings(), "pinterest", client=client)

    assert result["details"]["select_field"] == "board_id"
    assert result["details"]["options"][0] == {"value": "board-1", "label": "Керамика"}


@pytest.mark.asyncio
async def test_pinterest_health_offers_sections_after_board_is_selected():
    _oauth_account("pinterest", {"access_token": "pin-token", "board_id": "board-1"})

    async def handler(request):
        if request.url.path == "/v5/boards/board-1":
            return httpx.Response(200, json={"id": "board-1", "name": "Керамика"})
        if request.url.path == "/v5/boards/board-1/sections":
            return httpx.Response(
                200,
                json={"items": [{"id": "section-1", "name": "Чашки"}], "bookmark": None},
            )
        raise AssertionError(str(request.url))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client, SessionLocal() as db:
        result = await channel_health(db, get_settings(), "pinterest", client=client)

    assert result["ok"] is True
    assert result["details"]["secondary_select_field"] == "board_section_id"
    assert result["details"]["secondary_options"] == [
        {"value": "section-1", "label": "Чашки"}
    ]
