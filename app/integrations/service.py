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
from .onboarding import discover_target_choices
from .registry import CONNECTORS

OAUTH_PROVIDERS = {"meta", "google", "pinterest", "tiktok", "vk"}

PROVIDER_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token", "chat_id"),
    "pinterest": ("oauth_client_id", "oauth_client_secret", "board_id", "board_section_id"),
    "vk": ("oauth_client_id", "oauth_client_secret", "owner_id"),
    "meta": (
        "oauth_client_id",
        "oauth_client_secret",
        "instagram_user_id",
        "facebook_page_id",
    ),
    "tiktok": ("oauth_client_id", "oauth_client_secret"),
    "google": ("oauth_client_id", "oauth_client_secret", "youtube_category_id"),
}
CONFIG_FIELD_META: dict[str, dict] = {
    "oauth_client_id": {
        "label": "Client ID / App ID",
        "type": "text",
        "placeholder": "Вставьте ID приложения",
        "help": "Берётся в кабинете разработчика площадки. Это не пароль.",
        "phase": "oauth",
    },
    "oauth_client_secret": {
        "label": "Client Secret",
        "type": "password",
        "placeholder": "Вставьте секрет приложения",
        "help": "Сохраняется в Bamboo в зашифрованном виде и после сохранения не показывается.",
        "phase": "oauth",
    },
    "bot_token": {
        "label": "Токен бота",
        "type": "password",
        "placeholder": "123456:ABC…",
        "help": "Создайте бота через BotFather и добавьте его администратором канала.",
        "phase": "setup",
    },
    "chat_id": {
        "label": "Канал",
        "type": "text",
        "placeholder": "@bamboopottery",
        "help": "Для публичного канала достаточно @имени_канала; числовой chat ID искать не нужно.",
        "phase": "setup",
    },
    "board_id": {
        "label": "Доска Pinterest",
        "type": "text",
        "placeholder": "Выберите автоматически или вставьте ID",
        "required": True,
        "phase": "target",
    },
    "board_section_id": {
        "label": "Раздел доски",
        "type": "text",
        "placeholder": "необязательно",
        "phase": "optional",
    },
    "owner_id": {
        "label": "Стена VK",
        "type": "text",
        "placeholder": "Выберите автоматически или вставьте owner_id",
        "required": True,
        "phase": "target",
    },
    "instagram_user_id": {
        "label": "Instagram Professional ID",
        "type": "text",
        "placeholder": "Определится по выбранной Facebook Page",
        "phase": "target",
    },
    "facebook_page_id": {
        "label": "Facebook Page",
        "type": "text",
        "placeholder": "Выберите автоматически после OAuth",
        "phase": "target",
    },
    "youtube_category_id": {
        "label": "Категория YouTube",
        "type": "text",
        "placeholder": "22",
        "help": "По умолчанию используется категория 22 (People & Blogs).",
        "phase": "optional",
    },
}
SECRET_CONFIG_FIELDS = {"bot_token", "oauth_client_secret"}
OAUTH_TOKEN_FIELDS = {
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

_OAUTH_ENV_FIELDS: dict[str, tuple[str, str]] = {
    "google": ("google_client_id", "google_client_secret"),
    "pinterest": ("pinterest_client_id", "pinterest_client_secret"),
    "tiktok": ("tiktok_client_id", "tiktok_client_secret"),
    "meta": ("meta_client_id", "meta_client_secret"),
    "vk": ("vk_client_id", "vk_client_secret"),
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
    previous_oauth = {
        "oauth_client_id": credentials.get("oauth_client_id"),
        "oauth_client_secret": credentials.get("oauth_client_secret"),
    }

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

    oauth_changed = provider in OAUTH_PROVIDERS and any(
        previous_oauth[key] != credentials.get(key)
        for key in ("oauth_client_id", "oauth_client_secret")
    )
    if oauth_changed:
        for key in OAUTH_TOKEN_FIELDS:
            credentials.pop(key, None)
        account.expires_at = None

    account.encrypted_credentials = CredentialCipher(settings).encrypt_json(credentials)
    if provider == "telegram":
        account.status = (
            "connected"
            if credentials.get("bot_token") and credentials.get("chat_id")
            else "configured"
        )
    elif credentials.get("access_token") and not oauth_changed:
        account.status = "connected"
    else:
        account.status = "configured"
    db.commit()
    db.refresh(account)
    return account


def _oauth_env_values(settings: Settings, provider: str) -> tuple[str | None, str | None]:
    attrs = _OAUTH_ENV_FIELDS.get(provider)
    if not attrs:
        return None, None
    return getattr(settings, attrs[0], None), getattr(settings, attrs[1], None)


def public_provider_config(db: Session, settings: Settings, provider: str) -> dict:
    credentials = decrypted_credentials(db, settings, provider)
    env_client_id, env_client_secret = _oauth_env_values(settings, provider)
    result: dict = {}
    for field in PROVIDER_CONFIG_FIELDS.get(provider, ()):
        value = credentials.get(field)
        if field == "oauth_client_id":
            effective = value or env_client_id
            result[field] = effective or ""
            result["oauth_client_id_configured"] = bool(effective)
            result["oauth_credentials_source"] = (
                "interface" if value else "environment" if env_client_id else ""
            )
        elif field == "oauth_client_secret":
            effective = value or env_client_secret
            result[field] = ""
            result["oauth_client_secret_configured"] = bool(effective)
        elif field in SECRET_CONFIG_FIELDS:
            result[field] = ""
            result[f"{field}_configured"] = bool(value)
        else:
            result[field] = value
    if provider in OAUTH_PROVIDERS:
        result["oauth_ready"] = bool(
            result.get("oauth_client_id_configured")
            and result.get("oauth_client_secret_configured")
        )
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

    discovery = await discover_target_choices(provider, config)
    if discovery is not None:
        return {
            "channel": channel,
            "capabilities": asdict(connector.capabilities()),
            **discovery,
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
