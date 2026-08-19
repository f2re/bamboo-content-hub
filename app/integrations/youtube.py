from __future__ import annotations

import os

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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class YouTubeConnector:
    channel = "youtube"

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            text=True,
            images=False,
            videos=True,
            max_media=1,
            notes=(
                "YouTube uploads one video per publication.",
                "Uploads from unverified API projects can be restricted to private until Google audit requirements are met.",
            ),
        )

    def validate(self, request: PublishRequest) -> list[str]:
        errors: list[str] = []
        if not request.config.get("access_token"):
            errors.append("YouTube не подключён: отсутствует access token")
        if len(request.media) != 1 or not request.media[0].is_video:
            errors.append("Для YouTube выберите ровно одно видео")
        title = str(request.content.get("title") or request.text or "").strip()
        description = str(request.content.get("description") or "")
        if not title:
            errors.append("Укажите заголовок YouTube")
        if len(title) > 100:
            errors.append("Заголовок YouTube не должен превышать 100 символов")
        if len(description) > 5000:
            errors.append("Описание YouTube не должно превышать 5000 символов")
        privacy = str(request.config.get("youtube_privacy_status") or "private").lower()
        if privacy not in {"private", "unlisted", "public"}:
            errors.append("YouTube privacy status: private, unlisted или public")
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
                raise TransientPublishError(f"YouTube network error: {type(exc).__name__}") from exc
            raise_for_provider(response, "YouTube")
            body = response.json()
            items = body.get("items") if isinstance(body, dict) else None
            if not isinstance(items, list) or not items:
                raise PermanentPublishError("YouTube channel не найден для подключённого аккаунта")
            channel = items[0]
            snippet = channel.get("snippet") or {}
            return ConnectorHealth(
                ok=True,
                message="YouTube channel доступен",
                details={"channel_id": channel.get("id"), "title": snippet.get("title")},
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
        item = request.media[0]
        token = str(request.config["access_token"])
        title = str(request.content.get("title") or request.text).strip()
        description = str(request.content.get("description") or "")
        tags = request.content.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        privacy = str(request.config.get("youtube_privacy_status") or "private").lower()
        category_id = str(request.config.get("youtube_category_id") or "22")
        try:
            size = os.path.getsize(item.path)
        except OSError as exc:
            raise PermanentPublishError("Не удалось прочитать YouTube video file") from exc
        if size <= 0:
            raise PermanentPublishError("YouTube video file is empty")

        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": [str(tag) for tag in tags if str(tag).strip()],
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
                raise TransientPublishError(f"YouTube upload init network error: {type(exc).__name__}") from exc
            raise_for_provider(init, "YouTube")
            session_url = init.headers.get("location")
            if not session_url:
                raise TransientPublishError("YouTube resumable upload did not return Location")

            try:
                with open(item.path, "rb") as handle:
                    upload = await client.put(
                        session_url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Length": str(size),
                            "Content-Type": item.mime_type,
                        },
                        content=handle.read(),
                    )
            except (OSError, httpx.RequestError) as exc:
                if isinstance(exc, OSError):
                    raise PermanentPublishError("Не удалось прочитать YouTube video file") from exc
                raise TransientPublishError(f"YouTube upload network error: {type(exc).__name__}") from exc
            if upload.status_code == 308:
                raise TransientPublishError("YouTube resumable upload is incomplete")
            raise_for_provider(upload, "YouTube")
            body = upload.json()
            video_id = str(body.get("id") or "") if isinstance(body, dict) else ""
            if not video_id:
                raise TransientPublishError("YouTube did not return video id")
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
                raise TransientPublishError(f"YouTube status network error: {type(exc).__name__}") from exc
            raise_for_provider(response, "YouTube")
            body = response.json()
            items = body.get("items") if isinstance(body, dict) else None
            if not isinstance(items, list) or not items:
                return PublishStatus(state="failed", message="YouTube video не найден")
            video = items[0]
            status = video.get("status") or {}
            processing = video.get("processingDetails") or {}
            upload_status = str(status.get("uploadStatus") or "").lower()
            processing_status = str(processing.get("processingStatus") or "").lower()
            if upload_status in {"failed", "rejected", "deleted"} or processing_status in {"failed", "terminated"}:
                reason = str(status.get("rejectionReason") or status.get("failureReason") or processing_status or upload_status)
                return PublishStatus(state="failed", message=f"YouTube: {reason}"[:500])
            if processing_status in {"processing", "pending"} or upload_status in {"uploaded", "processing"}:
                return PublishStatus(
                    state="processing",
                    message=processing_status or upload_status,
                    poll_after_seconds=15,
                )
            return PublishStatus(
                state="published",
                external_url=f"https://www.youtube.com/watch?v={external_post_id}",
            )
        finally:
            if owned:
                await client.aclose()


CONNECTORS = {"youtube": YouTubeConnector()}
