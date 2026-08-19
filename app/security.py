from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings

_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_MEDIA_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


class CredentialCipher:
    def __init__(self, settings: Settings):
        raw = settings.master_key or settings.secret_key
        key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt_json(self, value: dict) -> str:
        return self._fernet.encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()

    def decrypt_json(self, value: str | None) -> dict:
        if not value:
            return {}
        try:
            return json.loads(self._fernet.decrypt(value.encode()).decode())
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise ValueError("Unable to decrypt stored credentials") from exc

    def encrypt_text(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt_text(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()


def random_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def hash_admin_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Пароль администратора должен содержать не менее 12 символов")
    return _PASSWORD_HASHER.hash(password)


def verify_admin_password(password_hash: str | None, password: str) -> bool:
    if not password_hash or not password:
        return False
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(settings: Settings) -> tuple[str, str]:
    csrf = random_token(24)
    payload = {
        "v": 1,
        "exp": int(time.time()) + settings.session_ttl_seconds,
        "csrf": csrf,
    }
    encoded = _b64_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.secret_key.encode(),
        f"session.{encoded}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}", csrf


def verify_session_token(settings: Settings, token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    try:
        encoded, supplied_signature = token.rsplit(".", 1)
        expected_signature = hmac.new(
            settings.secret_key.encode(),
            f"session.{encoded}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_b64_decode(encoded))
        if payload.get("v") != 1 or int(payload.get("exp", 0)) < int(time.time()):
            return None
        if not isinstance(payload.get("csrf"), str):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def detect_media_mime(content: bytes) -> str | None:
    """Detect a small allowlist of safe image/video formats from file signatures."""
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV"}:
            return "video/mp4"
    return None


def safe_media_extension(mime_type: str) -> str:
    try:
        return _MEDIA_EXTENSIONS[mime_type]
    except KeyError as exc:
        raise ValueError("unsupported media type") from exc


def sign_media_token(settings: Settings, asset_id: str, ttl: int | None = None) -> str:
    exp = int(time.time()) + int(ttl or settings.signed_media_ttl_seconds)
    nonce = random_token(8)
    body = f"{asset_id}.{exp}.{nonce}"
    sig = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    payload = f"{body}.{sig}".encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def verify_media_token(settings: Settings, token: str) -> str:
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode()
        asset_id, exp_s, nonce, sig = decoded.rsplit(".", 3)
        body = f"{asset_id}.{exp_s}.{nonce}"
        expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("invalid signature")
        if int(exp_s) < int(time.time()):
            raise ValueError("expired token")
        return asset_id
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("invalid token") from exc


def safe_media_path(media_dir: Path, stored_filename: str) -> Path:
    root = media_dir.resolve()
    path = (root / stored_filename).resolve()
    if root != path and root not in path.parents:
        raise ValueError("unsafe media path")
    return path
