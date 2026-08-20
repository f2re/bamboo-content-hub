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
MAX_FINAL_CHUNK = 128 * 1024 * 1024
DEFAULT_CHUNK = 32 * 1024 * 1024
MAX_VIDEO_BYTES = 4 * 1024 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
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


def _request_value(request: PublishRequest, key: str, default=None):
    if key in request.content:
        return request.content[key]
    return request.config.get(key, default)


def _request_bool(request: PublishRequest, key: str) -> bool:
    return bool(_request_value(request, key, False))


def _privacy_level(request: PublishRequest) -> str:
    return str(_request_value(request, "privacy_level", "") or "").strip()


def _raise_tiktok_error(body: dict) -> None:
    error = body.get("error")
    if not isinstance(error, dict):
        raise TransientPublishError("TikTok API вернул некорректный ответ")
    code = str(error.get("code") or "")
    if code in {"", "ok"}:
        return
    message = str(error.get("message") or code).replace("\n", " ").strip()[:500]
    rendered = f"Ошибка TikTok API {code}: {message}"
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
        raise TransientPublishError(f"Сетевая ошибка TikTok: {type(exc).__name__}") from exc
    if response.status_code in {408, 429} or response.status_code >= 500:
        raise TransientPublishError(f"TikTok API вернул HTTP {response.status_code}")
    if not response.is_success:
        raise PermanentPublishError(f"TikTok API вернул HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise TransientPublishError("TikTok API вернул не JSON") from exc
    if not isinstance(body, dict):
        raise TransientPublishError("TikTok API вернул некорректный ответ")
    _raise_tiktok_error(body)
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def _video_chunk_plan(size: int) -> tuple[int, int]:
    if size <= 0:
        raise PermanentPublishError("Видео TikTok пустое")
    if size > MAX_VIDEO_BYTES:
        raise PermanentPublishError("Видео TikTok превышает 4 ГБ")
    if size < MIN_CHUNK:
        return size, 1
    if size <= MAX_CHUNK:
        return size, 1
    chunk_size = DEFAULT_CHUNK
    total = size // chunk_size
    if total < 1:
        total = 1
    final_size = size - chunk_size * (total - 1)
    if final_size > MAX_FINAL_CHUNK:
        total += 1
        final_size = size - chunk_size * (total - 1)
    if total > 1000 or final_size <= 0:
        raise PermanentPublishError("Видео TikTok требует недопустимое число частей")
    return chunk_size, total


def _local_size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


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
                "Видимость выбирается из актуальных настроек аккаунта перед каждой публикацией.",
                "Перед Direct Post нужны декларация коммерческого контента и явное согласие.",
                "Фото должны быть доступны по HTTPS с подтверждённого в TikTok домена.",
                "Не прошедшие аудит приложения TikTok могут публиковать только с видимостью «Только я».",
            ),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("TikTok не подключён: отсутствует access token")

        privacy = _privacy_level(request)
        if not privacy:
            errors.append("Выберите видимость TikTok перед публикацией")
        if request.content.get("direct_post_consent") is not True:
            errors.append("Подтвердите отправку выбранных материалов в TikTok")

        commercial = request.content.get("commercial_content_toggle")
        if commercial is None:
            errors.append("Укажите, содержит ли публикация коммерческое продвижение")
        branded = _request_bool(request, "brand_content_toggle")
        own_brand = _request_bool(request, "brand_organic_toggle")
        if commercial is True and not (branded or own_brand):
            errors.append("Для коммерческой публикации выберите свой бренд, сторонний бренд или оба")
        if commercial is False and (branded or own_brand):
            errors.append("Отключите тип коммерческого контента или включите его декларацию")
        if branded and privacy == "SELF_ONLY":
            errors.append("Платное партнёрство TikTok нельзя публиковать с видимостью «Только я»")

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
            size = _local_size(videos[0].path)
            if size is not None and size > MAX_VIDEO_BYTES:
                errors.append("TikTok: видео превышает 4 ГБ")
            if _utf16_units(request.text) > _MAX_VIDEO_CAPTION_UTF16:
                errors.append("Подпись видео TikTok превышает 2200 UTF-16 символов")
        elif images:
            if len(images) > 35:
                errors.append("TikTok: не более 35 фотографий")
            if any(item.mime_type not in {"image/jpeg", "image/webp"} for item in images):
                errors.append("TikTok поддерживает фотографии JPEG и WebP")
            if any(not _public_https(item.public_url) for item in images):
                errors.append(
                    "TikTok должен скачать фотографии по публичному HTTPS URL подтверждённого домена"
                )
            if any((_local_size(item.path) or 0) > MAX_IMAGE_BYTES for item in images):
                errors.append("TikTok: размер каждой фотографии не должен превышать 20 МБ")
            title = str(request.content.get("title") or "")
            description = request.text
            if _utf16_units(title) > _MAX_PHOTO_TITLE_UTF16:
                errors.append("Заголовок фото TikTok превышает 90 UTF-16 символов")
            if _utf16_units(description) > _MAX_PHOTO_DESCRIPTION_UTF16:
                errors.append("Описание фото TikTok превышает 4000 UTF-16 символов")
            cover = request.content.get("photo_cover_index", 0)
            if not isinstance(cover, int) or not 0 <= cover < len(images):
                errors.append("Выберите корректную обложку публикации TikTok")
        else:
            errors.append("TikTok: неподдерживаемый тип медиа")
        return errors

    async def _creator_info(
        self,
        client: httpx.AsyncClient,
        token: str,
    ) -> dict:
        return await _api_post(client, "/v2/post/publish/creator_info/query/", token)

    def _post_info(
        self,
        request: PublishRequest,
        creator: dict,
        *,
        video: bool,
    ) -> dict:
        privacy = _privacy_level(request)
        options = creator.get("privacy_level_options") or []
        if privacy not in options:
            raise PermanentPublishError(
                "Выбранная видимость TikTok больше недоступна; обновите сведения об аккаунте"
            )
        post_info = {
            "privacy_level": privacy,
            "disable_comment": _request_bool(request, "disable_comment")
            or bool(creator.get("comment_disabled")),
            "brand_content_toggle": _request_bool(request, "brand_content_toggle"),
            "brand_organic_toggle": _request_bool(request, "brand_organic_toggle"),
        }
        if video:
            post_info.update(
                {
                    "disable_duet": _request_bool(request, "disable_duet")
                    or bool(creator.get("duet_disabled")),
                    "disable_stitch": _request_bool(request, "disable_stitch")
                    or bool(creator.get("stitch_disabled")),
                }
            )
            if "is_aigc" in request.content:
                post_info["is_aigc"] = bool(request.content.get("is_aigc"))
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
                message="Аккаунт TikTok доступен",
                details={
                    "username": creator.get("creator_username"),
                    "nickname": creator.get("creator_nickname"),
                    "avatar_url": creator.get("creator_avatar_url"),
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
            raise PermanentPublishError("Не удалось прочитать видео TikTok") from exc
        chunk_size, total_chunks = _video_chunk_plan(size)
        post_info = self._post_info(request, creator, video=True)
        post_info["title"] = request.text
        if request.content.get("video_cover_timestamp_ms") is not None:
            post_info["video_cover_timestamp_ms"] = int(
                request.content["video_cover_timestamp_ms"]
            )
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
                    body = handle.read() if index == total_chunks - 1 else handle.read(chunk_size)
                    if not body:
                        raise TransientPublishError("Загрузка TikTok остановилась до конца файла")
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
                            f"Сетевая ошибка загрузки TikTok: {type(exc).__name__}"
                        ) from exc
                    expected = 201 if index == total_chunks - 1 else 206
                    if response.status_code != expected:
                        if response.status_code in {408, 416, 429} or response.status_code >= 500:
                            raise TransientPublishError(
                                f"Загрузка TikTok вернула HTTP {response.status_code}"
                            )
                        raise PermanentPublishError(
                            f"Загрузка TikTok вернула HTTP {response.status_code}"
                        )
                    start = end + 1
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать видео TikTok") from exc
        if start != size:
            raise TransientPublishError("Число переданных байтов TikTok не совпадает с размером видео")
        return PublishResult(
            external_post_id=publish_id,
            processing=True,
            poll_after_seconds=20,
            message="TikTok обрабатывает публикацию; это может занять несколько минут",
        )

    async def _publish_photos(
        self,
        client: httpx.AsyncClient,
        request: PublishRequest,
        creator: dict,
    ) -> PublishResult:
        post_info = self._post_info(request, creator, video=False)
        post_info.update(
            {
                "title": str(request.content.get("title") or ""),
                "description": request.text,
                "auto_add_music": bool(request.content.get("auto_add_music", False)),
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
                    "photo_cover_index": int(request.content.get("photo_cover_index", 0)),
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
            message="TikTok обрабатывает публикацию; это может занять несколько минут",
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
                message = f"TikTok: публикация готова, ID {post_id}" if post_id else "TikTok: публикация готова"
                return PublishStatus(state="published", message=message)
            if state == "FAILED":
                reason = str(data.get("fail_reason") or "TikTok отклонил публикацию")[:500]
                return PublishStatus(state="failed", message=reason)
            return PublishStatus(
                state="processing",
                message=state or "TikTok обрабатывает публикацию",
                poll_after_seconds=20,
            )
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {"tiktok": TikTokConnector()}
