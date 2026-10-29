import types
import uuid

import httpx
import litellm

from app.models import Job
from tests.conftest import ScriptedLLM, make_runner, register, send, setup_provider

GEMINI_MODELS = {
    "models": [
        {
            "name": "models/gemini-3.8-flash",
            "displayName": "Gemini 3.8 Flash",
            "inputTokenLimit": 1000000,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/gemini-3.8-pro",
            "displayName": "Gemini 3.8 Pro",
            "supportedGenerationMethods": ["generateContent"],
        },
        {"name": "models/text-embedding-005", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-embedding-002", "supportedGenerationMethods": ["generateContent"]},
    ]
}


def gemini_api(request: httpx.Request) -> httpx.Response:
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.headers["x-goog-api-key"] == "AIzaTESTKEY0000000000000000000"
    assert "key=" not in str(request.url)  # key travels in a header, never in the URL/logs
    return httpx.Response(200, json=GEMINI_MODELS)


async def _models(client, headers):
    return {m["id"]: m for m in (await client.get("/api/v1/models?include_all=true", headers=headers)).json()}


async def test_adding_a_key_syncs_live_models_and_retires_stale_ones(client):
    client._transport.app.state.http_transport = httpx.MockTransport(gemini_api)
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "gemini"}, headers=headers)).json()
    # pretend an old, retired model was seeded earlier
    await client.post(
        f"/api/v1/providers/{provider['id']}/models", json={"model_name": "gemini-2.5-flash"}, headers=headers
    )
    r = await client.post(
        f"/api/v1/providers/{provider['id']}/keys",
        json={"label": "Gemini 1", "api_key": "AIzaTESTKEY0000000000000000000"},
        headers=headers,
    )
    assert r.status_code == 201
    models = await _models(client, headers)
    assert (
        models["gemini/gemini-3.8-flash"]["is_enabled"]
        and models["gemini/gemini-3.8-flash"]["tier"] == "cheap"
    )
    assert models["gemini/gemini-3.8-pro"]["tier"] == "strong"
    assert "gemini/text-embedding-005" not in models and "gemini/gemini-embedding-002" not in models
    assert models["gemini/gemini-2.5-flash"]["is_enabled"] is False
    assert models["gemini/gemini-2.5-flash"]["display_name"].endswith("(tidak tersedia)")
    active = {m["id"] for m in (await client.get("/api/v1/models", headers=headers)).json()}
    assert "gemini/gemini-2.5-flash" not in active


async def test_sync_formats_for_anthropic_openrouter_ollama(client):
    def api(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.anthropic.com":
            assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5"},
                        {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
                    ]
                },
            )
        if request.url.host == "openrouter.ai":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "meta-llama/llama-4:free",
                            "name": "Llama 4 (free)",
                            "pricing": {"prompt": "0", "completion": "0"},
                        },
                        {
                            "id": "openai/gpt-5",
                            "name": "GPT-5",
                            "pricing": {"prompt": "0.000005", "completion": "0.00002"},
                        },
                        {"id": "openai/whisper-1", "name": "Whisper"},
                    ]
                },
            )
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text"}]}
            )
        return httpx.Response(404)

    client._transport.app.state.http_transport = httpx.MockTransport(api)
    headers = await register(client)
    for name, key in (
        ("anthropic", "sk-ant-api03-xxxxxxxxxxxx"),
        ("openrouter", "sk-or-v1-xxxxxxxxxxxx"),
        ("ollama", ""),
    ):
        p = (await client.post("/api/v1/providers", json={"name": name}, headers=headers)).json()
        if key:
            await client.post(
                f"/api/v1/providers/{p['id']}/keys", json={"label": "A", "api_key": key}, headers=headers
            )
        else:
            r = await client.post(f"/api/v1/providers/{p['id']}/models/sync", headers=headers)
            assert r.status_code == 200, r.text
    models = await _models(client, headers)
    assert models["anthropic/claude-opus-4-7"]["tier"] == "strong"
    assert models["openrouter/meta-llama/llama-4:free"]["tier"] == "cheap"
    assert round(models["openrouter/openai/gpt-5"]["cost_out"], 2) == 20.0
    assert "openrouter/openai/whisper-1" not in models
    assert "ollama/llama3.2:3b" in models and "ollama/nomic-embed-text" not in models


async def test_key_test_heals_a_retired_model(client, monkeypatch):
    client._transport.app.state.http_transport = httpx.MockTransport(gemini_api)
    calls = []

    class Gone(Exception):
        status_code = 404

    async def fake(**kw):
        calls.append(kw["model"])
        if kw["model"] == "gemini/gemini-2.5-flash":
            raise Gone(
                '{"error":{"code":404,"message":'
                '"This model models/gemini-2.5-flash is no longer available to new users."}}'
            )
        return types.SimpleNamespace()

    monkeypatch.setattr(litellm, "acompletion", fake)
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "gemini"}, headers=headers)).json()
    # key added while discovery is down -> only the seeded + a stale model exist
    client._transport.app.state.http_transport = httpx.MockTransport(lambda r: httpx.Response(503))
    await client.post(
        f"/api/v1/providers/{provider['id']}/models",
        json={"model_name": "gemini-2.5-flash", "cost_out": 0},
        headers=headers,
    )
    key = (
        await client.post(
            f"/api/v1/providers/{provider['id']}/keys",
            json={"label": "G", "api_key": "AIzaTESTKEY0000000000000000000"},
            headers=headers,
        )
    ).json()
    client._transport.app.state.http_transport = httpx.MockTransport(gemini_api)
    r = (
        await client.post(f"/api/v1/providers/{provider['id']}/keys/{key['id']}/test", headers=headers)
    ).json()
    assert r["ok"] is True, r
    assert "Koneksi berhasil (gemini-3.8-flash)" in r["message"]
    assert "gemini-2.5-flash sudah dihentikan provider" in r["message"]
    assert calls == ["gemini/gemini-2.5-flash", "gemini/gemini-3.8-flash"]


async def test_chat_skips_and_retires_a_model_the_provider_removed(client, sessions, redis, notifier):
    class Gone(ScriptedLLM):
        async def stream(self, req, usage):
            self.calls.append(req)
            if req.model_name == "mock-strong":
                from app.services.llm import ModelNotFound

                raise ModelNotFound("404 model not found")
            async for t in super().stream(req, usage):
                yield t

    llm = Gone()
    runner = make_runner(sessions, redis, llm, notifier)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers, content="tolong debug kode python ini", model="auto")
    assert await runner.run(uuid.UUID(job_id)) == "done"
    async with sessions() as s:
        job = await s.get(Job, uuid.UUID(job_id))
    assert job.model_used == "mock/mock-fast"
    models = await _models(client, headers)
    assert models["mock/mock-strong"]["is_enabled"] is False
    audit = (await client.get("/api/v1/audit?action=model.retired", headers=headers)).json()
    assert audit["total"] == 1


def test_guess_tier_whole_words():
    from app.services.model_discovery import guess_tier

    cases = {
        "gemini-3.8-pro": "strong",
        "gemini-3.8-flash": "cheap",
        "gpt-4o-mini": "cheap",
        "gpt-4o": "strong",
        "claude-opus-4-7": "strong",
        "claude-haiku-4-5": "cheap",
        "llama-3.1-8b-instant": "cheap",
        "llama-3.3-70b-versatile": "strong",
        "qwen3-coder": "strong",
        "mistral-small-latest": "cheap",
        "meta-llama/llama-4:free": "cheap",
        "o3": "strong",
        "gemini-3.8-flash-lite": "cheap",
    }
    assert {k: guess_tier(k) for k in cases} == cases


async def test_key_test_tries_next_model_when_one_is_limited(client, monkeypatch):
    client._transport.app.state.http_transport = httpx.MockTransport(gemini_api)

    class Limited(Exception):
        status_code = 429

    class Busy(Exception):
        status_code = 503

    tried = []

    async def fake(**kw):
        tried.append(kw["model"])
        if kw["model"] == "gemini/gemini-3.8-flash":
            raise Limited(
                '{"error":{"code":429,"message":"You exceeded your current quota",'
                '"status":"RESOURCE_EXHAUSTED"}}'
            )
        if kw["model"] == "gemini/gemini-3.8-pro":
            raise Busy("The model is overloaded")
        return types.SimpleNamespace()

    monkeypatch.setattr(litellm, "acompletion", fake)
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "gemini"}, headers=headers)).json()
    key = (
        await client.post(
            f"/api/v1/providers/{provider['id']}/keys",
            json={"label": "G", "api_key": "AIzaTESTKEY0000000000000000000"},
            headers=headers,
        )
    ).json()
    r = (
        await client.post(f"/api/v1/providers/{provider['id']}/keys/{key['id']}/test", headers=headers)
    ).json()
    # only 2 chat models exist: flash (429) then pro (503) -> no winner, but key is valid
    assert r["ok"] is True and "Key VALID" in r["message"]
    assert tried == ["gemini/gemini-3.8-flash", "gemini/gemini-3.8-pro"]
    keys = (await client.get("/api/v1/providers", headers=headers)).json()
    gem = next(p for p in keys if p["name"] == "gemini")
    assert gem["keys"][0]["status"] == "active"  # a model-level limit never blocks the key


async def test_gemini_rate_limit_is_per_model_in_chat(client, sessions, redis, notifier):
    from app.services.llm import RateLimited

    class PerModel(ScriptedLLM):
        async def stream(self, req, usage):
            if req.model_name == "gemini-3.8-flash":
                self.calls.append(req)
                raise RateLimited("429 quota", retry_after=40)
            async for t in super().stream(req, usage):
                yield t

    llm = PerModel()
    runner = make_runner(sessions, redis, llm, notifier)
    client._transport.app.state.http_transport = httpx.MockTransport(gemini_api)
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "gemini"}, headers=headers)).json()
    await client.post(
        f"/api/v1/providers/{provider['id']}/keys",
        json={"label": "G", "api_key": "AIzaTESTKEY0000000000000000000"},
        headers=headers,
    )
    _, job_id = await send(client, headers, content="halo", model="auto")
    assert await runner.run(uuid.UUID(job_id)) == "done"
    async with sessions() as s:
        job = await s.get(Job, uuid.UUID(job_id))
    assert job.model_used == "gemini/gemini-3.8-pro"
    status = (await client.get("/api/v1/providers", headers=headers)).json()[0]["keys"][0]
    assert status["status"] == "active" and "kena limit" in status["last_error"]
    assert 0 < await redis.ttl(f"cool:{status['id']}:gemini-3.8-flash") <= 40
    # the next chat skips the cooled model without calling it again
    llm.calls.clear()
    _, job2 = await send(client, headers, content="halo lagi", model="auto")
    assert await runner.run(uuid.UUID(job2)) == "done"
    assert [c.model_name for c in llm.calls] == ["gemini-3.8-pro"]
