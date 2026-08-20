from __future__ import annotations

import asyncio
import hashlib
import io
import secrets
import shutil
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from .ai_pack import BambooContentPack, deep_fill
from .config import Settings
from .models import Delivery, DeliveryStatus, MediaAsset, Product, Publication, PublicationStatus
from .security import detect_media_mime, safe_media_extension, safe_media_path

IMAGE_MAX_SIDE = 2560
IMAGE_JPEG_QUALITY = 90
VIDEO_MAX_SIDE = 1920

CRITICAL_AI_FIELDS: dict[str, str] = {
    "price.amount": "Цена",
    "materials": "Материалы",
    "glaze": "Глазурь",
    "firing": "Режим обжига",
    "dimensions.height_mm": "Высота",
    "dimensions.diameter_mm": "Диаметр",
    "dimensions.volume_ml": "Объём",
    "dimensions.weight_g": "Масса",
    "care.dishwasher": "Посудомоечная машина",
    "care.microwave": "Микроволновая печь",
    "care.food_safe": "Контакт с пищей",
    "availability": "Наличие",
}


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _nested_get(data: dict, path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _nested_drop(data: dict, path: str) -> None:
    parts = path.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
        if current is None:
            return
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _flatten_values(data: Any, prefix: str = "product") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(data, dict):
        return result
    for key, value in data.items():
        if key == "_provenance":
            continue
        path = f"{prefix}.{key}"
        if isinstance(value, dict):
            result.update(_flatten_values(value, path))
        elif _has_value(value):
            result[path] = value
    return result


def validate_pack_media(product: Product, pack: BambooContentPack) -> None:
    actual = {
        f"image_{index + 1}"
        for index, _asset in enumerate(sorted(product.media, key=lambda item: item.sort_order))
    }
    referenced = {item.id for item in pack.media.images} | set(pack.media.order)
    if pack.media.recommended_cover:
        referenced.add(pack.media.recommended_cover)
    unknown = referenced - actual
    if unknown:
        raise ValueError(
            "Ответ ИИ ссылается на отсутствующие изображения: " + ", ".join(sorted(unknown))
        )


def build_ai_review(product: Product, pack: BambooContentPack) -> dict:
    """Build server-authoritative confirmation requirements for new critical facts."""
    validate_pack_media(product, pack)
    incoming = pack.product.model_dump()
    existing = dict(product.facts or {})
    required: list[dict] = []
    for relative_path, label in CRITICAL_AI_FIELDS.items():
        proposed = _nested_get(incoming, relative_path)
        current = _nested_get(existing, relative_path)
        if _has_value(proposed) and not _has_value(current):
            required.append(
                {
                    "path": f"product.{relative_path}",
                    "label": label,
                    "value": proposed,
                    "reason": "Новый критичный факт предложен ИИ и должен быть подтверждён человеком.",
                }
            )
    return {
        "required_confirmation": required,
        "needs_confirmation": [item.model_dump() for item in pack.needs_confirmation],
        "assumptions": [item.model_dump() for item in pack.assumptions],
    }


def _optimize_image(content: bytes, mime: str) -> tuple[bytes, str]:
    """Normalize phone/social images to an EXIF-corrected JPEG, falling back safely."""
    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener

        register_heif_opener()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            if getattr(image, "is_animated", False):
                return content, mime
            image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            elif image.mode == "L":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=IMAGE_JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
            optimized = output.getvalue()
            if optimized:
                return optimized, "image/jpeg"
    except Exception:
        pass
    return content, mime


async def _optimize_video(content: bytes, mime: str, media_dir: Path) -> tuple[bytes, str]:
    """Normalize decodable videos to H.264/AAC MP4; invalid/test fixtures fall back unchanged."""
    if not shutil.which("ffmpeg"):
        return content, mime
    token = secrets.token_hex(12)
    source = media_dir / f".{token}.source{safe_media_extension(mime)}"
    target = media_dir / f".{token}.optimized.mp4"
    source.write_bytes(content)
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-vf",
            f"scale={VIDEO_MAX_SIDE}:{VIDEO_MAX_SIDE}:force_original_aspect_ratio=decrease",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.communicate()
        if process.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return target.read_bytes(), "video/mp4"
    except (OSError, ValueError):
        pass
    finally:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
    return content, mime


async def save_upload(
    db: Session,
    settings: Settings,
    product: Product,
    upload: UploadFile,
    sort_order: int,
) -> MediaAsset:
    content = await upload.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise ValueError("Файл превышает допустимый размер")
    mime = detect_media_mime(content)
    if mime is None:
        raise ValueError("Формат файла не поддерживается или небезопасен")

    optimized = content
    optimized_mime = mime
    if mime.startswith("image/"):
        optimized, optimized_mime = _optimize_image(content, mime)
    elif mime.startswith("video/"):
        optimized, optimized_mime = await _optimize_video(content, mime, settings.media_dir)

    stored = f"{secrets.token_hex(16)}{safe_media_extension(optimized_mime)}"
    path = safe_media_path(settings.media_dir, stored)
    path.write_bytes(optimized)
    asset = MediaAsset(
        product_id=product.id,
        original_filename=Path(upload.filename or "upload").name,
        stored_filename=stored,
        mime_type=optimized_mime,
        media_type="image" if optimized_mime.startswith("image/") else "video",
        file_size=len(optimized),
        checksum=hashlib.sha256(optimized).hexdigest(),
        sort_order=sort_order,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def apply_ai_pack(
    db: Session,
    product: Product,
    pack: BambooContentPack,
    confirmed_paths: set[str] | None = None,
) -> Product:
    if confirmed_paths is None:
        confirmed_paths = {
            item.path
            for item in pack.needs_confirmation
            if getattr(item, "confirmed", False) and getattr(item, "proof", None)
        }
    else:
        confirmed_paths = set(confirmed_paths)
    review = build_ai_review(product, pack)
    required_paths = {item["path"] for item in review["required_confirmation"]}
    blocked_paths = required_paths - confirmed_paths

    incoming = pack.product.model_dump()
    for full_path in blocked_paths:
        relative_path = full_path.removeprefix("product.")
        _nested_drop(incoming, relative_path)

    existing_facts = deepcopy(product.facts or {})
    existing_provenance = dict(existing_facts.pop("_provenance", {}) or {})
    current_flat = _flatten_values(existing_facts)
    incoming_flat = _flatten_values(incoming)
    for path in current_flat:
        existing_provenance.setdefault(path, "user")
    for path in incoming_flat:
        relative_path = path.removeprefix("product.")
        if not _has_value(_nested_get(existing_facts, relative_path)):
            existing_provenance[path] = "confirmed" if path in confirmed_paths else "ai"

    product.name = product.name or incoming.get("name") or "Без названия"
    product.sku = product.sku or incoming.get("sku")
    product.product_type = product.product_type or incoming.get("product_type")
    product.collection = product.collection or incoming.get("collection")
    product.description = (
        product.description or pack.content.full_description or pack.content.short_description
    )
    merged_facts = deep_fill(existing_facts, incoming)
    merged_facts["_provenance"] = existing_provenance
    product.facts = merged_facts
    product.channel_content = deep_fill(product.channel_content or {}, pack.channels.model_dump())
    product.ai_request_id = pack.request_id
    by_image = {
        f"image_{i + 1}": asset
        for i, asset in enumerate(sorted(product.media, key=lambda m: m.sort_order))
    }
    for image in pack.media.images:
        asset = by_image.get(image.id)
        if asset:
            asset.alt_text = asset.alt_text or image.alt_text
            asset.role = asset.role or image.role
    if pack.media.order:
        for idx, image_id in enumerate(pack.media.order):
            if image_id in by_image:
                by_image[image_id].sort_order = idx
    db.commit()
    db.refresh(product)
    return product


def create_publication(
    db: Session,
    product: Product,
    channels: list[str],
    media_ids: list[str],
    scheduled_at: datetime | None = None,
    channel_overrides: dict[str, dict] | None = None,
) -> Publication:
    valid_media = {m.id for m in product.media}
    unknown = set(media_ids) - valid_media
    if unknown:
        raise ValueError("publication contains media from another product")
    status = PublicationStatus.scheduled.value if scheduled_at else PublicationStatus.draft.value
    content = deepcopy(product.channel_content or {})
    for channel, values in (channel_overrides or {}).items():
        current = dict(content.get(channel) or {})
        current.update(values)
        content[channel] = current
    publication = Publication(
        product_id=product.id,
        status=status,
        scheduled_at=scheduled_at,
        selected_media_ids=media_ids,
        channel_content=content,
    )
    db.add(publication)
    db.flush()
    for channel in dict.fromkeys(channels):
        key = hashlib.sha256(f"{publication.id}:{channel}".encode()).hexdigest()
        db.add(Delivery(publication_id=publication.id, channel=channel, idempotency_key=key))
    db.commit()
    db.refresh(publication)
    return publication


def parse_local_datetime(value: str, timezone_name: str) -> datetime | None:
    """Parse an HTML datetime-local value in the installation timezone and return UTC."""
    value = value.strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    zone = ZoneInfo(timezone_name)
    local = parsed.replace(tzinfo=zone, fold=0)
    roundtrip = local.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if roundtrip != parsed:
        raise ValueError(
            "Выбранное местное время не существует из-за перехода на летнее/зимнее время"
        )
    return local.astimezone(UTC)


def format_local_datetime(value: datetime | None, timezone_name: str) -> str:
    if value is None:
        return ""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(ZoneInfo(timezone_name)).strftime("%d.%m.%Y %H:%M %Z")


def retry_delay(attempt: int) -> timedelta:
    seconds = [60, 300, 900, 3600][min(max(attempt - 1, 0), 3)]
    return timedelta(seconds=seconds)


def claim_delivery(db: Session, delivery_id: str, lease_seconds: int) -> Delivery | None:
    """Atomically claim one due delivery using next_attempt_at as the lease deadline."""
    now = datetime.now(UTC)
    lease_until = now + timedelta(seconds=max(30, lease_seconds))
    due_retry = and_(
        Delivery.status.in_([DeliveryStatus.pending.value, DeliveryStatus.retry_wait.value]),
        or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now),
    )
    stale_processing = and_(
        Delivery.status == DeliveryStatus.processing.value,
        Delivery.next_attempt_at.is_not(None),
        Delivery.next_attempt_at <= now,
    )
    stmt = (
        update(Delivery)
        .where(Delivery.id == delivery_id, or_(due_retry, stale_processing))
        .values(
            status=DeliveryStatus.processing.value,
            attempt_count=Delivery.attempt_count + 1,
            next_attempt_at=lease_until,
        )
    )
    result = db.execute(stmt)
    db.commit()
    if result.rowcount != 1:
        return None
    db.expire_all()
    return db.get(Delivery, delivery_id)


def due_deliveries(db: Session) -> list[Delivery]:
    now = datetime.now(UTC)
    due_retry = and_(
        Delivery.status.in_([DeliveryStatus.pending.value, DeliveryStatus.retry_wait.value]),
        or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now),
    )
    stale_processing = and_(
        Delivery.status == DeliveryStatus.processing.value,
        Delivery.next_attempt_at.is_not(None),
        Delivery.next_attempt_at <= now,
    )
    stmt = (
        select(Delivery)
        .join(Publication)
        .where(
            or_(due_retry, stale_processing),
            (Publication.scheduled_at.is_(None)) | (Publication.scheduled_at <= now),
            Publication.status != PublicationStatus.draft.value,
        )
        .order_by(Delivery.next_attempt_at.asc().nullsfirst())
        .limit(20)
    )
    return list(db.scalars(stmt))
