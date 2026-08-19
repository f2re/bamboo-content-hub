from datetime import UTC, datetime, timedelta

import pytest

from app.db import SessionLocal
from app.models import Delivery, DeliveryStatus, Product, PublicationStatus
from app.services import claim_delivery, create_publication, due_deliveries, parse_local_datetime


def test_datetime_local_is_interpreted_in_installation_timezone():
    value = parse_local_datetime("2026-08-19T21:00", "Europe/Helsinki")
    assert value == datetime(2026, 8, 19, 18, 0, tzinfo=UTC)


def test_nonexistent_dst_local_time_is_rejected():
    with pytest.raises(ValueError):
        parse_local_datetime("2026-03-29T03:30", "Europe/Helsinki")


def test_delivery_claim_is_atomic_and_stale_claim_is_recoverable():
    with SessionLocal() as db:
        product = Product(name="Чашка")
        db.add(product)
        db.commit()
        db.refresh(product)
        publication = create_publication(
            db,
            product,
            ["demo"],
            [],
            datetime.now(UTC) - timedelta(minutes=1),
        )
        publication.status = PublicationStatus.scheduled.value
        db.commit()
        delivery_id = publication.deliveries[0].id

    with SessionLocal() as db:
        first = claim_delivery(db, delivery_id, 300)
        assert first is not None
        assert first.status == DeliveryStatus.processing.value
        assert first.attempt_count == 1

    with SessionLocal() as db:
        second = claim_delivery(db, delivery_id, 300)
        assert second is None

    with SessionLocal() as db:
        delivery = db.get(Delivery, delivery_id)
        delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert any(item.id == delivery_id for item in due_deliveries(db))
        reclaimed = claim_delivery(db, delivery_id, 300)
        assert reclaimed is not None
        assert reclaimed.attempt_count == 2


def test_api_stores_scheduled_time_as_utc_and_renders_local(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]
    response = client.post(
        f"/products/{product_id}/publications",
        data={"channels": "demo", "scheduled_at": "2026-08-19T21:00", "action": "draft"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        from app.models import Publication

        publication = db.query(Publication).one()
        stored = publication.scheduled_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        assert stored == datetime(2026, 8, 19, 18, 0, tzinfo=UTC)

    page = client.get("/publications")
    assert page.status_code == 200
    assert "19.08.2026 21:00" in page.text
