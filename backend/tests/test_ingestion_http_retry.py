import httpx
import pytest

from app.services.ingestion import http_retry


class _FakeClient:
    def __init__(self, actions):
        self.actions = actions
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        action = self.actions[self.calls]
        self.calls += 1
        if isinstance(action, Exception):
            raise action
        return action


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("POST", "http://model/api"), json={"ok": True})


@pytest.mark.asyncio
async def test_transient_timeout_is_retried(monkeypatch):
    client = _FakeClient([httpx.ReadTimeout("slow"), _response(200)])
    monkeypatch.setattr(http_retry.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(http_retry.asyncio, "sleep", _no_sleep)

    response = await http_retry.post_json_with_retry(
        "http://model/api", headers={}, payload={}, timeout_secs=1
    )

    assert response.status_code == 200
    assert client.calls == 2


@pytest.mark.asyncio
async def test_non_retryable_client_error_fails_immediately(monkeypatch):
    client = _FakeClient([_response(400), _response(200)])
    monkeypatch.setattr(http_retry.httpx, "AsyncClient", lambda **_kwargs: client)

    with pytest.raises(httpx.HTTPStatusError):
        await http_retry.post_json_with_retry(
            "http://model/api", headers={}, payload={}, timeout_secs=1
        )

    assert client.calls == 1


async def _no_sleep(_delay):
    return None
