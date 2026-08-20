import json

from app.ai_pack import parse_pack
from app.db import SessionLocal
from app.models import Product


def _raw_pack(request_id: str, *, price=3900, media=None):
    return {
        "schema_version": "bamboo-content-pack/1.0",
        "request_id": request_id,
        "product": {
            "name": "Чашка Туман",
            "price": {"amount": price, "currency": "RUB"},
            "materials": ["каменная масса"],
        },
        "content": {"full_description": "Спокойное описание чашки."},
        "media": media or {},
    }


def _new_product(client):
    response = client.post("/products", data={"name": "Чашка"}, follow_redirects=False)
    product_id = response.headers["location"].split("/")[-1]
    client.get(f"/products/{product_id}/ai")
    with SessionLocal() as db:
        request_id = db.get(Product, product_id).ai_request_id
    return product_id, request_id


def test_parse_moves_critical_fact_into_signed_confirmation():
    parsed = parse_pack(json.dumps(_raw_pack("REQ-SAFE")), "REQ-SAFE")

    assert parsed.product.price.amount is None
    assert parsed.product.materials == []
    price = next(item for item in parsed.needs_confirmation if item.path == "product.price.amount")
    assert price.value == 3900
    assert price.proof
    assert price.confirmed is False


def test_signed_confirmation_restores_only_explicitly_confirmed_value():
    preview = parse_pack(json.dumps(_raw_pack("REQ-CONFIRM")), "REQ-CONFIRM").model_dump()
    for item in preview["needs_confirmation"]:
        item["confirmed"] = item["path"] == "product.price.amount"

    parsed = parse_pack(json.dumps(preview), "REQ-CONFIRM")

    assert parsed.product.price.amount == 3900
    assert parsed.product.materials == []


def test_tampered_confirmation_value_is_not_restored():
    preview = parse_pack(json.dumps(_raw_pack("REQ-TAMPER")), "REQ-TAMPER").model_dump()
    price = next(item for item in preview["needs_confirmation"] if item["path"] == "product.price.amount")
    price["value"] = 9900
    price["confirmed"] = True

    parsed = parse_pack(json.dumps(preview), "REQ-TAMPER")

    assert parsed.product.price.amount is None


def test_direct_import_does_not_store_unconfirmed_critical_facts(client):
    product_id, request_id = _new_product(client)

    response = client.post(
        f"/api/products/{product_id}/ai/import",
        json={"text": json.dumps(_raw_pack(request_id), ensure_ascii=False)},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        product = db.get(Product, product_id)
        assert product.facts["price"]["amount"] is None
        assert product.facts["materials"] == []
        assert product.description == "Спокойное описание чашки."


def test_preview_then_confirmed_import_records_provenance(client):
    product_id, request_id = _new_product(client)
    raw = json.dumps(_raw_pack(request_id), ensure_ascii=False)

    preview_response = client.post(
        f"/api/products/{product_id}/ai/preview",
        json={"text": raw},
    )
    assert preview_response.status_code == 200
    pack = preview_response.json()["pack"]
    for item in pack["needs_confirmation"]:
        item["confirmed"] = item["path"] == "product.price.amount"

    import_response = client.post(
        f"/api/products/{product_id}/ai/import",
        json={"text": json.dumps(pack, ensure_ascii=False)},
    )
    assert import_response.status_code == 200

    with SessionLocal() as db:
        product = db.get(Product, product_id)
        assert product.facts["price"]["amount"] == 3900
        assert product.facts["materials"] == []
        assert product.facts["_provenance"]["product.price.amount"] == "confirmed"


def test_import_rejects_media_reference_not_uploaded_to_product(client):
    product_id, request_id = _new_product(client)
    raw = _raw_pack(
        request_id,
        media={
            "images": [{"id": "image_1", "role": "cover", "alt_text": "Чашка"}],
            "order": ["image_1"],
            "recommended_cover": "image_1",
        },
    )

    response = client.post(
        f"/api/products/{product_id}/ai/import",
        json={"text": json.dumps(raw, ensure_ascii=False)},
    )

    assert response.status_code == 422
    assert "отсутствующие изображения" in response.json()["detail"]
