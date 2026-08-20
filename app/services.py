from __future__ import annotations

import hashlib
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from .ai_pack import BambooContentPack, deep_fill
from .config import Settings
from .models import Delivery, DeliveryStatus, MediaAsset, Product, Publication, PublicationStatus
from .security import detect_media_mime, safe_media_extension, safe_media_path


async def save_upload(
    db: Session,
    settings: Settings,
    product: Product,
    upload: UploadFile,
    sort_order: int,
) -> MediaAsset:
    content = await upload.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise ValueError("file exceeds upload limit")
    mime = detect_media_mime(content)
    if mime is None:
        raise ValueError("unsupported or unsafe media file")
    stored = f"{secrets.token_hex(16)}{safe_media_extension(mime)}"
    path = safe_media_path(settings.media_dir, stored)
    path.write_bytes(content)
    asset = MediaAsset(
        product_id=product.id,
        original_filename=Path(upload.filename or "upload").name,
        stored_filename=stored,
        mime_type=mime,
        media_type="image" if mime.startswith("image/") else "video",
        file_size=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
        sort_order=sort_order,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def apply_ai_pack(db: Session, product: Product, pack: BambooContentPack) -> Product:
    incoming = pack.product.model_dump()
    product.name = product.name or incoming.get("name") or "Без названия"
    product.sku = product.sku or incoming.get("sku")
    product.product_type = product.product_type or incoming.get("product_type")
    product.collection = product.collection or incoming.get("collection")
    product.description = (
        product.description or pack.content.full_description or pack.content.short_description
    )
    product.facts = deep_fill(product.facts or {}, incoming)
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
