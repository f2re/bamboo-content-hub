from __future__ import annotations

import base64

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
    raise_for_provider,
)

API_BASE = "https://api.pinterest.com/v5"


class PinterestConnector:
    channel = "pinterest"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=True,
            videos=False,
            max_media=1,
            notes=("Один Pin содержит одно автоматически загружаемое изображение в текущем адаптере.",),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("Pinterest не подключён: отсутствует access token")
        if not request.config.get("board_id"):
            errors.append("Выберите board_id для Pinterest")
        if len(request.media) != 1:
            errors.append("Для Pinterest выберите ровно одно изображение")
        elif not request.media[0].is_image:
            errors.append("Текущий Pinterest adapter поддерживает автоматическую загрузку изображений")
        title = str(request.content.get("title") or "")
        description = str(request.content.get("description") or request.text or "")
        if len(title) > 100:
            errors.append("Заголовок Pinterest не должен превышать 100 символов")
        if len(description) > 800:
            errors.append("Описание Pinterest не должно превышать 800 символов")
        return errors

    @staticmethod
    def _headers(config: dict) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {config['access_token']}",
            "Content-Type": "application/json",
        }

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth:
        if not request.config.get("access_token"):
            raise PermanentPublishError("Pinterest не подключён: отсутствует access token")
        if not request.config.get("board_id"):
            raise PermanentPublishError("Выберите board_id для Pinterest")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            try:
                response = await client.get(
                    f"{API_BASE}/boards/{request.config['board_id']}",
                    headers=self._headers(request.config),
                )
            except httpx.RequestError as exc:
                raise TransientPublishError(f"Pinterest network error: {type(exc).__name__}") from exc
            raise_for_provider(response, "Pinterest")
            body = response.json()
            return ConnectorHealth(
                ok=True,
                message="Доска Pinterest доступна",
                details={"board_id": body.get("id"), "name": body.get("name")},
            )
        finally:
            if owned:
                await client.aclose()

    async def publish(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> PublishResult:
        ensure_valid(self, request)
        media = request.media[0]
        try:
            with open(media.path, "rb") as handle:
                data = base64.b64encode(handle.read()).decode()
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать изображение Pinterest") from exc
        payload: dict = {
            "board_id": str(request.config["board_id"]),
            "title": str(request.content.get("title") or "")[:100],
            "description": str(request.content.get("description") or request.text or "")[:800],
            "alt_text": media.alt_text[:500],
            "media_source": {
                "source_type": "image_base64",
                "content_type": media.mime_type,
                "data": data,
            },
        }
        if request.config.get("board_section_id"):
            payload["board_section_id"] = str(request.config["board_section_id"])
        destination_url = str(request.content.get("destination_url") or "").strip()
        if destination_url:
            payload["link"] = destination_url

        owned = client is None
        client = client or httpx.AsyncClient(timeout=60)
        try:
            try:
                response = await client.post(
                    f"{API_BASE}/pins",
                    headers=self._headers(request.config),
                    json=payload,
                )
            except httpx.RequestError as exc:
                raise TransientPublishError(f"Pinterest network error: {type(exc).__name__}") from exc
            raise_for_provider(response, "Pinterest")
            body = response.json()
            pin_id = str(body.get("id") or "")
            if not pin_id:
                raise TransientPublishError("Pinterest не вернул id созданного Pin")
            return PublishResult(
                external_post_id=pin_id,
                external_url=f"https://www.pinterest.com/pin/{pin_id}/",
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
            try:
                response = await client.get(
                    f"{API_BASE}/pins/{external_post_id}",
                    headers=self._headers(request.config),
                )
            except httpx.RequestError as exc:
                raise TransientPublishError(f"Pinterest network error: {type(exc).__name__}") from exc
            if response.status_code == 404:
                return PublishStatus(state="failed", message="Pin не найден")
            raise_for_provider(response, "Pinterest")
            return PublishStatus(
                state="published",
                external_url=f"https://www.pinterest.com/pin/{external_post_id}/",
            )
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {"pinterest": PinterestConnector()}
