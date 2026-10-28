import json
import uuid

import httpx

from app.services.memory import HttpMemoryStore, parse_extraction, wants_recall
from tests.conftest import ScriptedLLM, make_runner, register, send, setup_provider

EXTRACTED = json.dumps(
    {
        "memories": [
            {"kind": "preference", "content": "Pengguna suka jawaban singkat dalam bahasa Indonesia."},
            {"kind": "fact", "content": "Kata sandi pengguna adalah rahasia123."},
        ]
    }
)


async def _system(llm) -> str:
    first = llm.calls[0].messages[0]
    return first["content"] if first["role"] == "system" else ""


async def test_memory_crud_dedupe_and_ownership(client, queue):
    headers = await register(client)
    r = await client.post(
        "/api/v1/memories", json={"content": "Pengguna bekerja sebagai dosen di STEKOM."}, headers=headers
    )
    assert r.status_code == 201
    mid = r.json()["id"]
    dup = await client.post(
        "/api/v1/memories", json={"content": "Pengguna bekerja sebagai dosen di STEKOM"}, headers=headers
    )
    assert dup.json()["id"] == mid  # near-duplicate refreshes instead of piling up
    assert queue.jobs[-1][0] == "rebuild_profile"
    patched = await client.patch(
        f"/api/v1/memories/{mid}", json={"pinned": True, "kind": "context"}, headers=headers
    )
    assert patched.json()["pinned"] is True and patched.json()["kind"] == "context"
    other = await register(client)
    assert (await client.delete(f"/api/v1/memories/{mid}", headers=other)).status_code == 404
    assert (await client.get("/api/v1/memories", headers=other)).json()["total"] == 0
    assert (await client.delete(f"/api/v1/memories/{mid}", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/memories", headers=headers)).json()["total"] == 0


async def test_relevant_and_pinned_memories_are_injected(client, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    await client.post(
        "/api/v1/memories",
        json={"content": "Pengguna memakai Python dan FastAPI untuk backend."},
        headers=headers,
    )
    await client.post(
        "/api/v1/memories", json={"content": "Nama pengguna adalah Budi.", "pinned": True}, headers=headers
    )
    await client.post("/api/v1/memories", json={"content": "Kucing pengguna bernama Momo."}, headers=headers)
    chat_id, job_id = await send(client, headers, content="Bagaimana cara bikin endpoint FastAPI python?")
    await runner.run(uuid.UUID(job_id))
    system = await _system(llm)
    assert "Budi" in system and "FastAPI" in system
    msgs = (await client.get(f"/api/v1/chats/{chat_id}/messages", headers=headers)).json()["items"]
    assert msgs[-1]["memories_used"] >= 2
    mems = (await client.get("/api/v1/memories", headers=headers)).json()["items"]
    assert max(m["use_count"] for m in mems) >= 1


async def test_memory_can_be_switched_off(client, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    await client.post(
        "/api/v1/memories", json={"content": "Nama pengguna adalah Budi.", "pinned": True}, headers=headers
    )
    await client.patch("/api/v1/settings", json={"memory_enabled": False}, headers=headers)
    _, job_id = await send(client, headers)
    await runner.run(uuid.UUID(job_id))
    assert "Budi" not in await _system(llm)


async def test_learning_extracts_filters_secrets_and_builds_profile(client, sessions, redis, notifier):
    queued = []

    async def enqueue(name, arg):
        queued.append((name, arg))

    llm = ScriptedLLM(reply=EXTRACTED)
    runner = make_runner(sessions, redis, llm, notifier, enqueue=enqueue)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers, content="Tolong jawab singkat saja ya, pakai bahasa Indonesia.")
    assert await runner.run(uuid.UUID(job_id)) == "done"
    assert queued == [("learn_from_job", job_id)]
    assert await runner.learn(uuid.UUID(job_id)) == 1
    mems = (await client.get("/api/v1/memories", headers=headers)).json()["items"]
    assert [m["content"] for m in mems] == ["Pengguna suka jawaban singkat dalam bahasa Indonesia."]
    assert mems[0]["source"] == "auto" and mems[0]["status"] == "active"
    profile = (await client.get("/api/v1/memories/profile", headers=headers)).json()
    assert profile["active"] == 1 and profile["summary"]
    audit = (await client.get("/api/v1/audit", headers=headers)).json()["items"]
    actions = {a["action"] for a in audit}
    assert {"memory.create", "memory.profile_rebuild", "key.create"} <= actions
    assert all("rahasia123" not in json.dumps(a) for a in audit)


async def test_review_mode_keeps_new_memories_pending(client, sessions, redis, notifier):
    llm = ScriptedLLM(reply=EXTRACTED)
    runner = make_runner(sessions, redis, llm, notifier)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    await client.patch("/api/v1/settings", json={"memory_review": True}, headers=headers)
    _, job_id = await send(client, headers)
    await runner.run(uuid.UUID(job_id))
    assert await runner.learn(uuid.UUID(job_id)) == 1
    pending = (await client.get("/api/v1/memories?status=pending", headers=headers)).json()["items"]
    assert len(pending) == 1
    # pending memories are not used until approved
    _, job2 = await send(client, headers, content="jawab singkat bahasa Indonesia")
    llm.calls.clear()
    await runner.run(uuid.UUID(job2))
    assert "jawaban singkat" not in await _system(llm)
    await client.patch(f"/api/v1/memories/{pending[0]['id']}", json={"status": "active"}, headers=headers)
    assert (await client.get("/api/v1/memories/profile", headers=headers)).json()["active"] == 1


async def test_learning_respects_auto_extract_off(client, sessions, redis, notifier):
    queued = []

    async def enqueue(name, arg):
        queued.append(name)

    runner = make_runner(sessions, redis, ScriptedLLM(reply=EXTRACTED), notifier, enqueue=enqueue)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    await client.patch("/api/v1/settings", json={"memory_auto_extract": False}, headers=headers)
    _, job_id = await send(client, headers)
    await runner.run(uuid.UUID(job_id))
    assert queued == []
    assert await runner.learn(uuid.UUID(job_id)) == 0


async def test_history_search_and_recall_injection(client, runner, llm):
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    old_chat, j1 = await send(client, headers, content="Bagaimana setup kubernetes ingress dengan traefik?")
    await runner.run(uuid.UUID(j1))
    hits = (await client.get("/api/v1/search/messages?q=kubernetes", headers=headers)).json()
    assert hits and hits[0]["chat_id"] == old_chat and "kubernetes" in hits[0]["snippet"].lower()
    other = await register(client)
    assert (await client.get("/api/v1/search/messages?q=kubernetes", headers=other)).json() == []

    llm.calls.clear()
    _, j2 = await send(client, headers, content="Kita pernah bahas kubernetes ingress, lanjutkan yang itu")
    await runner.run(uuid.UUID(j2))
    system = await _system(llm)
    assert "Cuplikan percakapan lama" in system and "traefik" in system


async def test_external_memory_store_is_merged_and_mirrored(client, sessions, redis, notifier):
    seen = {"posts": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["posts"].append(json.loads(request.content))
            return httpx.Response(201, json={})
        return httpx.Response(200, json={"results": [{"content": "Pengguna tinggal di Semarang."}]})

    store = HttpMemoryStore("http://mem.example", "t0k", transport=httpx.MockTransport(handler))
    llm = ScriptedLLM(reply=EXTRACTED)
    runner = make_runner(sessions, redis, llm, notifier, external_memory=store)
    headers = await register(client)
    await setup_provider(client, headers, ["ok-aaaaaaaa"])
    _, job_id = await send(client, headers)
    await runner.run(uuid.UUID(job_id))
    assert "Semarang" in await _system(llm)
    await runner.learn(uuid.UUID(job_id))
    assert seen["posts"] and seen["posts"][0]["content"].startswith("Pengguna suka")

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    down = HttpMemoryStore("http://mem.example", transport=httpx.MockTransport(broken))
    assert await down.search(uuid.uuid4(), "x", 3) == []  # failures never break a chat


def test_parse_extraction_and_recall_cue():
    assert parse_extraction("bukan json") == []
    assert parse_extraction('ok {"memories":[{"kind":"weird","content":"Pengguna suka kopi."}]}') == [
        {"kind": "fact", "content": "Pengguna suka kopi."}
    ]
    assert parse_extraction('{"memories":[{"content":"API key: sk-abcdefghijkl"}]}') == []
    assert wants_recall("kita pernah bahas ini kan?")
    assert wants_recall("Remember when we talked about docker")
    assert not wants_recall("jelaskan docker")


async def test_admin_sees_all_audit_logs(client):
    admin = await register(client)
    member = await register(client)
    await client.post("/api/v1/memories", json={"content": "Pengguna suka teh manis."}, headers=member)
    own = (await client.get("/api/v1/audit?all_users=true", headers=member)).json()
    assert own["total"] == 1
    everyone = (await client.get("/api/v1/audit?all_users=true&action=memory", headers=admin)).json()
    assert everyone["total"] == 1
    assert (await client.get("/api/v1/audit", headers=admin)).json()["total"] == 0
