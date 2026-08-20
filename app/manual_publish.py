from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Delivery, DeliveryStatus, MediaAsset, Product, Publication
from .publisher import _update_publication_status, channel_text
from .security import safe_media_path

router = APIRouter()
settings = get_settings()

CHANNEL_LABELS = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "pinterest": "Pinterest",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "vk": "VK",
    "livemaster": "Ярмарка мастеров",
}
PLATFORM_URLS = {
    "instagram": "https://www.instagram.com/",
    "facebook": "https://www.facebook.com/",
    "pinterest": "https://www.pinterest.com/pin-creation-tool/",
    "tiktok": "https://www.tiktok.com/upload",
    "youtube": "https://studio.youtube.com/",
    "vk": "https://vk.com/",
    "livemaster": "https://www.livemaster.ru/",
}


def _template_context(request: Request) -> dict:
    return {
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "auth_enabled": not settings.trusted_lan,
    }


templates = Jinja2Templates(directory="templates", context_processors=[_template_context])


def _package_or_404(
    db: Session,
    publication_id: str,
    delivery_id: str,
) -> tuple[Publication, Delivery, Product, list[MediaAsset]]:
    publication = db.get(Publication, publication_id)
    delivery = db.get(Delivery, delivery_id)
    if not publication or not delivery or delivery.publication_id != publication.id:
        raise HTTPException(404, "Пакет публикации не найден")
    if delivery.status not in {
        DeliveryStatus.manual_action.value,
        DeliveryStatus.published.value,
    }:
        raise HTTPException(409, "Пакет ещё не подготовлен")
    product = db.get(Product, publication.product_id)
    if not product:
        raise HTTPException(404, "Изделие не найдено")

    selected = publication.selected_media_ids or []
    rows = (
        list(db.scalars(select(MediaAsset).where(MediaAsset.id.in_(selected))))
        if selected
        else []
    )
    by_id = {row.id: row for row in rows if row.product_id == product.id}
    media = [by_id[asset_id] for asset_id in selected if asset_id in by_id]
    return publication, delivery, product, media


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._ -]+", "-", value).strip(" .-")
    return cleaned[:120] or fallback


@router.get(
    "/publications/{publication_id}/manual/{delivery_id}",
    response_class=HTMLResponse,
)
def manual_package_page(
    publication_id: str,
    delivery_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    publication, delivery, product, media = _package_or_404(
        db,
        publication_id,
        delivery_id,
    )
    content = (publication.channel_content or {}).get(delivery.channel) or {}
    title = str(content.get("title") or product.name)
    return templates.TemplateResponse(
        request,
        "manual_package.html",
        {
            "publication": publication,
            "delivery": delivery,
            "product": product,
            "media": media,
            "channel_label": CHANNEL_LABELS.get(delivery.channel, delivery.channel),
            "platform_url": PLATFORM_URLS.get(delivery.channel, ""),
            "title_text": title,
            "publication_text": channel_text(publication, delivery.channel),
        },
    )


@router.get("/publications/{publication_id}/manual/{delivery_id}/media/{asset_id}")
def manual_media_download(
    publication_id: str,
    delivery_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
):
    _publication, _delivery, _product, media = _package_or_404(
        db,
        publication_id,
        delivery_id,
    )
    asset = next((item for item in media if item.id == asset_id), None)
    if not asset:
        raise HTTPException(404, "Медиафайл не входит в эту публикацию")
    return FileResponse(
        safe_media_path(settings.media_dir, asset.stored_filename),
        media_type=asset.mime_type,
        filename=asset.original_filename,
    )


@router.get("/publications/{publication_id}/manual/{delivery_id}/package.zip")
def manual_package_zip(
    publication_id: str,
    delivery_id: str,
    db: Session = Depends(get_db),
):
    publication, delivery, product, media = _package_or_404(
        db,
        publication_id,
        delivery_id,
    )
    content = (publication.channel_content or {}).get(delivery.channel) or {}
    title = str(content.get("title") or product.name)
    text = channel_text(publication, delivery.channel)

    output = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "publication.txt",
            f"{title}\n\n{text}".strip() + "\n",
        )
        for index, asset in enumerate(media, start=1):
            original = _safe_name(asset.original_filename, f"media-{index}")
            name = f"{index:02d}-{original}"
            while name in used_names:
                name = f"{index:02d}-{asset.id[:8]}-{original}"
            used_names.add(name)
            archive.write(
                safe_media_path(settings.media_dir, asset.stored_filename),
                arcname=name,
            )
    output.seek(0)
    filename = f"bamboo-{delivery.channel}-{_safe_name(product.name, 'product')}.zip"
    return StreamingResponse(
        output,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/publications/{publication_id}/manual/{delivery_id}/complete")
def manual_package_complete(
    publication_id: str,
    delivery_id: str,
    published_url: str = Form(default=""),
    db: Session = Depends(get_db),
):
    publication, delivery, _product, _media = _package_or_404(
        db,
        publication_id,
        delivery_id,
    )
    url = published_url.strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(422, "Ссылка должна начинаться с http:// или https://")
    delivery.status = DeliveryStatus.published.value
    delivery.published_at = datetime.now(UTC)
    delivery.last_error = None
    delivery.next_attempt_at = None
    delivery.external_url = url or None
    db.commit()
    _update_publication_status(db, publication)
    return RedirectResponse("/publications", status_code=303)
