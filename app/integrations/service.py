from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import IntegrationAccount
from ..oauth import valid_access_token
from ..security import CredentialCipher
from .base import PublishError, PublishRequest
from .connectors import CONNECTORS, credential_provider

OAUTH_PROVIDERS = {"meta", "google", "pinterest", "tiktok", "vk"}

PROVIDER_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token", "chat_id"),
    "pinterest": ("board_id", "board_section_id"),
    "vk": ("owner_id",),
    "meta": ("instagram_user_id", "facebook_page_id"),
    "tiktok": ("privacy_level", "disable_comment", "disable_duet", "disable_stitch"),
    "google": ("youtube_privacy_status", "youtube_category_id"),
}
SECRET_CONFIG_FIELDS = {"bot_token"}
TOKEN_FIELDS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token_type",
    "expires_in",
    "scope",
    "refresh_token_expires_in",
    "open_id",
}

CHANNELS_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "telegram": ("telegram",),
    "pinterest": ("pinterest",),
    "vk": ("vk",),
    "meta": ("instagram", "facebook"),
    "tiktok": ("tiktok",),
    "google": ("youtube",),
}


def provider_account(db: Session, provider: str) -> IntegrationAccount | None:
    return db.scalar(
        select(IntegrationAccount).where(
            IntegrationAccount.provider == provider,
            IntegrationAccount.account_key == "default",
        )
    )


def decrypted_credentials(db: Session, settings: Settings, provider: str) -> dict:
    account = provider_account(db, provider)
    if not account or not account.encrypted_credentials:
        return {}
    return CredentialCipher(settings).decrypt_json(account.encrypted_credentials)


def merge_provider_config(
    db: Session,
    settings: Settings,
    provider: str,
    values: dict,
) -> IntegrationAccount:
    allowed = PROVIDER_CONFIG_FIELDS.get(provider)
    if not allowed:
        raise ValueError("Для этой интеграции нет пользовательских настроек")
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"Неизвестные поля интеграции: {', '.join(sorted(unknown))}")

    account = provider_account(db, provider)
    if not account:
        account = IntegrationAccount(provider=provider, account_key="default", status="configured")
        db.add(account)
        db.flush()

    credentials = {}
    if account.encrypted_credentials:
        credentials = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
    for key in allowed:
        if key not in values:
            continue
        value = values[key]
        if isinstance(value, str):
            value = value.strip()
        if value in (None, ""):
            credentials.pop(key, None)
        else:
            credentials[key] = value
    account.encrypted_credentials = CredentialCipher(settings).encrypt_json(credentials)
    if provider == "telegram":
        account.status = "connected" if credentials.get("bot_token") and credentials.get("chat_id") else "configured"
    elif credentials.get("access_token"):
        account.status = "connected"
    else:
        account.status = "configured"
    db.commit()
    db.refresh(account)
    return account


def public_provider_config(db: Session, settings: Settings, provider: str) -> dict:
    credentials = decrypted_credentials(db, settings, provider)
    result: dict = {}
    for field in PROVIDER_CONFIG_FIELDS.get(provider, ()):
        value = credentials.get(field)
        if field in SECRET_CONFIG_FIELDS:
            result[field] = "••••••••" if value else ""
        else:
            result[field] = value
    return result


async def channel_health(db: Session, settings: Settings, channel: str) -> dict:
    connector = CONNECTORS.get(channel)
    if connector is None:
        return {
            "ok": False,
            "channel": channel,
            "message": "Автоматический адаптер ещё не активирован",
            "capabilities": None,
        }
    provider = credential_provider(channel)
    config = decrypted_credentials(db, settings, provider)
    if provider in OAUTH_PROVIDERS and config.get("access_token"):
        try:
            config["access_token"] = await valid_access_token(db, settings, provider)
        except ValueError as exc:
            return {
                "ok": False,
                "channel": channel,
                "message": str(exc),
                "capabilities": asdict(connector.capabilities()),
            }
    request = PublishRequest(
        text="Проверка подключения Bamboo Content Hub",
        media=(),
        config=config,
        content={},
        idempotency_key="health-check",
    )
    try:
        health = await connector.health(request)
        return {
            "ok": health.ok,
            "channel": channel,
            "message": health.message,
            "details": health.details,
            "capabilities": asdict(connector.capabilities()),
        }
    except PublishError as exc:
        return {
            "ok": False,
            "channel": channel,
            "message": str(exc),
            "capabilities": asdict(connector.capabilities()),
        }
