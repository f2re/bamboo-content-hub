from __future__ import annotations

from functools import lru_cache
from pathlib import Path
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

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _ = settings.timezone
    settings.ensure_dirs()
    return settings
