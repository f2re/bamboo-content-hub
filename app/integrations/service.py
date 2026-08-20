from __future__ import annotations

from dataclasses import asdict

import httpx
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
META_GRAPH_BASE = "https://graph.facebook.com/v23.0"
PINTEREST_API_BASE = "https://api.pinterest.com/v5"

PROVIDER_CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("bot_token", "chat_id"),
    "pinterest": ("board_id", "board_section_id"),
    "vk": ("owner_id",),
    # Instagram Professional ID is discovered from the selected Facebook Page.
    "meta": ("facebook_page_id",),
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
        "placeholder": "После OAuth нажмите «Проверить Pinterest»",
        "required": True,
        "help": "Хаб умеет получить доступные доски автоматически — ID вручную искать не нужно.",
    },
    "board_section_id": {
        "label": "Раздел доски",
        "type": "text",
        "placeholder": "необязательно",
        "help": "После выбора доски повторная проверка предложит доступные разделы.",
    },
    "owner_id": {
        "label": "Стена VK",
        "type": "text",
        "placeholder": "ID пользователя или -ID сообщества",
        "required": True,
        "help": "Для сообщества используется отрицательный ID. Автовыбор будет добавлен после унификации VK ID permissions.",
    },
    "facebook_page_id": {
        "label": "Страница Meta",
        "type": "text",
        "placeholder": "После OAuth нажмите проверку Facebook/Instagram",
        "help": "Хаб получит список доступных Facebook Pages; связанный Instagram Professional account определяется автоматически.",
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

    old_board_id = str(credentials.get("board_id") or "")
    new_board_id = str(values.get("board_id") or "").strip() if "board_id" in values else old_board_id
    if provider == "pinterest" and new_board_id != old_board_id:
        credentials.pop("board_section_id", None)
    if provider == "meta" and "facebook_page_id" in values:
        # Prevent an old manually entered Instagram ID from overriding discovery for a new Page.
        credentials.pop("instagram_user_id", None)

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


async def _meta_page_picker(
    config: dict,
    channel: str,
    client: httpx.AsyncClient,
) -> dict:
    try:
        response = await client.get(
            f"{META_GRAPH_BASE}/me/accounts",
            headers={"Authorization": f"Bearer {config['access_token']}"},
            params={
                "fields": "id,name,instagram_business_account{id,username}",
                "limit": 100,
            },
        )
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "channel": channel,
            "message": f"Не удалось получить страницы Meta: {type(exc).__name__}",
        }
    if not response.is_success:
        return {
            "ok": False,
            "channel": channel,
            "message": f"Meta не вернул список страниц (HTTP {response.status_code})",
        }
    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "channel": channel, "message": "Meta вернул некорректный ответ"}
    pages = body.get("data") if isinstance(body, dict) else None
    if not isinstance(pages, list):
        pages = []
    options = []
    for page in pages:
        if not isinstance(page, dict) or not page.get("id"):
            continue
        instagram = page.get("instagram_business_account")
        if channel == "instagram" and not isinstance(instagram, dict):
            continue
        name = str(page.get("name") or page["id"])
        if channel == "instagram" and isinstance(instagram, dict):
            username = str(instagram.get("username") or "").strip()
            if username:
                name = f"{name} · @{username}"
        options.append({"value": str(page["id"]), "label": name})
    message = (
        "Выберите страницу, связанную с Instagram Professional account"
        if channel == "instagram"
        else "Выберите Facebook Page"
    )
    if not options:
        message = (
            "Meta не вернул подходящих страниц. Проверьте доступы приложения и тип аккаунта."
        )
    return {
        "ok": False,
        "channel": channel,
        "message": message,
        "details": {"select_field": "facebook_page_id", "options": options},
    }


async def _pinterest_board_picker(config: dict, client: httpx.AsyncClient) -> dict:
    headers = {"Authorization": f"Bearer {config['access_token']}"}
    try:
        response = await client.get(
            f"{PINTEREST_API_BASE}/boards",
            headers=headers,
            params={"page_size": 100},
        )
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "channel": "pinterest",
            "message": f"Не удалось получить доски Pinterest: {type(exc).__name__}",
        }
    if not response.is_success:
        return {
            "ok": False,
            "channel": "pinterest",
            "message": f"Pinterest не вернул список досок (HTTP {response.status_code})",
        }
    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "channel": "pinterest", "message": "Pinterest вернул некорректный ответ"}
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        items = []
    options = [
        {"value": str(item["id"]), "label": str(item.get("name") or item["id"])}
        for item in items
        if isinstance(item, dict) and item.get("id")
    ]
    return {
        "ok": False,
        "channel": "pinterest",
        "message": "Выберите доску Pinterest" if options else "Pinterest не вернул доступных досок",
        "details": {"select_field": "board_id", "options": options},
    }


async def _pinterest_sections(
    config: dict,
    client: httpx.AsyncClient,
) -> list[dict]:
    board_id = str(config.get("board_id") or "").strip()
    if not board_id:
        return []
    try:
        response = await client.get(
            f"{PINTEREST_API_BASE}/boards/{board_id}/sections",
            headers={"Authorization": f"Bearer {config['access_token']}"},
            params={"page_size": 100},
        )
    except httpx.RequestError:
        return []
    if not response.is_success:
        return []
    try:
        body = response.json()
    except ValueError:
        return []
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    return [
        {"value": str(item["id"]), "label": str(item.get("name") or item["id"])}
        for item in items
        if isinstance(item, dict) and item.get("id")
    ]


async def channel_health(
    db: Session,
    settings: Settings,
    channel: str,
    client: httpx.AsyncClient | None = None,
) -> dict:
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

    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        if provider == "meta" and config.get("access_token") and not config.get("facebook_page_id"):
            result = await _meta_page_picker(config, channel, client)
            result["capabilities"] = asdict(connector.capabilities())
            return result
        if provider == "pinterest" and config.get("access_token") and not config.get("board_id"):
            result = await _pinterest_board_picker(config, client)
            result["capabilities"] = asdict(connector.capabilities())
            return result

        request = PublishRequest(
            text="Проверка подключения Bamboo Content Hub",
            media=(),
            config=config,
            content={},
            idempotency_key="health-check",
        )
        try:
            health = await connector.health(request, client=client)
            details = dict(health.details or {})
            if provider == "pinterest" and health.ok:
                sections = await _pinterest_sections(config, client)
                if sections:
                    details.update(
                        {
                            "secondary_select_field": "board_section_id",
                            "secondary_options": sections,
                        }
                    )
            return {
                "ok": health.ok,
                "channel": channel,
                "message": health.message,
                "details": details,
                "capabilities": asdict(connector.capabilities()),
            }
        except PublishError as exc:
            return {
                "ok": False,
                "channel": channel,
                "message": str(exc),
                "capabilities": asdict(connector.capabilities()),
            }
    finally:
        if owned_client:
            await client.aclose()
