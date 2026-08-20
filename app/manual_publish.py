from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

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
templates.env.globals["app_release"] = "0.3.0"
templates.env.globals["feature_marker"] = "manual-first-browser-assist"


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


def _remove_temp_package(path: Path) -> None:
    path.unlink(missing_ok=True)


def _format_dimensions(facts: dict) -> str:
    dimensions = facts.get("dimensions") or {}
    parts: list[str] = []
    for key, label, unit in (
        ("height_mm", "высота", "мм"),
        ("diameter_mm", "диаметр", "мм"),
        ("volume_ml", "объём", "мл"),
        ("weight_g", "масса", "г"),
    ):
        value = dimensions.get(key)
        if value not in (None, ""):
            parts.append(f"{label} {value:g} {unit}" if isinstance(value, float) else f"{label} {value} {unit}")
    return ", ".join(parts)


def _livemaster_payload(product: Product, content: dict) -> dict:
    facts = product.facts or {}
    price = facts.get("price") or {}
    materials = facts.get("materials") or []
    keywords = content.get("keywords") or []
    amount = price.get("amount")
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    return {
        "schema": "bamboo-browser-fill/1",
        "platform": "livemaster",
        "title": str(content.get("title") or product.name or "").strip(),
        "short_description": str(content.get("short_description") or "").strip(),
        "description": str(content.get("description") or product.description or "").strip(),
        "price": amount if amount is not None else "",
        "currency": str(price.get("currency") or "RUB").strip(),
        "materials": ", ".join(str(item).strip() for item in materials if str(item).strip()),
        "dimensions": _format_dimensions(facts),
        "keywords": ", ".join(str(item).strip() for item in keywords if str(item).strip()),
        "availability": str(facts.get("availability") or "").strip(),
    }


def _livemaster_fields(payload: dict) -> list[dict]:
    definitions = (
        ("title", "Название", False),
        ("short_description", "Краткое описание", True),
        ("description", "Полное описание", True),
        ("price", "Цена", False),
        ("materials", "Материалы", False),
        ("dimensions", "Размеры", False),
        ("keywords", "Ключевые слова", True),
        ("availability", "Наличие", False),
    )
    return [
        {"key": key, "label": label, "value": payload.get(key, ""), "multiline": multiline}
        for key, label, multiline in definitions
        if payload.get(key) not in (None, "")
    ]


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
    livemaster_payload = (
        _livemaster_payload(product, content) if delivery.channel == "livemaster" else None
    )
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
            "livemaster_payload_json": (
                json.dumps(livemaster_payload, ensure_ascii=False, indent=2)
                if livemaster_payload
                else ""
            ),
            "livemaster_fields": (
                _livemaster_fields(livemaster_payload) if livemaster_payload else []
            ),
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

    with tempfile.NamedTemporaryFile(prefix="bamboo-package-", suffix=".zip", delete=False) as temp:
        package_path = Path(temp.name)
    try:
        used_names: set[str] = set()
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "publication.txt",
                f"{title}\n\n{text}".strip() + "\n",
            )
            if delivery.channel == "livemaster":
                archive.writestr(
                    "browser-fill.json",
                    json.dumps(
                        _livemaster_payload(product, content),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
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
    except Exception:
        package_path.unlink(missing_ok=True)
        raise

    filename = f"bamboo-{delivery.channel}-{product.id[:8]}.zip"
    return FileResponse(
        package_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(_remove_temp_package, package_path),
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
