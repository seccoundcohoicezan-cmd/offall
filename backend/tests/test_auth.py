from app.core.config import get_settings
from tests.conftest import register


async def test_register_login_me(client):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "A@Example.com", "password": "rahasia123"}
    )
    assert resp.status_code == 201
    assert "offall_access" in resp.cookies
    client.cookies.clear()
    login = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "rahasia123"})
    assert login.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.json()["email"] == "a@example.com"
    assert me.json()["role"] == "admin"  # first user


async def test_cookie_auth_works(client):
    await client.post("/api/v1/auth/register", json={"email": "c@example.com", "password": "rahasia123"})
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_wrong_password_and_duplicate(client):
    await register(client, "b@example.com")
    bad = await client.post("/api/v1/auth/login", json={"email": "b@example.com", "password": "salah12345"})
    assert bad.status_code == 401
    assert bad.json() == {"error": {"code": "invalid_credentials", "message": "Email atau password salah."}}
    dup = await client.post(
        "/api/v1/auth/register", json={"email": "b@example.com", "password": "rahasia123"}
    )
    assert dup.status_code == 409


async def test_validation_error_shape(client):
    resp = await client.post("/api/v1/auth/register", json={"email": "x", "password": "1"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_requires_auth(client):
    resp = await client.get("/api/v1/chats")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_refresh_rotates_and_revokes(client):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "r@example.com", "password": "rahasia123"}
    )
    refresh = resp.json()["refresh_token"]
    client.cookies.clear()
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert first.status_code == 200
    client.cookies.clear()
    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert reused.status_code == 401


async def test_access_token_rejected_as_refresh(client):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "t@example.com", "password": "rahasia123"}
    )
    client.cookies.clear()
    bad = await client.post("/api/v1/auth/refresh", json={"refresh_token": resp.json()["access_token"]})
    assert bad.status_code == 401


async def test_logout_revokes_refresh_cookie(client):
    await client.post("/api/v1/auth/register", json={"email": "l@example.com", "password": "rahasia123"})
    refresh_cookie = client.cookies.get("offall_refresh")
    assert refresh_cookie
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.clear()
    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_cookie})
    assert again.status_code == 401


async def test_registration_can_be_closed(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "registration_open", False)
    resp = await client.post(
        "/api/v1/auth/register", json={"email": "z@example.com", "password": "rahasia123"}
    )
    assert resp.status_code == 403


async def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_limit_per_minute", 3)
    codes = [
        (
            await client.post("/api/v1/auth/login", json={"email": "n@example.com", "password": "rahasia123"})
        ).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok"}


def test_production_rejects_dev_secrets():
    import pytest

    from app.core.config import Settings
    from app.main import DEV_PLACEHOLDERS, check_secrets

    base = {"master_encryption_key": DEV_PLACEHOLDERS[0], "jwt_secret": DEV_PLACEHOLDERS[1]}
    check_secrets(Settings(environment="development", **base))
    with pytest.raises(RuntimeError):
        check_secrets(Settings(environment="production", **base))
    with pytest.raises(RuntimeError):
        check_secrets(Settings(environment="production", master_encryption_key="x", jwt_secret="short"))
    with pytest.raises(RuntimeError):
        check_secrets(Settings(master_encryption_key="", jwt_secret=""))
