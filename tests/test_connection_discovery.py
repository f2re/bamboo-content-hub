import pytest

from app.integrations import onboarding


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakePinterestClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, **_kwargs):
        assert url.endswith("/boards")
        return FakeResponse(
            {"items": [{"id": "board-1", "name": "Керамика"}, {"id": "board-2", "name": "Подарки"}]}
        )


@pytest.mark.asyncio
async def test_pinterest_target_discovery_returns_human_choices(monkeypatch):
    monkeypatch.setattr(onboarding.httpx, "AsyncClient", lambda **_kwargs: FakePinterestClient())
    result = await onboarding.discover_target_choices(
        "pinterest", {"access_token": "token", "board_id": ""}
    )
    assert result["ok"] is True
    assert result["details"]["choices"] == [
        {"label": "Керамика", "values": {"board_id": "board-1"}},
        {"label": "Подарки", "values": {"board_id": "board-2"}},
    ]


@pytest.mark.asyncio
async def test_discovery_is_skipped_when_target_is_already_saved():
    result = await onboarding.discover_target_choices(
        "pinterest", {"access_token": "token", "board_id": "board-1"}
    )
    assert result is None
