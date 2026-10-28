import types

import httpx
import litellm

from app.services.llm import LiteLLMClient, StreamRequest, Usage
from tests.conftest import register


def gateway(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/models"
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [{"id": "cc/claude-sonnet-4.5"}, {"id": "gemini-flash"}, {"id": "gemini-flash"}],
        },
    )


async def test_9router_provider_is_keyless_and_syncs_models(client):
    client._transport.app.state.http_transport = httpx.MockTransport(gateway)
    headers = await register(client)
    created = await client.post(
        "/api/v1/providers",
        json={"name": "9router", "base_url": "http://router.local:20128/v1"},
        headers=headers,
    )
    assert created.status_code == 201
    provider = created.json()
    assert len(provider["keys"]) == 1 and provider["keys"][0]["key_hint"] == "tanpa key"
    synced = await client.post(f"/api/v1/providers/{provider['id']}/models/sync", headers=headers)
    assert synced.json() == {"added": ["cc/claude-sonnet-4.5", "gemini-flash"], "total": 2}
    again = await client.post(f"/api/v1/providers/{provider['id']}/models/sync", headers=headers)
    assert again.json()["added"] == []
    models = {m["id"]: m for m in (await client.get("/api/v1/models", headers=headers)).json()}
    assert models["9router/cc/claude-sonnet-4.5"]["tier"] == "strong"
    assert models["9router/gemini-flash"]["tier"] == "cheap"
    from app.api.providers import guess_tier

    assert guess_tier("gh/gpt-4o-mini") == "cheap" and guess_tier("gh/gpt-4o") == "strong"

    added = await client.post(
        f"/api/v1/providers/{provider['id']}/models",
        json={"model_name": "kr/qwen3-coder", "tier": "strong"},
        headers=headers,
    )
    assert added.status_code == 201
    dup = await client.post(
        f"/api/v1/providers/{provider['id']}/models", json={"model_name": "kr/qwen3-coder"}, headers=headers
    )
    assert dup.status_code == 409
    gone = await client.delete(f"/api/v1/providers/{provider['id']}/models/kr/qwen3-coder", headers=headers)
    assert gone.status_code == 204


async def test_sync_reports_unreachable_gateway(client):
    def down(request):
        raise httpx.ConnectError("refused")

    client._transport.app.state.http_transport = httpx.MockTransport(down)
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "9router"}, headers=headers)).json()
    r = await client.post(f"/api/v1/providers/{provider['id']}/models/sync", headers=headers)
    assert r.status_code == 502 and r.json()["error"]["code"] == "sync_failed"


async def test_keyless_openai_compatible_call_uses_base_url(monkeypatch):
    captured = {}

    async def fake(**kw):
        captured.update(kw)

        async def gen():
            yield types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="ok"))], usage=None
            )

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake)
    req = StreamRequest(
        "9router", "cc/claude-sonnet-4.5", [{"role": "user", "content": "hi"}], "local", None, 5
    )
    out = [t async for t in LiteLLMClient().stream(req, Usage())]
    assert out == ["ok"]
    assert captured["model"] == "openai/cc/claude-sonnet-4.5"
    assert captured["api_base"] == "http://host.docker.internal:20128/v1"
    assert captured["api_key"] == "sk-no-key"
    req.api_key = "sk-router-123456"
    captured.clear()
    [t async for t in LiteLLMClient().stream(req, Usage())]
    assert captured["api_key"] == "sk-router-123456"
