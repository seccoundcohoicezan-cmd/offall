from tests.conftest import register, send, setup_provider


async def _pair(client):
    admin = await register(client, "owner@example.com")  # first user -> admin
    member = await register(client, "member@example.com")
    return admin, member


async def test_only_admin_can_manage_users(client):
    admin, member = await _pair(client)
    assert (await client.get("/api/v1/admin/users", headers=member)).status_code == 403
    page = (await client.get("/api/v1/admin/users", headers=admin)).json()
    assert [u["email"] for u in page["items"]] == ["owner@example.com", "member@example.com"]
    assert page["items"][0]["role"] == "admin"
    found = (await client.get("/api/v1/admin/users?q=memb", headers=admin)).json()
    assert found["total"] == 1


async def test_admin_creates_user_who_can_log_in(client):
    admin, _ = await _pair(client)
    created = await client.post(
        "/api/v1/admin/users",
        json={"email": "Baru@Example.com", "password": "rahasia123", "display_name": "Baru"},
        headers=admin,
    )
    assert created.status_code == 201 and created.json()["email"] == "baru@example.com"
    dup = await client.post(
        "/api/v1/admin/users", json={"email": "baru@example.com", "password": "rahasia123"}, headers=admin
    )
    assert dup.status_code == 409
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login", json={"email": "baru@example.com", "password": "rahasia123"}
    )
    assert login.status_code == 200


async def test_disable_blocks_login_tokens_and_jobs(client):
    admin, member = await _pair(client)
    await setup_provider(client, member, ["ok-aaaaaaaa"])
    _, job_id = await send(client, member)
    users = (await client.get("/api/v1/admin/users", headers=admin)).json()["items"]
    member_id = next(u["id"] for u in users if u["email"] == "member@example.com")
    r = await client.patch(f"/api/v1/admin/users/{member_id}", json={"is_active": False}, headers=admin)
    assert r.json()["is_active"] is False and r.json()["chats"] == 1
    assert (await client.get("/api/v1/chats", headers=member)).status_code == 403
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login", json={"email": "member@example.com", "password": "rahasia123"}
    )
    assert login.status_code == 403
    assert (await client.get(f"/api/v1/jobs/{job_id}", headers=admin)).status_code == 404  # still private
    await client.patch(f"/api/v1/admin/users/{member_id}", json={"is_active": True}, headers=admin)
    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=member)).json()
    assert job["status"] == "cancelled"


async def test_reset_password_and_role(client):
    admin, member = await _pair(client)
    users = (await client.get("/api/v1/admin/users", headers=admin)).json()["items"]
    member_id = next(u["id"] for u in users if u["email"] == "member@example.com")
    await client.patch(
        f"/api/v1/admin/users/{member_id}", json={"password": "passwordbaru1", "role": "admin"}, headers=admin
    )
    client.cookies.clear()
    old = await client.post(
        "/api/v1/auth/login", json={"email": "member@example.com", "password": "rahasia123"}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login", json={"email": "member@example.com", "password": "passwordbaru1"}
    )
    assert new.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new.json()['access_token']}"}
    )
    assert me.json()["role"] == "admin"


async def test_last_admin_and_self_protection(client):
    admin, _ = await _pair(client)
    me = (await client.get("/api/v1/auth/me", headers=admin)).json()
    demote = await client.patch(f"/api/v1/admin/users/{me['id']}", json={"role": "user"}, headers=admin)
    assert demote.status_code == 400 and demote.json()["error"]["code"] == "last_admin"
    assert (await client.delete(f"/api/v1/admin/users/{me['id']}", headers=admin)).status_code == 400


async def test_delete_user(client):
    admin, _ = await _pair(client)
    users = (await client.get("/api/v1/admin/users", headers=admin)).json()["items"]
    member_id = next(u["id"] for u in users if u["email"] == "member@example.com")
    assert (await client.delete(f"/api/v1/admin/users/{member_id}", headers=admin)).status_code == 204
    assert (await client.get("/api/v1/admin/users", headers=admin)).json()["total"] == 1


async def test_admin_toggles_registration(client):
    admin, member = await _pair(client)
    assert (await client.get("/api/v1/auth/config")).json() == {"registration_open": True}
    assert (
        await client.patch("/api/v1/admin/settings", json={"registration_open": False}, headers=member)
    ).status_code == 403
    r = await client.patch("/api/v1/admin/settings", json={"registration_open": False}, headers=admin)
    assert r.json() == {"registration_open": False}
    assert (await client.get("/api/v1/auth/config")).json() == {"registration_open": False}
    client.cookies.clear()
    blocked = await client.post(
        "/api/v1/auth/register", json={"email": "x@example.com", "password": "rahasia123"}
    )
    assert blocked.status_code == 403
    # admin can still add people while sign-up is closed
    ok = await client.post(
        "/api/v1/admin/users", json={"email": "x@example.com", "password": "rahasia123"}, headers=admin
    )
    assert ok.status_code == 201
