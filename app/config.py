from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bamboo Content Hub"
    app_base_url: str = "http://localhost:8080"
    app_timezone: str = "Europe/Helsinki"
    database_url: str = "sqlite:///./data/bamboo.db"
    data_dir: Path = Path("./data")
    media_dir: Path = Path("./data/media")
    secret_key: str = Field(default="change-me-in-production", min_length=16)
    master_key: str | None = None
    trusted_lan: bool = True
    admin_password_hash: str | None = None
    session_ttl_seconds: int = 12 * 60 * 60
    auth_rate_limit_per_minute: int = 10
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 10
    delivery_lease_seconds: int = 300
    signed_media_ttl_seconds: int = 1800
    max_upload_bytes: int = 100 * 1024 * 1024

    google_client_id: str | None = None
    google_client_secret: str | None = None
    pinterest_client_id: str | None = None
    pinterest_client_secret: str | None = None
    tiktok_client_id: str | None = None
    tiktok_client_secret: str | None = None
    meta_client_id: str | None = None
    meta_client_secret: str | None = None
    meta_authorize_url: str = "https://www.facebook.com/v23.0/dialog/oauth"
    meta_token_url: str = "https://graph.facebook.com/v23.0/oauth/access_token"
    vk_client_id: str | None = None
    vk_client_secret: str | None = None
    vk_authorize_url: str = "https://id.vk.com/authorize"
    vk_token_url: str = "https://id.vk.com/oauth2/auth"

    webhook_verify_token: str | None = None
    meta_webhook_secret: str | None = None

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.app_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown APP_TIMEZONE: {self.app_timezone}") from exc

    @property
    def secure_cookies(self) -> bool:
        return urlparse(self.app_base_url).scheme == "https"

    def validate_runtime_security(self) -> None:
        if self.trusted_lan:
            return
        problems: list[str] = []
        if len(self.secret_key) < 32 or self.secret_key == "change-me-in-production":
            problems.append("SECRET_KEY must be a random value of at least 32 characters")
        if not self.master_key or len(self.master_key) < 32:
            problems.append("MASTER_KEY must be a separate random value of at least 32 characters")
        if not self.admin_password_hash or not self.admin_password_hash.startswith("$argon2"):
            problems.append("ADMIN_PASSWORD_HASH must contain an Argon2 password hash")
        parsed = urlparse(self.app_base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            problems.append("APP_BASE_URL must use HTTPS when TRUSTED_LAN=false")
        if problems:
            raise ValueError("Unsafe public configuration: " + "; ".join(problems))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _ = settings.timezone
    settings.validate_runtime_security()
    settings.ensure_dirs()
    return settings
