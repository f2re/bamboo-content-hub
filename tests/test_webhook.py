import hashlib
import hmac
import json

from app.main import settings


def test_meta_webhook_signature_and_deduplication(client):
    secret = "webhook-secret"
    settings.meta_webhook_secret = secret
    payload = json.dumps({"object": "instagram", "entry": [{"id": "1"}]}).encode()
    signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    headers = {
        "content-type": "application/json",
        "x-hub-signature-256": signature,
        "x-event-id": "evt-1",
    }
    first = client.post("/webhooks/meta", content=payload, headers=headers)
    assert first.status_code == 200
    second = client.post("/webhooks/meta", content=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True


def test_meta_webhook_rejects_bad_signature(client):
    settings.meta_webhook_secret = "webhook-secret"
    response = client.post(
        "/webhooks/meta",
        content=b"{}",
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=bad"},
    )
    assert response.status_code == 403
