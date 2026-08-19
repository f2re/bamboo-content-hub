from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .integrations.connectors import CONNECTORS
from .models import Delivery, DeliveryStatus, IntegrationAccount, MediaAsset, Publication, PublicationStatus
from .security import CredentialCipher, safe_media_path
from .services import retry_delay


def channel_text(publication: Publication, channel: str) -> str:
    content = (publication.channel_content or {}).get(channel) or {}
    text = content.get("caption") or content.get("text") or content.get("description") or content.get("title") or ""
    hashtags = content.get("hashtags") or []
    if hashtags:
        text = f"{text}\n\n{' '.join(hashtags)}".strip()
    return text


async def process_delivery(db: Session, settings: Settings, delivery: Delivery) -> None:
    if delivery.status == DeliveryStatus.published.value:
        return
    connector = CONNECTORS.get(delivery.channel)
    if connector is None:
        delivery.status = DeliveryStatus.manual_action.value
        delivery.last_error = "Автоматический адаптер для этой площадки ещё не активирован"
        db.commit()
        return
    delivery.status = DeliveryStatus.processing.value
    delivery.attempt_count += 1
    db.commit()
    publication = db.get(Publication, delivery.publication_id)
    media = list(db.scalars(select(MediaAsset).where(MediaAsset.id.in_(publication.selected_media_ids)))) if publication.selected_media_ids else []
    by_id = {m.id: m for m in media}
    media_paths = [str(safe_media_path(settings.media_dir, by_id[mid].stored_filename)) for mid in publication.selected_media_ids if mid in by_id]
    config = {}
    account = db.scalar(select(IntegrationAccount).where(IntegrationAccount.provider == delivery.channel, IntegrationAccount.account_key == "default"))
    if account and account.encrypted_credentials:
        config = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
    try:
        result = await connector.publish(channel_text(publication, delivery.channel), media_paths, config)
        if result.manual_action:
            delivery.status = DeliveryStatus.manual_action.value
            delivery.last_error = result.message
        else:
            delivery.status = DeliveryStatus.published.value
            delivery.external_post_id = result.external_post_id
            delivery.external_url = result.external_url
            delivery.published_at = datetime.now(UTC)
            delivery.last_error = None
    except Exception as exc:
        delivery.last_error = str(exc)[:1500]
        if delivery.attempt_count >= 4:
            delivery.status = DeliveryStatus.failed.value
        else:
            delivery.status = DeliveryStatus.retry_wait.value
            delivery.next_attempt_at = datetime.now(UTC) + retry_delay(delivery.attempt_count)
    db.commit()
    statuses = [d.status for d in publication.deliveries]
    if statuses and all(s in (DeliveryStatus.published.value, DeliveryStatus.manual_action.value) for s in statuses):
        publication.status = PublicationStatus.completed.value
    elif any(s == DeliveryStatus.failed.value for s in statuses):
        publication.status = PublicationStatus.partially_failed.value
    else:
        publication.status = PublicationStatus.processing.value
    db.commit()
