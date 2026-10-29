import json
import logging
import types
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import update

from app import worker
from app.core.logging import JsonFormatter, setup_logging
from app.db.base import utcnow
from app.models import Chat, Job
from app.services import llm as llm_mod
from app.services.llm import (
    BadRequest,
    InvalidKey,
    LiteLLMClient,
    MockLLMClient,
    QuotaExhausted,
    RateLimited,
    RoutingLLMClient,
    StreamRequest,
    TransientError,
    Usage,
    classify_error,
)
from app.services.notify import Event, Notifier, TelegramChannel
from tests.conftest import ScriptedLLM, make_runner, register, send, setup_provider


class FakeArq:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, *args, **kw):
        self.enqueued.append((name, args))


class ProviderError(Exception):
    def __init__(self, message, status_code=None, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = types.SimpleNamespace(headers=headers or {})


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ProviderError("slow down", 429, {"retry-after": "12"}), RateLimited),
        # OpenAI billing exhaustion carries the insufficient_quota code
        (
            ProviderError(
                '{"error":{"message":"You exceeded your current quota","code":"insufficient_quota"}}', 429
            ),
            QuotaExhausted,
        ),
        # Gemini free-tier per-minute/day windows use the same words but are a rate limit
        (
            ProviderError(
                '{"error":{"code":429,"message":"You exceeded your current quota",'
                '"status":"RESOURCE_EXHAUSTED"}}',
                429,
            ),
            RateLimited,
        ),
        (ProviderError("Your credit balance is too low", 400), QuotaExhausted),
        (ProviderError("payment", 402), QuotaExhausted),
        (ProviderError("bad key", 401), InvalidKey),
        (ProviderError("forbidden", 403), InvalidKey),
        (ProviderError("context too long", 400), BadRequest),
        (ProviderError("upstream", 503), TransientError),
        (ConnectionError("reset"), TransientError),
    ],
)
def test_classify_error(exc, kind):
    assert isinstance(classify_error(exc), kind)


def test_gemini_retry_delay_parsed():
    body = (
        '{"error":{"code":429,"details":'
        '[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"37s"}]}}'
    )
    err = classify_error(ProviderError(body, 429))
    assert isinstance(err, RateLimited) and err.retry_after == 37.0


def test_retry_after_parsed():
    err = classify_error(ProviderError("slow down", 429, {"retry-after": "12"}))
    assert err.retry_after == 12.0
    err = classify_error(ProviderError("Please retry after 7 seconds", 429))
    assert err.retry_after == 7.0


def _req(key="k", provider="openai"):
    return StreamRequest(provider, "gpt-4o-mini", [{"role": "user", "content": "hai"}], key, None, 10)


async def test_litellm_client_streams_and_maps_errors(monkeypatch):
    import litellm

    def chunk(text=None, usage=None):
        delta = types.SimpleNamespace(content=text)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(delta=delta)] if text else [], usage=usage
        )

    captured = {}

    async def fake_acompletion(**kw):
        captured.update(kw)

        async def gen():
            yield chunk("ha")
            yield chunk("lo")
            yield chunk(usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=2))

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    usage = Usage()
    out = [t async for t in LiteLLMClient().stream(_req("sk-test-123"), usage)]
    assert out == ["ha", "lo"] and (usage.tokens_in, usage.tokens_out) == (5, 2)
    assert captured["model"] == "openai/gpt-4o-mini" and captured["api_key"] == "sk-test-123"

    async def failing(**kw):
        raise ProviderError("rate", 429)

    monkeypatch.setattr(litellm, "acompletion", failing)
    with pytest.raises(RateLimited):
        [t async for t in LiteLLMClient().stream(_req(), Usage())]


async def test_mock_and_routing_clients():
    mock = MockLLMClient(delay=0)
    text = "".join([t async for t in mock.stream(_req("demo-key", "mock"), Usage())])
    assert "Jawaban untuk: hai" in text
    for key, exc in (("x-ratelimit", RateLimited), ("x-quota", QuotaExhausted), ("x-invalid", InvalidKey)):
        with pytest.raises(exc):
            [t async for t in mock.stream(_req(key, "mock"), Usage())]
    routing = RoutingLLMClient(real=ScriptedLLM(), mock=None)
    with pytest.raises(InvalidKey):
        routing.stream(_req("k", "mock"), Usage())
    assert routing.stream(_req("ok-1", "openai"), Usage()) is not None
    assert llm_mod.PROVIDERS["ollama"].needs_key is False


async def test_telegram_channel_and_notifier_swallow_errors(monkeypatch):
    sent = {}

    def handler(request):
        sent["url"] = str(request.url)
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler))
    )
    user = types.SimpleNamespace(id=uuid.uuid4(), settings={"notify_telegram_chat_id": "42"})
    await TelegramChannel("BOT").send(user, Event("job_done", "Selesai", "isi"))
    assert sent["body"] == {"chat_id": "42", "text": "Selesai\nisi"}

    class Boom:
        async def send(self, user, event):
            raise RuntimeError("down")

    await Notifier([Boom()]).notify(user, Event("job_done", "a", "b"))  # must not raise


def test_json_logging_redacts(capsys):
    setup_logging()
    logging.getLogger("t").info("key sk-ant-api03-abcdefghijk used", extra={"job_id": "j1", "key_id": "k1"})
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["job_id"] == "j1" and "abcdefghijk" not in line["msg"]
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "x", None, None)
    assert json.loads(JsonFormatter().format(record))["level"] == "ERROR"


async def test_worker_entrypoints(client, sessions, redis, notifier, monkeypatch):
    llm = ScriptedLLM()
    ctx = {"redis": FakeArq(), "sessions": sessions, "runner": make_runner(sessions, redis, llm, notifier)}
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers)
    assert await worker.run_job(ctx, job_id) == "done"

    _, waiting = await send(client, headers, content="kedua")
    _, stale = await send(client, headers, content="ketiga")
    async with sessions() as s:
        await s.execute(
            update(Job).where(Job.id == uuid.UUID(waiting)).values(status="waiting_quota", retry_at=None)
        )
        await s.execute(
            update(Job)
            .where(Job.id == uuid.UUID(stale))
            .values(status="running", started_at=utcnow() - timedelta(hours=3))
        )
        await s.commit()
    assert await worker.resume_waiting(ctx) == 2
    assert {args[0] for _, args in ctx["redis"].enqueued} == {waiting, stale}

    startup_ctx = {"redis": redis}
    await worker.startup(startup_ctx)
    assert "runner" in startup_ctx


async def test_rolling_summary_used_for_long_chat(client, sessions, redis, notifier):
    llm = ScriptedLLM(reply="ringkasan singkat")
    runner = make_runner(sessions, redis, llm, notifier)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    chat_id = None
    for i in range(13):
        chat_id, job_id = await send(
            client, headers, content=f"pertanyaan unik nomor {i} soal {i * 13}", chat_id=chat_id
        )
        assert await runner.run(uuid.UUID(job_id)) == "done"
    async with sessions() as s:
        chat = await s.get(Chat, uuid.UUID(chat_id))
    assert chat.summary_upto > 0 and chat.summary
    last = llm.calls[-1].messages
    assert any(m["role"] == "system" and "Ringkasan percakapan" in m["content"] for m in last)
    assert any("Ringkas percakapan" in str(c.messages[0]["content"]) for c in llm.calls)


def test_prompt_cache_marks_long_anthropic_system_prompt():
    long_system = {"role": "system", "content": "aturan " * 1000}
    msgs = [long_system, {"role": "user", "content": "hai"}]
    cached = llm_mod.with_prompt_cache("anthropic", msgs)
    assert cached[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert cached[1] == msgs[1]
    assert llm_mod.with_prompt_cache("openai", msgs) == msgs
    short = [{"role": "system", "content": "pendek"}]
    assert llm_mod.with_prompt_cache("anthropic", short) == short
