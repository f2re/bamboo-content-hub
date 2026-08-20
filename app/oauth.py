from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import IntegrationAccount, OAuthState
from .security import CredentialCipher, pkce_pair, random_token, token_hash


@dataclass(frozen=True)
class OAuthProvider:
    name: str
    authorize_url: str
    token_url: str
    client_id: str | None
    client_secret: str | None
    scopes: tuple[str, ...]
    revoke_url: str | None = None
    use_pkce: bool = True
    client_id_param: str = "client_id"
    client_secret_param: str = "client_secret"
    token_auth: str = "body"  # body | basic
    scope_separator: str = " "
    extra_authorize: dict[str, str] = field(default_factory=dict)
    extra_token: dict[str, str] = field(default_factory=dict)


def provider_registry(settings: Settings) -> dict[str, OAuthProvider]:
    return {
        "google": OAuthProvider(
            name="google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            revoke_url="https://oauth2.googleapis.com/revoke",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=(
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ),
            use_pkce=True,
            extra_authorize={"access_type": "offline", "include_granted_scopes": "true", "prompt": "consent"},
        ),
        "pinterest": OAuthProvider(
            name="pinterest",
            authorize_url="https://www.pinterest.com/oauth/",
            token_url="https://api.pinterest.com/v5/oauth/token",
            client_id=settings.pinterest_client_id,
            client_secret=settings.pinterest_client_secret,
            scopes=("boards:read", "boards:write", "pins:read", "pins:write"),
            use_pkce=False,
            token_auth="basic",
            scope_separator=",",
            extra_token={"continuous_refresh": "true"},
        ),
        "tiktok": OAuthProvider(
            name="tiktok",
            authorize_url="https://www.tiktok.com/v2/auth/authorize/",
            token_url="https://open.tiktokapis.com/v2/oauth/token/",
            client_id=settings.tiktok_client_id,
            client_secret=settings.tiktok_client_secret,
            client_id_param="client_key",
            client_secret_param="client_secret",
            scopes=("user.info.basic", "video.publish", "video.upload"),
            use_pkce=True,
            scope_separator=",",
        ),
        "meta": OAuthProvider(
            name="meta",
            authorize_url=settings.meta_authorize_url,
            token_url=settings.meta_token_url,
            client_id=settings.meta_client_id,
            client_secret=settings.meta_client_secret,
            scopes=(
                "instagram_basic",
                "instagram_content_publish",
                "pages_show_list",
                "pages_read_engagement",
                "pages_manage_posts",
            ),
            use_pkce=False,
            scope_separator=",",
        ),
        "vk": OAuthProvider(
            name="vk",
            authorize_url=settings.vk_authorize_url,
            token_url=settings.vk_token_url,
            client_id=settings.vk_client_id,
            client_secret=settings.vk_client_secret,
            scopes=("wall", "photos", "video", "offline"),
            use_pkce=True,
        ),
    }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def begin_oauth(db: Session, settings: Settings, provider_name: str) -> str:
    provider = provider_registry(settings).get(provider_name)
    if not provider:
        raise ValueError("unknown OAuth provider")
    if not provider.client_id:
        raise ValueError(f"{provider_name} client id is not configured")
    redirect_uri = f"{settings.app_base_url.rstrip('/')}/oauth/{provider_name}/callback"
    state = random_token(32)
    verifier = challenge = None
    cipher = CredentialCipher(settings)
    if provider.use_pkce:
        verifier, challenge = pkce_pair()
    row = OAuthState(
        provider=provider_name,
        state_hash=token_hash(state),
        code_verifier_encrypted=cipher.encrypt_text(verifier) if verifier else None,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()
    params = {
        provider.client_id_param: provider.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider.scope_separator.join(provider.scopes),
        "state": state,
        **provider.extra_authorize,
    }
    if challenge:
        params.update({"code_challenge": challenge, "code_challenge_method": "S256"})
    return f"{provider.authorize_url}?{urlencode(params)}"


def consume_state(db: Session, settings: Settings, provider_name: str, state: str) -> tuple[OAuthState, str | None]:
    row = db.scalar(select(OAuthState).where(OAuthState.state_hash == token_hash(state), OAuthState.provider == provider_name))
    if not row or row.used_at is not None:
        raise ValueError("invalid or already used OAuth state")
    if _aware(row.expires_at) < datetime.now(UTC):
        raise ValueError("OAuth state expired")
    row.used_at = datetime.now(UTC)
    db.commit()
    verifier = CredentialCipher(settings).decrypt_text(row.code_verifier_encrypted) if row.code_verifier_encrypted else None
    return row, verifier


def _auth_and_data(provider: OAuthProvider, data: dict) -> tuple[dict, tuple[str, str] | None]:
    auth = None
    if provider.token_auth == "basic":
        if not provider.client_secret:
            raise ValueError("client secret is not configured")
        auth = (provider.client_id or "", provider.client_secret)
    else:
        data[provider.client_id_param] = provider.client_id
        if provider.client_secret:
            data[provider.client_secret_param] = provider.client_secret
    return data, auth


async def exchange_code(db: Session, settings: Settings, provider_name: str, code: str, state: str, client: httpx.AsyncClient | None = None) -> IntegrationAccount:
    provider = provider_registry(settings).get(provider_name)
    if not provider:
        raise ValueError("unknown OAuth provider")
    state_row, verifier = consume_state(db, settings, provider_name, state)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": state_row.redirect_uri,
        **provider.extra_token,
    }
    if verifier:
        data["code_verifier"] = verifier
    data, auth = _auth_and_data(provider, data)
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.post(provider.token_url, data=data, auth=auth)
        response.raise_for_status()
        token = response.json()
    finally:
        if owned_client:
            await client.aclose()
    expires_at = None
    if token.get("expires_in"):
        expires_at = datetime.now(UTC) + timedelta(seconds=int(token["expires_in"]))
    scopes = token.get("scope") or provider.scopes
    if isinstance(scopes, str):
        scopes = scopes.replace(",", " ").split()
    account = db.scalar(select(IntegrationAccount).where(IntegrationAccount.provider == provider_name, IntegrationAccount.account_key == "default"))
    if not account:
        account = IntegrationAccount(provider=provider_name, account_key="default")
        db.add(account)
    credentials = {}
    if account.encrypted_credentials:
        credentials = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
    credentials.update(token)
    account.status = "connected"
    account.scopes = list(scopes)
    account.encrypted_credentials = CredentialCipher(settings).encrypt_json(credentials)
    account.expires_at = expires_at
    account.last_checked_at = datetime.now(UTC)
    db.commit()
    db.refresh(account)
    return account


async def refresh_account(db: Session, settings: Settings, account: IntegrationAccount, client: httpx.AsyncClient | None = None) -> IntegrationAccount:
    provider = provider_registry(settings).get(account.provider)
    if not provider:
        raise ValueError("unknown OAuth provider")
    credentials = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        account.status = "reauthorize"
        db.commit()
        raise ValueError("refresh token is not available")
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    data, auth = _auth_and_data(provider, data)
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.post(provider.token_url, data=data, auth=auth)
        response.raise_for_status()
        new_values = response.json()
    finally:
        if owned_client:
            await client.aclose()
    if "refresh_token" not in new_values:
        new_values["refresh_token"] = refresh_token
    credentials.update(new_values)
    account.encrypted_credentials = CredentialCipher(settings).encrypt_json(credentials)
    if new_values.get("expires_in"):
        account.expires_at = datetime.now(UTC) + timedelta(seconds=int(new_values["expires_in"]))
    account.status = "connected"
    account.last_checked_at = datetime.now(UTC)
    db.commit()
    return account


async def valid_access_token(db: Session, settings: Settings, provider_name: str, safety_window_seconds: int = 600) -> str:
    account = db.scalar(select(IntegrationAccount).where(IntegrationAccount.provider == provider_name, IntegrationAccount.account_key == "default"))
    if not account or not account.encrypted_credentials:
        raise ValueError(f"{provider_name} is not connected")
    if account.expires_at and _aware(account.expires_at) <= datetime.now(UTC) + timedelta(seconds=safety_window_seconds):
        account = await refresh_account(db, settings, account)
    token = CredentialCipher(settings).decrypt_json(account.encrypted_credentials).get("access_token")
    if not token:
        raise ValueError("access token is missing")
    return token


async def revoke_account(db: Session, settings: Settings, provider_name: str, client: httpx.AsyncClient | None = None) -> None:
    provider = provider_registry(settings).get(provider_name)
    account = db.scalar(select(IntegrationAccount).where(IntegrationAccount.provider == provider_name, IntegrationAccount.account_key == "default"))
    if not account:
        return
    credentials = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
    token = credentials.get("refresh_token") or credentials.get("access_token")
    if provider and provider.revoke_url and token:
        owned_client = client is None
        client = client or httpx.AsyncClient(timeout=10)
        try:
            try:
                await client.post(provider.revoke_url, data={"token": token})
            except httpx.HTTPError:
                pass
        finally:
            if owned_client:
                await client.aclose()
    preserved = {
        key: value
        for key, value in credentials.items()
        if key not in {
            "access_token",
            "refresh_token",
            "id_token",
            "token_type",
            "expires_in",
            "scope",
            "refresh_token_expires_in",
            "open_id",
        }
    }
    account.encrypted_credentials = CredentialCipher(settings).encrypt_json(preserved) if preserved else None
    account.status = "configured" if preserved else "disconnected"
    account.expires_at = None
    db.commit()
