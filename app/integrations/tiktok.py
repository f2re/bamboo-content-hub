from __future__ import annotations

import ipaddress
import os
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
)

API_BASE = "https://open.tiktokapis.com"
MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
DEFAULT_CHUNK = 32 * 1024 * 1024
_MAX_VIDEO_CAPTION_UTF16 = 2200
_MAX_PHOTO_TITLE_UTF16 = 90
_MAX_PHOTO_DESCRIPTION_UTF16 = 4000
_TRANSIENT_CODES = {"internal_error", "rate_limit_exceeded"}


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _public_https(url: str) -> bool:
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


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def _raise_tiktok_error(body: dict) -> None:
    error = body.get("error")
    if not isinstance(error, dict):
        raise TransientPublishError("TikTok API returned an invalid response")
    code = str(error.get("code") or "")
    if code in {"", "ok"}:
        return
    message = str(error.get("message") or code).replace("\n", " ").strip()[:500]
    rendered = f"TikTok API error {code}: {message}"
    if code in _TRANSIENT_CODES:
        raise TransientPublishError(rendered)
    raise PermanentPublishError(rendered)


async def _api_post(
    client: httpx.AsyncClient,
    path: str,
    token: str,
    payload: dict | None = None,
) -> dict:
    try:
        response = await client.post(
            f"{API_BASE}{path}",
            headers=_headers(token),
            json=payload or {},
        )
    except httpx.RequestError as exc:
        raise TransientPublishError(f"TikTok network error: {type(exc).__name__}") from exc
    if response.status_code in {408, 429} or response.status_code >= 500:
        raise TransientPublishError(f"TikTok API returned HTTP {response.status_code}")
    if not response.is_success:
        raise PermanentPublishError(f"TikTok API returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise TransientPublishError("TikTok API returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise TransientPublishError("TikTok API returned invalid response")
    _raise_tiktok_error(body)
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def _video_chunk_plan(size: int) -> tuple[int, int]:
    if size <= 0:
        raise PermanentPublishError("TikTok video file is empty")
    if size < MIN_CHUNK:
        return size, 1
    if size <= MAX_CHUNK:
        return size, 1
    chunk_size = DEFAULT_CHUNK
    total = size // chunk_size
    if total < 1:
        total = 1
    if total > 1000:
        raise PermanentPublishError("TikTok video requires more than 1000 upload chunks")
    return chunk_size, total


class TikTokConnector:
    channel = "tiktok"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=True,
            videos=True,
            max_media=35,
            requires_public_media=True,
            notes=(
                "Privacy level must be explicitly selected from the creator's current options.",
                "Commercial-content declarations and direct-post consent are required.",
                "Unaudited TikTok clients are restricted by TikTok to private visibility.",
            ),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("TikTok не подключён: отсутствует access token")
        if not str(request.config.get("privacy_level") or "").strip():
            errors.append("Выберите privacy_level TikTok перед публикацией")
        if "brand_content_toggle" not in request.config:
            errors.append("Укажите, является ли публикация платным партнёрством TikTok")
        if "brand_organic_toggle" not in request.config:
            errors.append("Укажите, продвигает ли публикация собственный бизнес автора")
        if request.content.get("direct_post_consent") is not True:
            errors.append("Для TikTok требуется явное согласие пользователя на Direct Post")
        if not request.media:
            errors.append("TikTok: выберите видео или фотографии")
            return errors

        videos = [item for item in request.media if item.is_video]
        images = [item for item in request.media if item.is_image]
        if videos and images:
            errors.append("TikTok не принимает смешанную публикацию фото и видео")
        elif videos:
            if len(videos) != 1 or len(request.media) != 1:
                errors.append("TikTok Direct Post поддерживает одно видео за публикацию")
            if videos[0].mime_type not in {"video/mp4", "video/quicktime", "video/webm"}:
                errors.append("TikTok: видео должно быть MP4, MOV или WebM")
            if _utf16_units(request.text) > _MAX_VIDEO_CAPTION_UTF16:
                errors.append("TikTok video caption превышает 2200 UTF-16 символов")
        elif images:
            if len(images) > 35:
                errors.append("TikTok: не более 35 фотографий")
            if any(item.mime_type not in {"image/jpeg", "image/webp"} for item in images):
                errors.append("TikTok photo post поддерживает JPEG и WebP")
            if any(not _public_https(item.public_url) for item in images):
                errors.append("TikTok должен скачать фотографии по публичному HTTPS URL подтверждённого домена")
            title = str(request.content.get("title") or "")
            description = str(request.content.get("caption") or request.text or "")
            if _utf16_units(title) > _MAX_PHOTO_TITLE_UTF16:
                errors.append("TikTok photo title превышает 90 UTF-16 символов")
            if _utf16_units(description) > _MAX_PHOTO_DESCRIPTION_UTF16:
                errors.append("TikTok photo description превышает 4000 UTF-16 символов")
        else:
            errors.append("TikTok: неподдерживаемый media type")
        return errors

    async def _creator_info(
        self,
        client: httpx.AsyncClient,
        token: str,
    ) -> dict:
        return await _api_post(client, "/v2/post/publish/creator_info/query/", token)

    def _post_info(self, request: PublishRequest, creator: dict) -> dict:
        privacy = str(request.config.get("privacy_level") or "").strip()
        options = creator.get("privacy_level_options") or []
        if privacy not in options:
            raise PermanentPublishError(
                "Выбранный privacy_level TikTok больше недоступен; обновите настройки подключения"
            )
        post_info = {
            "privacy_level": privacy,
            "disable_comment": bool(request.config.get("disable_comment"))
            or bool(creator.get("comment_disabled")),
            "disable_duet": bool(request.config.get("disable_duet"))
            or bool(creator.get("duet_disabled")),
            "disable_stitch": bool(request.config.get("disable_stitch"))
            or bool(creator.get("stitch_disabled")),
            "brand_content_toggle": bool(request.config.get("brand_content_toggle")),
            "brand_organic_toggle": bool(request.config.get("brand_organic_toggle")),
        }
        if "is_aigc" in request.config:
            post_info["is_aigc"] = bool(request.config.get("is_aigc"))
        return post_info

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth:
        token = str(request.config.get("access_token") or "")
        if not token:
            raise PermanentPublishError("TikTok не подключён: отсутствует access token")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            creator = await self._creator_info(client, token)
            return ConnectorHealth(
                ok=True,
                message="TikTok creator доступен",
                details={
                    "username": creator.get("creator_username"),
                    "nickname": creator.get("creator_nickname"),
                    "privacy_level_options": creator.get("privacy_level_options") or [],
                    "comment_disabled": creator.get("comment_disabled"),
                    "duet_disabled": creator.get("duet_disabled"),
                    "stitch_disabled": creator.get("stitch_disabled"),
                    "max_video_post_duration_sec": creator.get("max_video_post_duration_sec"),
                },
            )
        finally:
            if owned:
                await client.aclose()

    async def _upload_video(
        self,
        client: httpx.AsyncClient,
        request: PublishRequest,
        creator: dict,
    ) -> PublishResult:
        item = request.media[0]
        try:
            size = os.path.getsize(item.path)
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать TikTok video file") from exc
        chunk_size, total_chunks = _video_chunk_plan(size)
        post_info = self._post_info(request, creator)
        post_info["title"] = request.text
        init = await _api_post(
            client,
            "/v2/post/publish/video/init/",
            str(request.config["access_token"]),
            {
                "post_info": post_info,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                },
            },
        )
        publish_id = str(init.get("publish_id") or "")
        upload_url = str(init.get("upload_url") or "")
        if not publish_id or not upload_url:
            raise TransientPublishError("TikTok не вернул publish_id/upload_url")

        try:
            with open(item.path, "rb") as handle:
                start = 0
                for index in range(total_chunks):
                    if index == total_chunks - 1:
                        body = handle.read()
                    else:
                        body = handle.read(chunk_size)
                    if not body:
                        raise TransientPublishError("TikTok upload stopped before the file ended")
                    end = start + len(body) - 1
                    try:
                        response = await client.put(
                            upload_url,
                            headers={
                                "Content-Type": item.mime_type,
                                "Content-Length": str(len(body)),
                                "Content-Range": f"bytes {start}-{end}/{size}",
                            },
                            content=body,
                        )
                    except httpx.RequestError as exc:
                        raise TransientPublishError(
                            f"TikTok upload network error: {type(exc).__name__}"
                        ) from exc
                    expected = 201 if index == total_chunks - 1 else 206
                    if response.status_code != expected:
                        if response.status_code in {408, 416, 429} or response.status_code >= 500:
                            raise TransientPublishError(
                                f"TikTok upload returned HTTP {response.status_code}"
                            )
                        raise PermanentPublishError(
                            f"TikTok upload returned HTTP {response.status_code}"
                        )
                    start = end + 1
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать TikTok video file") from exc
        if start != size:
            raise TransientPublishError("TikTok upload byte count does not match the video size")
        return PublishResult(
            external_post_id=publish_id,
            processing=True,
            poll_after_seconds=20,
            message="TikTok обрабатывает публикацию",
        )

    async def _publish_photos(
        self,
        client: httpx.AsyncClient,
        request: PublishRequest,
        creator: dict,
    ) -> PublishResult:
        post_info = self._post_info(request, creator)
        post_info.update(
            {
                "title": str(request.content.get("title") or ""),
                "description": str(request.content.get("caption") or request.text or ""),
            }
        )
        data = await _api_post(
            client,
            "/v2/post/publish/content/init/",
            str(request.config["access_token"]),
            {
                "media_type": "PHOTO",
                "post_mode": "DIRECT_POST",
                "post_info": post_info,
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 0,
                    "photo_images": [item.public_url for item in request.media],
                },
            },
        )
        publish_id = str(data.get("publish_id") or "")
        if not publish_id:
            raise TransientPublishError("TikTok не вернул publish_id")
        return PublishResult(
            external_post_id=publish_id,
            processing=True,
            poll_after_seconds=20,
            message="TikTok обрабатывает photo post",
        )

    async def publish(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> PublishResult:
        ensure_valid(self, request)
        owned = client is None
        client = client or httpx.AsyncClient(timeout=90)
        try:
            creator = await self._creator_info(client, str(request.config["access_token"]))
            if request.media[0].is_video:
                return await self._upload_video(client, request, creator)
            return await self._publish_photos(client, request, creator)
        finally:
            if owned:
                await client.aclose()

    async def status(
        self,
        request: PublishRequest,
        external_post_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> PublishStatus:
        token = str(request.config.get("access_token") or "")
        if not token:
            raise PermanentPublishError("TikTok не подключён")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            data = await _api_post(
                client,
                "/v2/post/publish/status/fetch/",
                token,
                {"publish_id": external_post_id},
            )
            state = str(data.get("status") or "")
            if state == "PUBLISH_COMPLETE":
                post_ids = data.get("publicaly_available_post_id") or []
                post_id = str(post_ids[0]) if isinstance(post_ids, list) and post_ids else ""
                message = f"TikTok post id: {post_id}" if post_id else "TikTok publication complete"
                return PublishStatus(state="published", message=message)
            if state == "FAILED":
                reason = str(data.get("fail_reason") or "TikTok rejected the publication")[:500]
                return PublishStatus(state="failed", message=reason)
            return PublishStatus(
                state="processing",
                message=state or "TikTok processing",
                poll_after_seconds=20,
            )
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {"tiktok": TikTokConnector()}
