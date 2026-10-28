import uuid

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core.deps import DB, AppSettings, Cipher, CurrentUser
from app.core.encryption import mask_key
from app.core.errors import ApiError, not_found
from app.db.base import utcnow
from app.models import AIModel, KeyStatus, Provider, ProviderKey
from app.schemas import (
    CustomModelIn,
    KeyIn,
    KeyOut,
    KeyPatch,
    KeyTestOut,
    ModelSyncOut,
    ProviderIn,
    ProviderOut,
    ProviderPatch,
)
from app.services import audit
from app.services.catalog import PROVIDERS
from app.services.key_pool import is_usable
from app.services.llm import NO_KEY, InvalidKey, LLMError, QuotaExhausted, RateLimited, StreamRequest, Usage

router = APIRouter(prefix="/providers", tags=["providers"])
MAX_KEYS_PER_PROVIDER = 50


def _out(provider: Provider, keys: list[ProviderKey]) -> ProviderOut:
    now = utcnow()
    counts = {s.value: 0 for s in KeyStatus}
    for k in keys:
        counts[k.status] = counts.get(k.status, 0) + 1
    return ProviderOut(
        id=provider.id,
        name=provider.name,
        display_name=PROVIDERS[provider.name].display if provider.name in PROVIDERS else provider.name,
        base_url=provider.base_url,
        rotation_strategy=provider.rotation_strategy,
        created_at=provider.created_at,
        keys=[KeyOut.model_validate(k) for k in keys],
        status_counts=counts,
        usable_keys=sum(1 for k in keys if is_usable(k, now)),
    )


async def _owned(db: DB, user_id: uuid.UUID, provider_id: uuid.UUID) -> Provider:
    provider = await db.get(Provider, provider_id)
    if provider is None or provider.user_id != user_id:
        raise not_found("provider")
    return provider


async def _keys(db: DB, provider_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ProviderKey]]:
    rows = (
        await db.scalars(
            select(ProviderKey)
            .where(ProviderKey.provider_id.in_(provider_ids))
            .order_by(ProviderKey.priority, ProviderKey.created_at)
        )
    ).all()
    grouped: dict[uuid.UUID, list[ProviderKey]] = {pid: [] for pid in provider_ids}
    for k in rows:
        grouped[k.provider_id].append(k)
    return grouped


@router.get("", response_model=list[ProviderOut])
async def list_providers(db: DB, user: CurrentUser) -> list[ProviderOut]:
    providers = (
        await db.scalars(select(Provider).where(Provider.user_id == user.id).order_by(Provider.created_at))
    ).all()
    keys = await _keys(db, [p.id for p in providers])
    return [_out(p, keys[p.id]) for p in providers]


@router.post("", response_model=ProviderOut, status_code=201)
async def create_provider(
    body: ProviderIn, db: DB, user: CurrentUser, settings: AppSettings, cipher: Cipher
) -> ProviderOut:
    if body.name == "mock" and not settings.enable_mock_provider:
        raise ApiError(400, "provider_disabled", "Provider mock tidak aktif di server ini.")
    exists = await db.scalar(select(Provider).where(Provider.user_id == user.id, Provider.name == body.name))
    if exists:
        raise ApiError(409, "provider_exists", "Provider ini sudah ada. Tambahkan key ke provider tersebut.")
    provider = Provider(
        user_id=user.id, name=body.name, base_url=body.base_url, rotation_strategy=body.rotation_strategy
    )
    db.add(provider)
    await db.flush()
    spec_info = PROVIDERS[body.name]
    if not spec_info.needs_key:
        # Keyless gateways (Ollama, 9Router without auth) work right away; a real key can be added later.
        db.add(
            ProviderKey(
                provider_id=provider.id,
                label="Default (tanpa key)",
                api_key_encrypted=cipher.encrypt(NO_KEY),
                key_hint="tanpa key",
                priority=0,
            )
        )
    for spec in spec_info.models:
        db.add(
            AIModel(
                provider_id=provider.id,
                model_name=spec.name,
                display_name=spec.display,
                tier=spec.tier,
                cost_in=spec.cost_in,
                cost_out=spec.cost_out,
                context_window=spec.context,
            )
        )
    await db.commit()
    return _out(provider, (await _keys(db, [provider.id]))[provider.id])


@router.patch("/{provider_id}", response_model=ProviderOut)
async def patch_provider(
    provider_id: uuid.UUID, body: ProviderPatch, db: DB, user: CurrentUser
) -> ProviderOut:
    provider = await _owned(db, user.id, provider_id)
    if body.rotation_strategy is not None:
        provider.rotation_strategy = body.rotation_strategy
    if body.base_url is not None:
        provider.base_url = body.base_url or None
    await db.commit()
    return _out(provider, (await _keys(db, [provider.id]))[provider.id])


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(provider_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    provider = await _owned(db, user.id, provider_id)
    await db.delete(provider)
    await db.commit()


@router.post("/{provider_id}/keys", response_model=KeyOut, status_code=201)
async def add_key(
    provider_id: uuid.UUID, body: KeyIn, db: DB, user: CurrentUser, cipher: Cipher
) -> ProviderKey:
    provider = await _owned(db, user.id, provider_id)
    secret = body.api_key.strip()
    if PROVIDERS[provider.name].needs_key and len(secret) < 8:
        raise ApiError(422, "validation_error", "api_key: API key terlalu pendek.")
    count = await db.scalar(
        select(func.count()).select_from(ProviderKey).where(ProviderKey.provider_id == provider.id)
    )
    if (count or 0) >= MAX_KEYS_PER_PROVIDER:
        raise ApiError(400, "too_many_keys", "Batas key per provider tercapai.")
    priority = body.priority
    if priority is None:
        top = await db.scalar(
            select(func.max(ProviderKey.priority)).where(ProviderKey.provider_id == provider.id)
        )
        priority = 0 if top is None else top + 1
    key = ProviderKey(
        provider_id=provider.id,
        label=body.label,
        api_key_encrypted=cipher.encrypt(secret or NO_KEY),
        key_hint=mask_key(secret) if secret else "tanpa key",
        priority=priority,
        daily_token_quota=body.daily_token_quota,
    )
    db.add(key)
    await db.flush()
    audit.record(db, user.id, "user", "key.create", str(key.id), provider=provider.name, hint=key.key_hint)
    await db.commit()
    return key


async def _owned_key(
    db: DB, user_id: uuid.UUID, provider_id: uuid.UUID, key_id: uuid.UUID
) -> tuple[Provider, ProviderKey]:
    provider = await _owned(db, user_id, provider_id)
    key = await db.get(ProviderKey, key_id)
    if key is None or key.provider_id != provider.id:
        raise not_found("key")
    return provider, key


@router.patch("/{provider_id}/keys/{key_id}", response_model=KeyOut)
async def patch_key(
    provider_id: uuid.UUID, key_id: uuid.UUID, body: KeyPatch, db: DB, user: CurrentUser
) -> ProviderKey:
    _, key = await _owned_key(db, user.id, provider_id, key_id)
    if body.label is not None:
        key.label = body.label
    if body.priority is not None:
        key.priority = body.priority
    if body.daily_token_quota is not None:
        key.daily_token_quota = body.daily_token_quota or None
    if body.enabled is False:
        key.status = KeyStatus.disabled
    elif body.enabled is True:
        key.status = KeyStatus.active
        key.cooldown_until = None
        key.reset_at = None
        key.last_error = None
    await db.commit()
    return key


@router.delete("/{provider_id}/keys/{key_id}", status_code=204)
async def delete_key(provider_id: uuid.UUID, key_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    provider, key = await _owned_key(db, user.id, provider_id, key_id)
    audit.record(db, user.id, "user", "key.delete", str(key.id), provider=provider.name, hint=key.key_hint)
    await db.delete(key)
    await db.commit()


@router.post("/{provider_id}/keys/{key_id}/test", response_model=KeyTestOut)
async def test_key(
    provider_id: uuid.UUID,
    key_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    cipher: Cipher,
    settings: AppSettings,
) -> KeyTestOut:
    from app.services.runtime import build_llm

    provider, key = await _owned_key(db, user.id, provider_id, key_id)
    model = await db.scalar(
        select(AIModel)
        .where(AIModel.provider_id == provider.id)
        .order_by(AIModel.tier.desc(), AIModel.cost_out)
    )
    if model is None:
        raise ApiError(400, "no_model", "Provider belum punya model.")
    llm = build_llm(settings)
    req = StreamRequest(
        provider=provider.name,
        model_name=model.model_name,
        messages=[{"role": "user", "content": "ping"}],
        api_key=cipher.decrypt(key.api_key_encrypted),
        base_url=provider.base_url,
        max_tokens=1,
    )
    try:
        async for _ in llm.stream(req, Usage()):
            break
    except InvalidKey as exc:
        key.status, key.last_error = KeyStatus.invalid, str(exc)[:500]
        await db.commit()
        return KeyTestOut(ok=False, status=key.status, message="Key ditolak provider (401/403).")
    except RateLimited:
        return KeyTestOut(ok=True, status=key.status, message="Key valid tapi sedang kena rate limit.")
    except QuotaExhausted:
        return KeyTestOut(ok=False, status=key.status, message="Kredit/kuota key habis.")
    except LLMError as exc:
        return KeyTestOut(ok=False, status=key.status, message=f"Gagal terhubung: {type(exc).__name__}")
    if key.status == KeyStatus.invalid:
        key.status = KeyStatus.active
    key.last_error = None
    await db.commit()
    return KeyTestOut(ok=True, status=key.status, message="Koneksi berhasil.")


STRONG_HINTS = (
    "opus",
    "sonnet",
    "gpt-4",
    "gpt-5",
    "o1",
    "o3",
    "pro",
    "large",
    "70b",
    "405b",
    "r1",
    "qwen3-coder",
)


CHEAP_HINTS = ("mini", "nano", "flash", "haiku", "small", "lite", "8b", "7b", "3b", "instant", "free")


def guess_tier(name: str) -> str:
    low = name.lower()
    if any(h in low for h in CHEAP_HINTS):
        return "cheap"
    return "strong" if any(h in low for h in STRONG_HINTS) else "cheap"


@router.post("/{provider_id}/models", status_code=201)
async def add_model(provider_id: uuid.UUID, body: CustomModelIn, db: DB, user: CurrentUser) -> dict[str, str]:
    provider = await _owned(db, user.id, provider_id)
    name = body.model_name.strip()
    exists = await db.scalar(
        select(AIModel).where(AIModel.provider_id == provider.id, AIModel.model_name == name)
    )
    if exists:
        raise ApiError(409, "model_exists", "Model ini sudah ada.")
    db.add(
        AIModel(
            provider_id=provider.id,
            model_name=name,
            display_name=body.display_name.strip() or name,
            tier=body.tier,
            cost_in=body.cost_in,
            cost_out=body.cost_out,
            context_window=body.context_window,
        )
    )
    await db.commit()
    return {"id": f"{provider.name}/{name}"}


@router.delete("/{provider_id}/models/{model_name:path}", status_code=204)
async def delete_model(provider_id: uuid.UUID, model_name: str, db: DB, user: CurrentUser) -> None:
    provider = await _owned(db, user.id, provider_id)
    model = await db.scalar(
        select(AIModel).where(AIModel.provider_id == provider.id, AIModel.model_name == model_name)
    )
    if model is None:
        raise ApiError(404, "not_found", "model not found")
    await db.delete(model)
    await db.commit()


@router.post("/{provider_id}/models/sync", response_model=ModelSyncOut)
async def sync_models(
    provider_id: uuid.UUID, db: DB, user: CurrentUser, cipher: Cipher, request: Request
) -> ModelSyncOut:
    """Reads GET {base_url}/models (OpenAI format) from gateways like 9Router.
    A plain metadata read: no completion is run, so it is fine inside the request."""
    provider = await _owned(db, user.id, provider_id)
    spec = PROVIDERS[provider.name]
    base = (provider.base_url or spec.default_base_url or "").rstrip("/")
    if not base:
        raise ApiError(400, "no_base_url", "Isi Base URL provider dulu.")
    key = await db.scalar(
        select(ProviderKey)
        .where(ProviderKey.provider_id == provider.id, ProviderKey.status != KeyStatus.disabled)
        .order_by(ProviderKey.priority)
    )
    secret = cipher.decrypt(key.api_key_encrypted) if key else NO_KEY
    headers = {"Authorization": f"Bearer {secret}"} if secret != NO_KEY else {}
    transport = getattr(request.app.state, "http_transport", None)
    try:
        async with httpx.AsyncClient(timeout=15, transport=transport) as client:
            resp = await client.get(f"{base}/models", headers=headers)
            resp.raise_for_status()
            names = [str(m["id"]) for m in resp.json().get("data", []) if m.get("id")]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ApiError(
            502, "sync_failed", f"Gagal membaca daftar model dari {base}: {type(exc).__name__}"
        ) from exc
    existing = set(
        (await db.scalars(select(AIModel.model_name).where(AIModel.provider_id == provider.id))).all()
    )
    added = [n for n in dict.fromkeys(names) if n not in existing][:300]
    for name in added:
        db.add(AIModel(provider_id=provider.id, model_name=name, display_name=name, tier=guess_tier(name)))
    audit.record(db, user.id, "user", "provider.sync_models", str(provider.id), added=len(added))
    await db.commit()
    return ModelSyncOut(added=added, total=len(existing) + len(added))
