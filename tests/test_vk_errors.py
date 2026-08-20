import httpx
import pytest

from app.integrations.base import PermanentPublishError, PublishRequest, TransientPublishError
from app.integrations.vk import VKConnector


def request():
    return PublishRequest(
        text="Проверка",
        media=(),
        config={"access_token": "super-secret-vk-token", "owner_id": "-123"},
    )


@pytest.mark.asyncio
async def test_vk_permanent_error_does_not_leak_access_token():
    async def handler(http_request):
        return httpx.Response(
            200,
            json={"error": {"error_code": 5, "error_msg": "User authorization failed"}},
        )

    connector = VKConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PermanentPublishError) as exc:
            await connector.health(request(), client)
    assert "super-secret-vk-token" not in str(exc.value)
    assert "authorization failed" in str(exc.value)


@pytest.mark.asyncio
async def test_vk_rate_limit_style_error_is_transient():
    async def handler(http_request):
        return httpx.Response(
            200,
            json={"error": {"error_code": 6, "error_msg": "Too many requests per second"}},
        )

    connector = VKConnector()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TransientPublishError):
            await connector.health(request(), client)
