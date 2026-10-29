import base64
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

os.environ.update(
    {
        "MASTER_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
        "JWT_SECRET": "test-jwt-secret-that-is-long-enough-123",
        "ENABLE_MOCK_PROVIDER": "true",
        "DATABASE_URL": "sqlite+aiosqlite://",
        "RATE_LIMIT_PER_MINUTE": "10000",
        "LOGIN_RATE_LIMIT_PER_MINUTE": "1000",
    }
)

import fakeredis
import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.encryption import KeyCipher
from app.db.base import Base
from app.db.session import SessionFactory, set_session_factory
from app.main import create_app
from app.services.jobs import JobRunner
from app.services.llm import (
    InvalidKey,
    QuotaExhausted,
    RateLimited,
    StreamRequest,
    TransientError,
    Usage,
)
from app.services.notify import Event, Notifier
from app.services.runtime import build_runner

get_settings.cache_clear()


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> None:
        self.jobs.append((name, args))


class ScriptedLLM:
    """Behaviour is chosen by the API key so tests can script each account.

    "ok-*": streams `reply` word by word
    "rl-*": 429, "quota-*": 402, "bad-*": 401, "flaky-*": network error
    "cut-*": streams 2 words then drops the connection
    """

    def __init__(self, reply: str = "halo dari model palsu", gate: Any = None) -> None:
        self.reply = reply
        self.calls: list[StreamRequest] = []
        self.gate = gate

    async def stream(self, req: StreamRequest, usage: Usage) -> AsyncIterator[str]:
        self.calls.append(req)
        key = req.api_key or ""
        if key.startswith("rl-"):
            raise RateLimited("429", retry_after=30)
        if key.startswith("quota-"):
            raise QuotaExhausted("credit balance too low")
        if key.startswith("bad-"):
            raise InvalidKey("401")
        if key.startswith("flaky-"):
            raise TransientError("connection reset")
        words = self.reply.split(" ")
        usage.tokens_in = 10
        for i, word in enumerate(words):
            if self.gate is not None:
                await self.gate()
            if key.startswith("cut-") and i == 2:
                raise TransientError("stream dropped")
            usage.tokens_out += 1
            yield word + (" " if i < len(words) - 1 else "")


class RecordingNotifier(Notifier):
    def __init__(self) -> None:
        super().__init__([])
        self.events: list[Event] = []

    async def notify(self, user: Any, event: Event) -> None:
        self.events.append(event)


@pytest.fixture
async def sessions(tmp_path) -> AsyncIterator[SessionFactory]:
    # TEST_DATABASE_URL=postgresql+asyncpg://... runs the suite against real Postgres (CI does).
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    set_session_factory(factory)
    yield factory
    await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[Any]:
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer())
    yield client
    await client.aclose()


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
async def client(sessions, redis, queue) -> AsyncIterator[AsyncClient]:
    app = create_app(redis=redis, queue=queue)
    # Tests never reach real provider APIs: model discovery/probes hit this offline stub
    # unless a test installs its own transport.
    app.state.http_transport = httpx.MockTransport(lambda request: httpx.Response(503))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def cipher() -> KeyCipher:
    return KeyCipher(get_settings().master_encryption_key)


def make_runner(sessions, redis, llm, notifier, **pool_kw: Any) -> JobRunner:
    return build_runner(
        sessions, redis, get_settings(), llm=llm, notifier=notifier, busy_wait=0.01, busy_timeout=2, **pool_kw
    )


@pytest.fixture
def runner(sessions, redis, llm, notifier) -> JobRunner:
    return make_runner(sessions, redis, llm, notifier)


async def register(client: AsyncClient, email: str | None = None) -> dict[str, str]:
    email = email or f"u{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": "rahasia123"})
    assert resp.status_code == 201, resp.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def setup_provider(
    client: AsyncClient,
    headers: dict[str, str],
    keys: list[str],
    name: str = "mock",
    strategy: str = "fill_first",
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/providers", json={"name": name, "rotation_strategy": strategy}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    provider = resp.json()
    provider["key_ids"] = []
    for i, secret in enumerate(keys):
        r = await client.post(
            f"/api/v1/providers/{provider['id']}/keys",
            json={"label": f"Akun {chr(65 + i)}", "api_key": secret},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        provider["key_ids"].append(r.json()["id"])
    return provider


async def send(
    client: AsyncClient,
    headers: dict[str, str],
    content: str = "halo",
    model: str = "auto",
    chat_id: str | None = None,
) -> tuple[str, str]:
    if chat_id is None:
        chat = await client.post("/api/v1/chats", json={}, headers=headers)
        chat_id = chat.json()["id"]
    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"content": content, "model": model}, headers=headers
    )
    assert resp.status_code == 202, resp.text
    return chat_id, resp.json()["job_id"]
