from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlparse

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

GRAPH_BASE = "https://graph.facebook.com/v23.0"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _is_public_https(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_unspecified
        )
    except ValueError:
        return False


async def _graph_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    token: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
) -> dict:
    try:
        response = await client.request(
            method,
            f"{GRAPH_BASE}/{path.lstrip('/')}",
            headers=_headers(token),
            params=params,
            data=data,
        )
    except httpx.RequestError as exc:
        raise TransientPublishError(f"Meta network error: {type(exc).__name__}") from exc
    raise_for_provider(response, "Meta")
    try:
        body = response.json()
    except ValueError as exc:
        raise TransientPublishError("Meta API returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise TransientPublishError("Meta API returned invalid response")
    return body


async def _resolve_page(client: httpx.AsyncClient, config: dict) -> tuple[str, str, str | None, str | None]:
    user_token = str(config.get("access_token") or "")
    page_id = str(config.get("facebook_page_id") or "").strip()
    if not user_token:
        raise PermanentPublishError("Meta не подключён: отсутствует User Access Token")
    if not page_id:
        raise PermanentPublishError("Укажите Facebook Page ID для Meta-подключения")
    page = await _graph_request(
        client,
        "GET",
        page_id,
        user_token,
        params={"fields": "id,name,access_token,instagram_business_account"},
    )
    page_token = str(page.get("access_token") or "")
    if not page_token:
        raise PermanentPublishError("Meta не выдал Page Access Token для выбранной страницы")
    instagram = page.get("instagram_business_account") or {}
    discovered_ig_id = instagram.get("id") if isinstance(instagram, dict) else None
    ig_id = str(config.get("instagram_user_id") or discovered_ig_id or "").strip() or None
    return page_id, page_token, ig_id, page.get("name")


def _media_url_errors(request: PublishRequest) -> list[str]:
    errors: list[str] = []
    for item in request.media:
        if not _is_public_https(item.public_url):
            errors.append(
                "Meta должен скачать медиа по публичному HTTPS URL; настройте внешний APP_BASE_URL/reverse proxy"
            )
            break
    return errors


class InstagramConnector:
    channel = "instagram"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=True,
            videos=True,
            max_media=10,
            requires_public_media=True,
            notes=("Поддерживаются одиночное изображение, Reel и carousel из изображений.",),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("Instagram не подключён через Meta OAuth")
        if not request.config.get("facebook_page_id"):
            errors.append("Укажите Facebook Page ID, связанную с Instagram Professional account")
        if not 1 <= len(request.media) <= 10:
            errors.append("Instagram: выберите от 1 до 10 медиа")
        if len(request.media) > 1 and any(not item.is_image for item in request.media):
            errors.append("Текущий carousel Instagram поддерживает несколько изображений; Reel публикуется отдельно")
        if len(request.media) == 1 and not (request.media[0].is_image or request.media[0].is_video):
            errors.append("Instagram: неподдерживаемый формат медиа")
        if len(request.text) > 2200:
            errors.append("Instagram caption не должен превышать 2200 символов")
        errors.extend(_media_url_errors(request))
        return errors

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth:
        if not request.config.get("access_token") or not request.config.get("facebook_page_id"):
            raise PermanentPublishError("Подключите Meta OAuth и укажите Facebook Page ID")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            page_id, page_token, ig_id, page_name = await _resolve_page(client, request.config)
            if not ig_id:
                raise PermanentPublishError("У выбранной Facebook Page не найден связанный Instagram Professional account")
            profile = await _graph_request(
                client,
                "GET",
                ig_id,
                page_token,
                params={"fields": "id,username"},
            )
            return ConnectorHealth(
                ok=True,
                message="Instagram Professional account доступен",
                details={
                    "page_id": page_id,
                    "page_name": page_name,
                    "instagram_user_id": ig_id,
                    "username": profile.get("username"),
                },
            )
        finally:
            if owned:
                await client.aclose()

    async def _create_container(
        self,
        client: httpx.AsyncClient,
        ig_id: str,
        page_token: str,
        request: PublishRequest,
    ) -> str:
        if len(request.media) == 1:
            item = request.media[0]
            data: dict = {"caption": request.text}
            if item.is_video:
                data.update(
                    {
                        "media_type": "REELS",
                        "video_url": item.public_url,
                        "share_to_feed": "true",
                    }
                )
            else:
                data["image_url"] = item.public_url
            body = await _graph_request(client, "POST", f"{ig_id}/media", page_token, data=data)
            container_id = str(body.get("id") or "")
            if not container_id:
                raise TransientPublishError("Instagram не вернул container id")
            return container_id

        children: list[str] = []
        for item in request.media:
            body = await _graph_request(
                client,
                "POST",
                f"{ig_id}/media",
                page_token,
                data={"image_url": item.public_url, "is_carousel_item": "true"},
            )
            child_id = str(body.get("id") or "")
            if not child_id:
                raise TransientPublishError("Instagram не вернул child container id")
            children.append(child_id)
        parent = await _graph_request(
            client,
            "POST",
            f"{ig_id}/media",
            page_token,
            data={"media_type": "CAROUSEL", "children": ",".join(children), "caption": request.text},
        )
        container_id = str(parent.get("id") or "")
        if not container_id:
            raise TransientPublishError("Instagram не вернул carousel container id")
        return container_id

    async def publish(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> PublishResult:
        ensure_valid(self, request)
        owned = client is None
        client = client or httpx.AsyncClient(timeout=40)
        try:
            _page_id, page_token, ig_id, _page_name = await _resolve_page(client, request.config)
            if not ig_id:
                raise PermanentPublishError("Не найден Instagram Professional account для выбранной Page")
            container_id = await self._create_container(client, ig_id, page_token, request)
            return PublishResult(
                external_post_id=container_id,
                processing=True,
                poll_after_seconds=10,
                message="Instagram обрабатывает media container",
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
        if not request.config.get("access_token") or not request.config.get("facebook_page_id"):
            raise PermanentPublishError("Meta connection is incomplete")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=30)
        try:
            _page_id, page_token, ig_id, _page_name = await _resolve_page(client, request.config)
            if not ig_id:
                raise PermanentPublishError("Не найден Instagram Professional account")
            container = await _graph_request(
                client,
                "GET",
                external_post_id,
                page_token,
                params={"fields": "status_code,status"},
            )
            code = str(container.get("status_code") or "").upper()
            message = str(container.get("status") or "")[:500]
            if code in {"ERROR", "EXPIRED"}:
                return PublishStatus(state="failed", message=message or f"Instagram container: {code}")
            if code != "FINISHED":
                return PublishStatus(state="processing", message=message, poll_after_seconds=10)

            published = await _graph_request(
                client,
                "POST",
                f"{ig_id}/media_publish",
                page_token,
                data={"creation_id": external_post_id},
            )
            media_id = str(published.get("id") or "")
            if not media_id:
                raise TransientPublishError("Instagram не вернул published media id")
            media = await _graph_request(
                client,
                "GET",
                media_id,
                page_token,
                params={"fields": "id,permalink"},
            )
            return PublishStatus(
                state="published",
                message=f"Instagram media id: {media_id}",
                external_url=media.get("permalink"),
            )
        finally:
            if owned:
                await client.aclose()


class FacebookConnector:
    channel = "facebook"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=True,
            videos=False,
            max_media=10,
            requires_public_media=True,
            notes=("Поддерживаются текстовые Page posts и до 10 изображений.",),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("Facebook не подключён через Meta OAuth")
        if not request.config.get("facebook_page_id"):
            errors.append("Укажите Facebook Page ID")
        if len(request.media) > 10:
            errors.append("Facebook: не более 10 изображений")
        if any(not item.is_image for item in request.media):
            errors.append("Текущий Facebook adapter поддерживает автоматическую загрузку изображений")
        if not request.text.strip() and not request.media:
            errors.append("Публикация Facebook не может быть пустой")
        errors.extend(_media_url_errors(request))
        return errors

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth:
        if not request.config.get("access_token") or not request.config.get("facebook_page_id"):
            raise PermanentPublishError("Подключите Meta OAuth и укажите Facebook Page ID")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            page_id, _page_token, ig_id, page_name = await _resolve_page(client, request.config)
            return ConnectorHealth(
                ok=True,
                message="Facebook Page доступна",
                details={"page_id": page_id, "page_name": page_name, "instagram_user_id": ig_id},
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
        owned = client is None
        client = client or httpx.AsyncClient(timeout=40)
        try:
            page_id, page_token, _ig_id, _page_name = await _resolve_page(client, request.config)
            data: dict = {"message": request.text}
            if request.media:
                photo_ids: list[str] = []
                for item in request.media:
                    photo = await _graph_request(
                        client,
                        "POST",
                        f"{page_id}/photos",
                        page_token,
                        data={"url": item.public_url, "published": "false"},
                    )
                    photo_id = str(photo.get("id") or "")
                    if not photo_id:
                        raise TransientPublishError("Facebook не вернул media_fbid")
                    photo_ids.append(photo_id)
                for index, photo_id in enumerate(photo_ids):
                    data[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})
            post = await _graph_request(client, "POST", f"{page_id}/feed", page_token, data=data)
            post_id = str(post.get("id") or "")
            if not post_id:
                raise TransientPublishError("Facebook не вернул post id")
            suffix = post_id.split("_", 1)[-1]
            return PublishResult(
                external_post_id=post_id,
                external_url=f"https://www.facebook.com/{page_id}/posts/{suffix}",
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
        if not request.config.get("access_token") or not request.config.get("facebook_page_id"):
            raise PermanentPublishError("Meta connection is incomplete")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            _page_id, page_token, _ig_id, _page_name = await _resolve_page(client, request.config)
            try:
                post = await _graph_request(
                    client,
                    "GET",
                    external_post_id,
                    page_token,
                    params={"fields": "id,permalink_url"},
                )
            except PermanentPublishError as exc:
                if "HTTP 404" in str(exc):
                    return PublishStatus(state="failed", message="Facebook post не найден")
                raise
            return PublishStatus(
                state="published",
                external_url=post.get("permalink_url"),
            )
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {
    "instagram": InstagramConnector(),
    "facebook": FacebookConnector(),
}
