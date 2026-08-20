from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import IntegrationAccount
from ..oauth import valid_access_token
from ..security import CredentialCipher
from .base import PublishError, PublishRequest
from .connectors import credential_provider
from .registry import CONNECTORS

OAUTH_PROVIDERS = {"meta", "google", "pinterest", "tiktok", "vk"}

PROVIDER_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token", "chat_id"),
    "pinterest": ("board_id", "board_section_id"),
    "vk": ("owner_id",),
    "meta": ("instagram_user_id", "facebook_page_id"),
    "tiktok": (),
    "google": ("youtube_category_id",),
}
CONFIG_FIELD_META: dict[str, dict] = {
    "bot_token": {
        "label": "Токен бота",
        "type": "password",
        "placeholder": "123456:ABC…",
        "help": "Создайте бота через BotFather и добавьте его администратором канала.",
    },
    "chat_id": {
        "label": "Канал / chat ID",
        "type": "text",
        "placeholder": "@bamboopottery",
    },
    "board_id": {
        "label": "Доска Pinterest",
        "type": "text",
        "placeholder": "ID доски",
        "required": True,
    },
    "board_section_id": {
        "label": "Раздел доски",
        "type": "text",
        "placeholder": "необязательно",
    },
    "owner_id": {
        "label": "Стена VK",
        "type": "text",
        "placeholder": "ID пользователя или -ID сообщества",
        "required": True,
    },
    "instagram_user_id": {
        "label": "Instagram Professional ID",
        "type": "text",
        "placeholder": "ID профессионального аккаунта",
    },
    "facebook_page_id": {
        "label": "Facebook Page ID",
        "type": "text",
        "placeholder": "ID страницы",
    },
    "youtube_category_id": {
        "label": "Категория YouTube",
        "type": "text",
        "placeholder": "22",
        "help": "По умолчанию используется категория 22 (People & Blogs).",
    },
}
SECRET_CONFIG_FIELDS = {"bot_token"}

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
    if allowed is None:
        raise ValueError("Неизвестная интеграция")
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"Неизвестные поля интеграции: {', '.join(sorted(unknown))}")
    if not allowed:
        raise ValueError("Для этой интеграции нет постоянных пользовательских настроек")

    account = provider_account(db, provider)
    if not account:
        account = IntegrationAccount(
            provider=provider,
            account_key="default",
            status="configured",
        )
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
        if key in SECRET_CONFIG_FIELDS and value == "••••••••":
            continue
        if value in (None, ""):
            credentials.pop(key, None)
        else:
            credentials[key] = value
    account.encrypted_credentials = CredentialCipher(settings).encrypt_json(credentials)
    if provider == "telegram":
        account.status = (
            "connected"
            if credentials.get("bot_token") and credentials.get("chat_id")
            else "configured"
        )
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
            result[field] = ""
            result[f"{field}_configured"] = bool(value)
        else:
            result[field] = value
    return result


def provider_config_fields(provider: str) -> list[dict]:
    return [
        {"name": name, **CONFIG_FIELD_META[name]}
        for name in PROVIDER_CONFIG_FIELDS.get(provider, ())
        if name in CONFIG_FIELD_META
    ]


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
