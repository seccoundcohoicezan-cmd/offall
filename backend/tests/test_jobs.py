import asyncio
import json
import uuid

from sqlalchemy import select

from app.api.jobs import job_event_stream
from app.models import Job, Message, UsageLog
from app.services.events import JobEvents, stream_key
from tests.conftest import ScriptedLLM, make_runner, register, send, setup_provider


def _parse(chunks):
    events = []
    for chunk in chunks:
        if chunk.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in chunk.strip().split("\n"))
        events.append((fields.get("id"), fields["event"], json.loads(fields["data"])))
    return events


def _text(events):
    out = ""
    for _, kind, data in events:
        if kind == "delta":
            out += data["text"]
        elif kind == "snapshot":
            out = data["text"]
    return out


async def test_post_message_returns_job_without_running_ai(client, queue, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    chat_id, job_id = await send(client, headers, content="Halo gateway")
    assert queue.jobs == [("run_job", (job_id,))]
    assert llm.calls == []
    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
    assert job["status"] == "queued"
    msgs = (await client.get(f"/api/v1/chats/{chat_id}/messages", headers=headers)).json()["items"]
    assert [m["role"] for m in msgs] == ["user"]
    chat = (await client.get(f"/api/v1/chats/{chat_id}", headers=headers)).json()
    assert chat["title"] == "Halo gateway"


async def test_worker_completes_and_persists(client, sessions, runner, notifier):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    chat_id, job_id = await send(client, headers)
    assert await runner.run(uuid.UUID(job_id)) == "done"
    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
    assert job["status"] == "done" and job["result_message_id"]
    msgs = (await client.get(f"/api/v1/chats/{chat_id}/messages", headers=headers)).json()["items"]
    assert msgs[-1]["role"] == "assistant" and msgs[-1]["content"] == "halo dari model palsu"
    assert msgs[-1]["model_used"].startswith("mock/")
    assert [e.kind for e in notifier.events] == ["job_done"]
    # Running again is a no-op: no duplicate message or bill.
    assert await runner.run(uuid.UUID(job_id)) == "skipped"
    async with sessions() as s:
        assert len((await s.scalars(select(UsageLog))).all()) == 1
        assert len((await s.scalars(select(Message).where(Message.role == "assistant"))).all()) == 1


async def test_job_survives_sse_disconnect_and_reconnect_gets_full_text(client, sessions, redis, notifier):
    release = asyncio.Event()
    words_sent = 0

    async def gate():
        nonlocal words_sent
        words_sent += 1
        if words_sent == 3:
            await release.wait()  # hold the worker until the client has gone away
        await asyncio.sleep(0)

    reply = "ini jawaban panjang yang dikirim sedikit demi sedikit"
    runner = make_runner(sessions, redis, ScriptedLLM(reply=reply, gate=gate), notifier)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers)
    events = JobEvents(redis)

    async def load():
        async with sessions() as s:
            return await s.get(Job, uuid.UUID(job_id))

    worker = asyncio.create_task(runner.run(uuid.UUID(job_id)))

    first_client = job_event_stream(events, load, job_id, None, block_ms=50)
    seen = []
    async for chunk in first_client:
        seen.append(chunk)
        if sum(1 for e in _parse(seen) if e[1] == "delta") == 2:
            break
    await first_client.aclose()  # user closes the tab
    release.set()
    assert await worker == "done"

    last_id = [e for e in _parse(seen) if e[0]][-1][0]
    resumed = [c async for c in job_event_stream(events, load, job_id, last_id, block_ms=50)]
    assert _text(_parse(seen)) + _text(_parse(resumed)) == reply
    assert _parse(resumed)[-1][1] == "done"

    fresh = [c async for c in job_event_stream(events, load, job_id, None, block_ms=50)]
    assert _text(_parse(fresh)) == reply

    await redis.delete(stream_key(job_id))  # stream TTL expired
    late = _parse([c async for c in job_event_stream(events, load, job_id, None, block_ms=50)])
    assert late[0][1] == "snapshot" and _text(late) == reply and late[-1][1] == "done"


async def test_stream_endpoint_after_done(client, runner):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers)
    await runner.run(uuid.UUID(job_id))
    resp = await client.get(f"/api/v1/jobs/{job_id}/stream", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse([c + "\n\n" for c in resp.text.strip().split("\n\n")])
    assert _text(events) == "halo dari model palsu"
    other = await register(client)
    assert (await client.get(f"/api/v1/jobs/{job_id}/stream", headers=other)).status_code == 404


async def test_cancel_queued_and_running(client, sessions, redis, notifier):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, queued = await send(client, headers)
    resp = await client.post(f"/api/v1/jobs/{queued}/cancel", headers=headers)
    assert resp.json()["status"] == "cancelled"
    llm = ScriptedLLM()
    runner = make_runner(sessions, redis, llm, notifier)
    assert await runner.run(uuid.UUID(queued)) == "skipped"
    assert llm.calls == []

    started = asyncio.Event()
    proceed = asyncio.Event()

    async def gate():
        started.set()
        await proceed.wait()

    runner = make_runner(sessions, redis, ScriptedLLM(reply="a b c d e f", gate=gate), notifier)
    _, running = await send(client, headers, content="lagi")
    task = asyncio.create_task(runner.run(uuid.UUID(running)))
    await started.wait()
    await client.post(f"/api/v1/jobs/{running}/cancel", headers=headers)
    proceed.set()
    assert await task == "cancelled"
    job = (await client.get(f"/api/v1/jobs/{running}", headers=headers)).json()
    assert job["status"] == "cancelled" and job["partial_output"] == "a "

    retry = await client.post(f"/api/v1/jobs/{queued}/retry", headers=headers)
    assert retry.status_code == 202


async def test_idempotency_key_prevents_duplicates(client, queue):
    headers = await register(client)
    chat = (await client.post("/api/v1/chats", json={}, headers=headers)).json()
    body = {"content": "sekali saja", "model": "auto", "idempotency_key": "abc-123"}
    r1 = await client.post(f"/api/v1/chats/{chat['id']}/messages", json=body, headers=headers)
    r2 = await client.post(f"/api/v1/chats/{chat['id']}/messages", json=body, headers=headers)
    assert r1.json() == r2.json()
    assert len(queue.jobs) == 1
    msgs = (await client.get(f"/api/v1/chats/{chat['id']}/messages", headers=headers)).json()
    assert msgs["total"] == 1


async def test_parallel_job_limit_and_message_length(client):
    headers = await register(client)
    chat = (await client.post("/api/v1/chats", json={}, headers=headers)).json()
    url = f"/api/v1/chats/{chat['id']}/messages"
    codes = [
        (await client.post(url, json={"content": f"m{i}"}, headers=headers)).status_code for i in range(4)
    ]
    assert codes == [202, 202, 202, 429]
    too_long = await client.post(url, json={"content": "x" * 20_001}, headers=headers)
    assert too_long.status_code == 422


async def test_semantic_cache_hit_on_same_question(client, sessions, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, j1 = await send(client, headers, content="Apa ibu kota Indonesia?")
    await runner.run(uuid.UUID(j1))
    _, j2 = await send(client, headers, content="apa ibu kota indonesia")
    await runner.run(uuid.UUID(j2))
    assert len(llm.calls) == 1
    async with sessions() as s:
        logs = (await s.scalars(select(UsageLog).order_by(UsageLog.created_at))).all()
    assert [log.cached for log in logs] == [False, True]
    assert logs[1].tokens_saved > 0
    summary = (await client.get("/api/v1/usage/summary", headers=headers)).json()
    assert summary["total"]["cache_hits"] == 1 and summary["total"]["requests"] == 2
    assert summary["per_key"][0]["requests"] == 1


async def test_agent_instructions_become_system_prompt(client, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    await client.patch(
        "/api/v1/settings", json={"system_prompt": "Jawab dalam bahasa Indonesia."}, headers=headers
    )
    agent = (
        await client.post(
            "/api/v1/agents", json={"name": "Strategist", "instructions": "Fokus strategi."}, headers=headers
        )
    ).json()
    chat = (await client.post("/api/v1/chats", json={"agent_id": agent["id"]}, headers=headers)).json()
    _, job_id = await send(client, headers, chat_id=chat["id"])
    await runner.run(uuid.UUID(job_id))
    system = llm.calls[0].messages[0]
    assert system["role"] == "system"
    assert "Jawab dalam bahasa Indonesia." in system["content"]
    assert "Strategist" in system["content"] and "Fokus strategi." in system["content"]


async def test_model_switch_mid_chat_keeps_history(client, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    chat_id, j1 = await send(client, headers, content="pertanyaan pertama", model="mock/mock-fast")
    await runner.run(uuid.UUID(j1))
    _, j2 = await send(client, headers, content="pertanyaan kedua", model="mock/mock-strong", chat_id=chat_id)
    await runner.run(uuid.UUID(j2))
    second = llm.calls[1]
    assert second.model_name == "mock-strong"
    assert [m["content"] for m in second.messages if m["role"] == "user"][0] == "pertanyaan pertama"
    chat = (await client.get(f"/api/v1/chats/{chat_id}", headers=headers)).json()
    assert chat["default_model"] == "mock/mock-strong"


async def test_jobs_list_filters_and_ownership(client, runner):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, done_id = await send(client, headers)
    await runner.run(uuid.UUID(done_id))
    await send(client, headers, content="kedua")
    page = (await client.get("/api/v1/jobs?status=done", headers=headers)).json()
    assert [j["id"] for j in page["items"]] == [done_id]
    active = (await client.get("/api/v1/jobs?active=true", headers=headers)).json()
    assert active["total"] == 1
    other = await register(client)
    assert (await client.get(f"/api/v1/jobs/{done_id}", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/jobs/{done_id}/cancel", headers=other)).status_code == 404
