import logging

from sqlalchemy import select

from app.models import ProviderKey
from tests.conftest import register, setup_provider

SECRET = "sk-ant-api03-VERYSECRETVALUE-9xYz"


async def test_add_key_is_encrypted_and_masked(client, sessions, cipher, caplog):
    caplog.set_level(logging.DEBUG)
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "anthropic"}, headers=headers)).json()
    resp = await client.post(
        f"/api/v1/providers/{provider['id']}/keys",
        json={"label": "Akun A", "api_key": SECRET},
        headers=headers,
    )
    assert resp.status_code == 201
    assert SECRET not in resp.text
    assert resp.json()["key_hint"] == "sk-...9xYz"

    listing = await client.get("/api/v1/providers", headers=headers)
    assert SECRET not in listing.text
    assert listing.json()[0]["status_counts"]["active"] == 1

    async with sessions() as s:
        key = (await s.scalars(select(ProviderKey))).one()
    assert SECRET not in key.api_key_encrypted
    assert cipher.decrypt(key.api_key_encrypted) == SECRET
    assert SECRET not in caplog.text


async def test_models_listed_only_with_active_key(client):
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "openai"}, headers=headers)).json()
    assert (await client.get("/api/v1/models", headers=headers)).json() == []
    key = await client.post(
        f"/api/v1/providers/{provider['id']}/keys",
        json={"label": "A", "api_key": "sk-proj-123456789"},
        headers=headers,
    )
    models = (await client.get("/api/v1/models", headers=headers)).json()
    assert {m["id"] for m in models} == {"openai/gpt-4o", "openai/gpt-4o-mini"}
    await client.patch(
        f"/api/v1/providers/{provider['id']}/keys/{key.json()['id']}",
        json={"enabled": False},
        headers=headers,
    )
    assert (await client.get("/api/v1/models", headers=headers)).json() == []


async def test_key_crud_and_strategy(client):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["ok-aaaaaaaa", "ok-bbbbbbbb"])
    pid, (ka, kb) = provider["id"], provider["key_ids"]
    patched = await client.patch(
        f"/api/v1/providers/{pid}/keys/{kb}", json={"priority": 0, "label": "Utama"}, headers=headers
    )
    assert patched.json()["label"] == "Utama"
    await client.patch(f"/api/v1/providers/{pid}/keys/{ka}", json={"priority": 5}, headers=headers)
    keys = (await client.get("/api/v1/providers", headers=headers)).json()[0]["keys"]
    assert [k["id"] for k in keys] == [kb, ka]
    strat = await client.patch(
        f"/api/v1/providers/{pid}", json={"rotation_strategy": "round_robin"}, headers=headers
    )
    assert strat.json()["rotation_strategy"] == "round_robin"
    assert (
        await client.patch(f"/api/v1/providers/{pid}", json={"rotation_strategy": "x"}, headers=headers)
    ).status_code == 422
    assert (await client.delete(f"/api/v1/providers/{pid}/keys/{ka}", headers=headers)).status_code == 204
    keys = (await client.get("/api/v1/providers", headers=headers)).json()[0]["keys"]
    assert [k["id"] for k in keys] == [kb]


async def test_duplicate_provider_rejected(client):
    headers = await register(client)
    await client.post("/api/v1/providers", json={"name": "groq"}, headers=headers)
    dup = await client.post("/api/v1/providers", json={"name": "groq"}, headers=headers)
    assert dup.status_code == 409


async def test_other_user_cannot_touch_provider(client):
    owner = await register(client)
    provider = await setup_provider(client, owner, ["ok-aaaaaaaa"])
    intruder = await register(client)
    pid, kid = provider["id"], provider["key_ids"][0]
    assert (
        await client.patch(
            f"/api/v1/providers/{pid}", json={"rotation_strategy": "least_used"}, headers=intruder
        )
    ).status_code == 404
    assert (await client.delete(f"/api/v1/providers/{pid}/keys/{kid}", headers=intruder)).status_code == 404
    assert (
        await client.post(
            f"/api/v1/providers/{pid}/keys", json={"label": "x", "api_key": "ok-12345678"}, headers=intruder
        )
    ).status_code == 404
    assert (await client.get("/api/v1/providers", headers=intruder)).json() == []


async def test_key_test_endpoint_marks_invalid(client):
    headers = await register(client)
    provider = await setup_provider(client, headers, ["invalid-key-123", "good-key-1234"])
    pid, (bad, good) = provider["id"], provider["key_ids"]
    r = await client.post(f"/api/v1/providers/{pid}/keys/{bad}/test", headers=headers)
    assert r.json()["ok"] is False and r.json()["status"] == "invalid"
    r = await client.post(f"/api/v1/providers/{pid}/keys/{good}/test", headers=headers)
    assert r.json() == {"ok": True, "status": "active", "message": "Koneksi berhasil."}


async def test_short_key_rejected(client):
    headers = await register(client)
    provider = (await client.post("/api/v1/providers", json={"name": "openai"}, headers=headers)).json()
    r = await client.post(
        f"/api/v1/providers/{provider['id']}/keys", json={"label": "A", "api_key": "abc"}, headers=headers
    )
    assert r.status_code == 422


async def test_agents_crud(client):
    headers = await register(client)
    created = await client.post(
        "/api/v1/agents",
        json={
            "name": "Data Analyst",
            "instructions": "Analisis data secara ringkas.",
            "description": "Analisis",
        },
        headers=headers,
    )
    assert created.status_code == 201
    aid = created.json()["id"]
    patched = await client.patch(f"/api/v1/agents/{aid}", json={"is_enabled": False}, headers=headers)
    assert patched.json()["is_enabled"] is False
    other = await register(client)
    assert (await client.patch(f"/api/v1/agents/{aid}", json={"name": "x"}, headers=other)).status_code == 404
    assert len((await client.get("/api/v1/agents", headers=headers)).json()) == 1
    assert (await client.delete(f"/api/v1/agents/{aid}", headers=headers)).status_code == 204
