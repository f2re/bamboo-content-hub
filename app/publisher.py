from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .integrations.base import MediaInput, PermanentPublishError, PublishRequest, TransientPublishError
from .integrations.connectors import credential_provider
from .integrations.registry import CONNECTORS
from .models import Delivery, DeliveryStatus, IntegrationAccount, MediaAsset, Publication, PublicationStatus
from .oauth import valid_access_token
from .security import CredentialCipher, safe_media_path, sign_media_token
from .services import claim_delivery, retry_delay

OAUTH_PROVIDERS = {"meta", "google", "pinterest", "tiktok", "vk"}
MAX_STATUS_POLLS = 20


def channel_text(publication: Publication, channel: str) -> str:
    content = (publication.channel_content or {}).get(channel) or {}
    text = content.get("caption") or content.get("text") or content.get("description") or content.get("title") or ""
    hashtags = content.get("hashtags") or []
    if hashtags:
        text = f"{text}\n\n{' '.join(hashtags)}".strip()
    return text


def _update_publication_status(db: Session, publication: Publication) -> None:
    db.expire(publication, ["deliveries"])
    statuses = [d.status for d in publication.deliveries]
    if statuses and all(s in (DeliveryStatus.published.value, DeliveryStatus.manual_action.value) for s in statuses):
        publication.status = PublicationStatus.completed.value
    elif any(s == DeliveryStatus.failed.value for s in statuses):
        publication.status = PublicationStatus.partially_failed.value
    else:
        publication.status = PublicationStatus.processing.value
    db.commit()


async def build_publish_request(
    db: Session,
    settings: Settings,
    publication: Publication,
    delivery: Delivery,
) -> PublishRequest:
    selected = publication.selected_media_ids or []
    media_rows = list(db.scalars(select(MediaAsset).where(MediaAsset.id.in_(selected)))) if selected else []
    by_id = {item.id: item for item in media_rows}
    media: list[MediaInput] = []
    for asset_id in selected:
        asset = by_id.get(asset_id)
        if asset is None:
            continue
        token = sign_media_token(settings, asset.id)
        media.append(
            MediaInput(
                asset_id=asset.id,
                path=str(safe_media_path(settings.media_dir, asset.stored_filename)),
                mime_type=asset.mime_type,
                public_url=f"{settings.app_base_url.rstrip('/')}/media/public/{token}",
                alt_text=asset.alt_text or "",
                role=asset.role,
            )
        )

    provider = credential_provider(delivery.channel)
    account = db.scalar(
        select(IntegrationAccount).where(
            IntegrationAccount.provider == provider,
            IntegrationAccount.account_key == "default",
        )
    )
    config: dict = {}
    if account and account.encrypted_credentials:
        config = CredentialCipher(settings).decrypt_json(account.encrypted_credentials)
    if provider in OAUTH_PROVIDERS and account and account.encrypted_credentials:
        config["access_token"] = await valid_access_token(db, settings, provider)

    return PublishRequest(
        text=channel_text(publication, delivery.channel),
        media=tuple(media),
        config=config,
        content=((publication.channel_content or {}).get(delivery.channel) or {}),
        idempotency_key=delivery.idempotency_key,
    )


def _schedule_retry(delivery: Delivery) -> None:
    if delivery.attempt_count >= 4:
        delivery.status = DeliveryStatus.failed.value
        delivery.next_attempt_at = None
    else:
        delivery.status = DeliveryStatus.retry_wait.value
        delivery.next_attempt_at = datetime.now(UTC) + retry_delay(delivery.attempt_count)


def _schedule_status_poll(delivery: Delivery, seconds: int, message: str | None = None) -> None:
    if delivery.attempt_count >= MAX_STATUS_POLLS:
        delivery.status = DeliveryStatus.failed.value
        delivery.last_error = message or "Площадка слишком долго не подтверждает публикацию"
        delivery.next_attempt_at = None
        return
    delivery.status = DeliveryStatus.processing.value
    delivery.last_error = message
    delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=max(5, seconds))


async def process_delivery(db: Session, settings: Settings, delivery: Delivery) -> bool:
    if delivery.status in (DeliveryStatus.published.value, DeliveryStatus.manual_action.value):
        return False

    claimed = claim_delivery(db, delivery.id, settings.delivery_lease_seconds)
    if claimed is None:
        return False
    delivery = claimed

    publication = db.get(Publication, delivery.publication_id)
    if publication is None:
        delivery.status = DeliveryStatus.failed.value
        delivery.last_error = "Publication does not exist"
        delivery.next_attempt_at = None
        db.commit()
        return True

    connector = CONNECTORS.get(delivery.channel)
    if connector is None:
        delivery.status = DeliveryStatus.manual_action.value
        delivery.last_error = "Автоматический адаптер для этой площадки ещё не активирован"
        delivery.next_attempt_at = None
        db.commit()
        _update_publication_status(db, publication)
        return True

    try:
        request = await build_publish_request(db, settings, publication, delivery)
        errors = connector.validate(request)
        if errors:
            raise PermanentPublishError("; ".join(errors))

        if delivery.external_post_id:
            status = await connector.status(request, delivery.external_post_id)
            if status.state == "published":
                delivery.status = DeliveryStatus.published.value
                delivery.external_url = status.external_url or delivery.external_url
                delivery.published_at = delivery.published_at or datetime.now(UTC)
                delivery.last_error = None
                delivery.next_attempt_at = None
            elif status.state == "failed":
                delivery.status = DeliveryStatus.failed.value
                delivery.last_error = status.message or "Площадка отклонила публикацию"
                delivery.next_attempt_at = None
            else:
                _schedule_status_poll(delivery, status.poll_after_seconds, status.message or None)
        else:
            result = await connector.publish(request)
            if result.manual_action:
                delivery.status = DeliveryStatus.manual_action.value
                delivery.last_error = result.message
                delivery.next_attempt_at = None
            elif result.processing:
                if not result.external_post_id:
                    raise PermanentPublishError("Площадка приняла публикацию без идентификатора статуса")
                delivery.external_post_id = result.external_post_id
                delivery.external_url = result.external_url
                _schedule_status_poll(delivery, result.poll_after_seconds, result.message)
            else:
                delivery.status = DeliveryStatus.published.value
                delivery.external_post_id = result.external_post_id
                delivery.external_url = result.external_url
                delivery.published_at = datetime.now(UTC)
                delivery.last_error = None
                delivery.next_attempt_at = None
    except PermanentPublishError as exc:
        delivery.last_error = str(exc)[:1500]
        delivery.status = DeliveryStatus.failed.value
        delivery.next_attempt_at = None
    except TransientPublishError as exc:
        delivery.last_error = str(exc)[:1500]
        if delivery.external_post_id:
            _schedule_status_poll(delivery, 30, delivery.last_error)
        else:
            _schedule_retry(delivery)
    except Exception as exc:
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:1500]
        if delivery.external_post_id:
            _schedule_status_poll(delivery, 30, delivery.last_error)
        else:
            _schedule_retry(delivery)
    db.commit()
    _update_publication_status(db, publication)
    return True
