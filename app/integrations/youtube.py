from __future__ import annotations

import os
import re

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

API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
MAX_RECOVERY_ATTEMPTS = 4


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _privacy_status(request: PublishRequest) -> str:
    return str(
        request.content.get("privacy_status")
        or request.content.get("privacy")
        or request.config.get("youtube_privacy_status")
        or ""
    ).lower()


def _tags_length(tags: list[str]) -> int:
    rendered = []
    for tag in tags:
        value = str(tag).strip()
        if not value:
            continue
        rendered.append(f'"{value}"' if " " in value else value)
    return len(",".join(rendered))


def _next_offset(range_header: str | None) -> int | None:
    if not range_header:
        return None
    match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header.strip())
    if not match:
        return None
    start, end = (int(value) for value in match.groups())
    if start != 0 or end < start:
        return None
    return end + 1


def _video_id(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("id") or "") if isinstance(body, dict) else ""


class YouTubeConnector:
    channel = "youtube"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=False,
            videos=True,
            max_media=1,
            notes=(
                "YouTube принимает одно видео за публикацию.",
                "Заголовок, описание и видимость выбираются пользователем перед отправкой.",
                "Загрузка выполняется частями через resumable upload session.",
                "Непроверенные проекты Google могут быть ограничены видимостью private.",
            ),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("YouTube не подключён: отсутствует access token")
        if len(request.media) != 1 or not request.media[0].is_video:
            errors.append("Для YouTube выберите ровно одно видео")
        elif not request.media[0].mime_type.startswith("video/"):
            errors.append("YouTube: выбранный файл не является видео")

        title = str(request.content.get("title") or request.text or "").strip()
        description = str(request.content.get("description") or "")
        if not title:
            errors.append("Укажите заголовок YouTube")
        if len(title) > 100:
            errors.append("Заголовок YouTube не должен превышать 100 символов")
        if "<" in title or ">" in title:
            errors.append("Заголовок YouTube не должен содержать символы < и >")
        if len(description.encode("utf-8")) > 5000:
            errors.append("Описание YouTube не должно превышать 5000 байт UTF-8")
        if "<" in description or ">" in description:
            errors.append("Описание YouTube не должно содержать символы < и >")

        tags = request.content.get("tags") or []
        if not isinstance(tags, list):
            errors.append("Теги YouTube должны быть списком")
        elif _tags_length([str(tag) for tag in tags]) > 500:
            errors.append("Общая длина тегов YouTube не должна превышать 500 символов")

        privacy = _privacy_status(request)
        if privacy not in {"private", "unlisted", "public"}:
            errors.append("Выберите видимость YouTube: private, unlisted или public")
        category_id = str(request.config.get("youtube_category_id") or "22")
        if not category_id.isdigit():
            errors.append("Категория YouTube должна быть числовым ID")
        return errors

    async def health(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> ConnectorHealth:
        token = str(request.config.get("access_token") or "")
        if not token:
            raise PermanentPublishError("YouTube не подключён: отсутствует access token")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            try:
                response = await client.get(
                    f"{API_BASE}/channels",
                    headers=_headers(token),
                    params={"part": "snippet", "mine": "true", "maxResults": 1},
                )
            except httpx.RequestError as exc:
                raise TransientPublishError(
                    f"Сетевая ошибка YouTube: {type(exc).__name__}"
                ) from exc
            raise_for_provider(response, "YouTube")
            try:
                body = response.json()
            except ValueError as exc:
                raise TransientPublishError("YouTube API вернул не JSON") from exc
            items = body.get("items") if isinstance(body, dict) else None
            if not isinstance(items, list) or not items:
                raise PermanentPublishError("Канал YouTube не найден для подключённого аккаунта")
            channel = items[0]
            snippet = channel.get("snippet") or {}
            return ConnectorHealth(
                ok=True,
                message="Канал YouTube доступен",
                details={"channel_id": channel.get("id"), "title": snippet.get("title")},
            )
        finally:
            if owned:
                await client.aclose()

    async def _query_upload(
        self,
        client: httpx.AsyncClient,
        session_url: str,
        token: str,
        size: int,
    ) -> httpx.Response:
        return await client.put(
            session_url,
            headers={
                **_headers(token),
                "Content-Length": "0",
                "Content-Range": f"bytes */{size}",
            },
            content=b"",
        )

    async def _recover_upload(
        self,
        client: httpx.AsyncClient,
        session_url: str,
        token: str,
        size: int,
    ) -> tuple[int | None, str]:
        try:
            response = await self._query_upload(client, session_url, token, size)
        except httpx.RequestError as exc:
            raise TransientPublishError(
                f"Не удалось проверить загрузку YouTube: {type(exc).__name__}"
            ) from exc
        if response.status_code == 308:
            offset = _next_offset(response.headers.get("range"))
            return (offset if offset is not None else 0), ""
        if response.status_code == 404:
            raise TransientPublishError("Сессия загрузки YouTube истекла")
        raise_for_provider(response, "YouTube")
        video_id = _video_id(response)
        if not video_id:
            raise TransientPublishError("YouTube завершил загрузку без video id")
        return None, video_id

    async def _upload_file(
        self,
        client: httpx.AsyncClient,
        session_url: str,
        token: str,
        path: str,
        mime_type: str,
        size: int,
    ) -> str:
        offset = 0
        recovery_attempts = 0
        try:
            with open(path, "rb") as handle:
                while offset < size:
                    handle.seek(offset)
                    body = handle.read(min(UPLOAD_CHUNK_SIZE, size - offset))
                    if not body:
                        raise TransientPublishError("Видео YouTube закончилось раньше ожидаемого")
                    end = offset + len(body) - 1
                    try:
                        response = await client.put(
                            session_url,
                            headers={
                                **_headers(token),
                                "Content-Length": str(len(body)),
                                "Content-Type": mime_type,
                                "Content-Range": f"bytes {offset}-{end}/{size}",
                            },
                            content=body,
                        )
                    except httpx.RequestError:
                        recovery_attempts += 1
                        if recovery_attempts > MAX_RECOVERY_ATTEMPTS:
                            raise TransientPublishError(
                                "YouTube не подтвердил состояние загрузки после сетевой ошибки"
                            )
                        recovered_offset, video_id = await self._recover_upload(
                            client, session_url, token, size
                        )
                        if video_id:
                            return video_id
                        offset = recovered_offset or 0
                        continue

                    if response.status_code == 308:
                        next_offset = _next_offset(response.headers.get("range"))
                        if next_offset is None or not offset < next_offset <= size:
                            raise TransientPublishError(
                                "YouTube вернул некорректный Range возобновляемой загрузки"
                            )
                        offset = next_offset
                        recovery_attempts = 0
                        continue

                    if response.status_code >= 500:
                        recovery_attempts += 1
                        if recovery_attempts > MAX_RECOVERY_ATTEMPTS:
                            raise TransientPublishError(
                                f"Загрузка YouTube вернула HTTP {response.status_code}"
                            )
                        recovered_offset, video_id = await self._recover_upload(
                            client, session_url, token, size
                        )
                        if video_id:
                            return video_id
                        offset = recovered_offset or 0
                        continue

                    raise_for_provider(response, "YouTube")
                    video_id = _video_id(response)
                    if not video_id:
                        raise TransientPublishError("YouTube не вернул video id")
                    return video_id
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать видео YouTube") from exc

        recovered_offset, video_id = await self._recover_upload(
            client, session_url, token, size
        )
        if video_id:
            return video_id
        raise TransientPublishError(
            f"YouTube подтвердил только {recovered_offset or 0} из {size} байт"
        )

    async def publish(
        self,
        request: PublishRequest,
        client: httpx.AsyncClient | None = None,
    ) -> PublishResult:
        ensure_valid(self, request)
        item = request.media[0]
        token = str(request.config["access_token"])
        title = str(request.content.get("title") or request.text).strip()
        description = str(request.content.get("description") or "")
        tags = request.content.get("tags") or []
        privacy = _privacy_status(request)
        category_id = str(request.config.get("youtube_category_id") or "22")
        try:
            size = os.path.getsize(item.path)
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать видео YouTube") from exc
        if size <= 0:
            raise PermanentPublishError("Видео YouTube пустое")

        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
                "categoryId": category_id,
            },
            "status": {"privacyStatus": privacy},
        }
        owned = client is None
        client = client or httpx.AsyncClient(timeout=120)
        try:
            try:
                init = await client.post(
                    UPLOAD_URL,
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers={
                        **_headers(token),
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Length": str(size),
                        "X-Upload-Content-Type": item.mime_type,
                    },
                    json=metadata,
                )
            except httpx.RequestError as exc:
                raise TransientPublishError(
                    f"Не удалось начать загрузку YouTube: {type(exc).__name__}"
                ) from exc
            raise_for_provider(init, "YouTube")
            session_url = init.headers.get("location")
            if not session_url:
                raise TransientPublishError("YouTube не вернул Location для resumable upload")
            video_id = await self._upload_file(
                client,
                session_url,
                token,
                item.path,
                item.mime_type,
                size,
            )
            return PublishResult(
                external_post_id=video_id,
                external_url=f"https://www.youtube.com/watch?v={video_id}",
                processing=True,
                poll_after_seconds=15,
                message="YouTube обрабатывает загруженное видео",
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
        token = str(request.config.get("access_token") or "")
        if not token:
            raise PermanentPublishError("YouTube не подключён")
        owned = client is None
        client = client or httpx.AsyncClient(timeout=20)
        try:
            try:
                response = await client.get(
                    f"{API_BASE}/videos",
                    headers=_headers(token),
                    params={
                        "part": "status,processingDetails",
                        "id": external_post_id,
                    },
                )
            except httpx.RequestError as exc:
                raise TransientPublishError(
                    f"Сетевая ошибка статуса YouTube: {type(exc).__name__}"
                ) from exc
            raise_for_provider(response, "YouTube")
            try:
                body = response.json()
            except ValueError as exc:
                raise TransientPublishError("YouTube API вернул не JSON") from exc
            items = body.get("items") if isinstance(body, dict) else None
            if not isinstance(items, list) or not items:
                return PublishStatus(state="failed", message="Видео YouTube не найдено")
            video = items[0]
            status = video.get("status") or {}
            processing = video.get("processingDetails") or {}
            upload_status = str(status.get("uploadStatus") or "").lower()
            processing_status = str(processing.get("processingStatus") or "").lower()
            if upload_status in {"failed", "rejected", "deleted"} or processing_status in {
                "failed",
                "terminated",
            }:
                reason = str(
                    status.get("rejectionReason")
                    or status.get("failureReason")
                    or processing.get("processingFailureReason")
                    or processing_status
                    or upload_status
                )
                return PublishStatus(state="failed", message=f"YouTube: {reason}"[:500])
            if processing_status == "processing" or upload_status == "uploaded":
                return PublishStatus(
                    state="processing",
                    message=processing_status or upload_status,
                    poll_after_seconds=15,
                )
            if upload_status == "processed" or processing_status == "succeeded":
                return PublishStatus(
                    state="published",
                    external_url=f"https://www.youtube.com/watch?v={external_post_id}",
                )
            return PublishStatus(
                state="processing",
                message=processing_status or upload_status or "YouTube обрабатывает видео",
                poll_after_seconds=15,
            )
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {"youtube": YouTubeConnector()}
