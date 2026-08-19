from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings


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
