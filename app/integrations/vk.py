from __future__ import annotations

import json
from pathlib import Path

import httpx

from .base import (
    ConnectorCapabilities,
    ConnectorHealth,
    PermanentPublishError,
    PublishRequest,
    PublishResult,
    PublishStatus,
    TransientPublishError,
    ensure_valid,
)

API_BASE = "https://api.vk.com/method"
API_VERSION = "5.199"
_TRANSIENT_CODES = {1, 6, 9, 10, 29}


def _error_message(error: dict) -> str:
    code = error.get("error_code")
    message = str(error.get("error_msg") or "VK API error").replace("\n", " ").strip()[:500]
    return f"VK API error {code}: {message}"


def _raise_vk_error(body: dict) -> None:
    error = body.get("error")
    if not isinstance(error, dict):
        return
    code = int(error.get("error_code") or 0)
    message = _error_message(error)
    if code in _TRANSIENT_CODES:
        raise TransientPublishError(message)
    raise PermanentPublishError(message)


class VKConnector:
    channel = "vk"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=True,
            videos=False,
            max_media=10,
            notes=("Видео пока не загружается автоматически; используйте изображения или отдельную публикацию.",),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("VK не подключён: отсутствует access token")
        owner_id = request.config.get("owner_id")
        try:
            int(str(owner_id))
        except (TypeError, ValueError):
            errors.append("Укажите числовой owner_id стены VK; для сообщества используется отрицательный ID")
        if len(request.media) > 10:
            errors.append("VK: не более 10 изображений в одной публикации")
        if any(not item.is_image for item in request.media):
            errors.append("Автоматическая публикация VK сейчас поддерживает только изображения")
        if not request.text.strip() and not request.media:
            errors.append("Публикация VK не может быть пустой")
        return errors

    async def _call(
        self,
        client: httpx.AsyncClient,
        method: str,
        config: dict,
        params: dict | None = None,
    ) -> object:
        data = {
            "access_token": config["access_token"],
            "v": API_VERSION,
            **(params or {}),
        }
        try:
            response = await client.post(f"{API_BASE}/{method}", data=data)
        except httpx.RequestError as exc:
            raise TransientPublishError(f"VK network error: {type(exc).__name__}") from exc
        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise TransientPublishError(f"VK API returned HTTP {response.status_code}")
        if not response.is_success:
            raise PermanentPublishError(f"VK API returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise TransientPublishError("VK API returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise TransientPublishError("VK API returned invalid response")
        _raise_vk_error(body)
        return body.get("response")

    @staticmethod
    def _owner_id(config: dict) -> int:
        return int(str(config["owner_id"]))

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth:
        ensure_valid(self, request)
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            owner_id = self._owner_id(request.config)
            response = await self._call(
                client,
                "wall.get",
                request.config,
                {"owner_id": owner_id, "count": 1, "filter": "owner"},
            )
            count = response.get("count") if isinstance(response, dict) else None
            return ConnectorHealth(
                ok=True,
                message="Стена VK доступна",
                details={"owner_id": owner_id, "posts": count},
            )
        finally:
            if owned:
                await client.aclose()

    async def _upload_image(
        self,
        client: httpx.AsyncClient,
        request: PublishRequest,
        media,
    ) -> str:
        owner_id = self._owner_id(request.config)
        upload_params: dict = {}
        save_params: dict = {}
        if owner_id < 0:
            group_id = abs(owner_id)
            upload_params["group_id"] = group_id
            save_params["group_id"] = group_id
        else:
            save_params["user_id"] = owner_id

        upload_info = await self._call(
            client,
            "photos.getWallUploadServer",
            request.config,
            upload_params,
        )
        if not isinstance(upload_info, dict) or not upload_info.get("upload_url"):
            raise TransientPublishError("VK не вернул upload_url для фотографии")

        try:
            with open(media.path, "rb") as handle:
                upload_response = await client.post(
                    str(upload_info["upload_url"]),
                    files={"photo": (Path(media.path).name, handle, media.mime_type)},
                )
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать изображение VK") from exc
        except httpx.RequestError as exc:
            raise TransientPublishError(f"VK photo upload network error: {type(exc).__name__}") from exc
        if upload_response.status_code >= 500 or upload_response.status_code in {408, 429}:
            raise TransientPublishError(
                f"VK photo upload returned HTTP {upload_response.status_code}"
            )
        if not upload_response.is_success:
            raise PermanentPublishError(
                f"VK photo upload returned HTTP {upload_response.status_code}"
            )
        try:
            uploaded = upload_response.json()
        except ValueError as exc:
            raise TransientPublishError("VK photo upload returned invalid JSON") from exc
        if not isinstance(uploaded, dict) or not all(
            key in uploaded for key in ("server", "photo", "hash")
        ):
            raise TransientPublishError("VK photo upload returned incomplete response")

        save_params.update(
            {
                "server": uploaded["server"],
                "photo": (
                    uploaded["photo"]
                    if isinstance(uploaded["photo"], str)
                    else json.dumps(uploaded["photo"])
                ),
                "hash": uploaded["hash"],
            }
        )
        saved = await self._call(client, "photos.saveWallPhoto", request.config, save_params)
        if not isinstance(saved, list) or not saved or not isinstance(saved[0], dict):
            raise TransientPublishError("VK не вернул сохранённую фотографию")
        photo = saved[0]
        if photo.get("owner_id") is None or photo.get("id") is None:
            raise TransientPublishError("VK не вернул ID сохранённой фотографии")
        return f"photo{photo['owner_id']}_{photo['id']}"

    async def publish(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> PublishResult:
        ensure_valid(self, request)
        owned = client is None
        client = client or httpx.AsyncClient(timeout=60)
        try:
            attachments = [await self._upload_image(client, request, item) for item in request.media]
            owner_id = self._owner_id(request.config)
            params: dict = {
                "owner_id": owner_id,
                "message": request.text,
                # VK API 5.199 exposes guid specifically to prevent duplicate wall posts.
                "guid": request.idempotency_key,
            }
            if attachments:
                params["attachments"] = ",".join(attachments)
            if owner_id < 0:
                params["from_group"] = 1
            response = await self._call(client, "wall.post", request.config, params)
            if not isinstance(response, dict) or response.get("post_id") is None:
                raise TransientPublishError("VK не вернул post_id")
            post_id = str(response["post_id"])
            return PublishResult(
                external_post_id=f"{owner_id}_{post_id}",
                external_url=f"https://vk.com/wall{owner_id}_{post_id}",
            )
        finally:
            if owned:
                await client.aclose()

    async def status(
        self,
        request: PublishRequest,
        external_post_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> PublishStatus:
        ensure_valid(self, request)
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            response = await self._call(
                client,
                "wall.getById",
                request.config,
                {"posts": external_post_id},
            )
            if isinstance(response, list) and response:
                return PublishStatus(
                    state="published",
                    external_url=f"https://vk.com/wall{external_post_id}",
                )
            return PublishStatus(state="failed", message="Запись VK не найдена")
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {"vk": VKConnector()}
