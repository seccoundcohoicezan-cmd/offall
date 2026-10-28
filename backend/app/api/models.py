import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import DB, AppSettings, CurrentUser
from app.core.errors import not_found
from app.db.base import utcnow
from app.models import AIModel, Provider, ProviderKey
from app.schemas import ModelOut, ModelPatch
from app.services.catalog import PROVIDERS, model_ref
from app.services.key_pool import RECOVERABLE, is_usable

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelOut])
async def list_models(
    db: DB, user: CurrentUser, settings: AppSettings, include_all: bool = False
) -> list[ModelOut]:
    """Models whose provider has at least one active key (all models with include_all=true)."""
    now = utcnow()
    keys = (
        await db.scalars(
            select(ProviderKey)
            .join(Provider, Provider.id == ProviderKey.provider_id)
            .where(Provider.user_id == user.id, ProviderKey.status.in_(RECOVERABLE))
        )
    ).all()
    active_providers = {k.provider_id for k in keys if is_usable(k, now)}
    rows = (
        await db.execute(
            select(AIModel, Provider)
            .join(Provider, Provider.id == AIModel.provider_id)
            .where(Provider.user_id == user.id)
            .order_by(Provider.created_at, AIModel.tier.desc(), AIModel.display_name)
        )
    ).all()
    favorites = set(user.settings.get("favorite_models") or [])
    out = []
    for model, provider in rows:
        if provider.name == "mock" and not settings.enable_mock_provider:
            continue
        if not include_all and (provider.id not in active_providers or not model.is_enabled):
            continue
        ref = model_ref(provider.name, model.model_name)
        out.append(
            ModelOut(
                id=ref,
                provider=provider.name,
                provider_display=PROVIDERS[provider.name].display
                if provider.name in PROVIDERS
                else provider.name,
                model_name=model.model_name,
                display_name=model.display_name,
                tier=model.tier,
                is_enabled=model.is_enabled,
                cost_in=model.cost_in,
                cost_out=model.cost_out,
                context_window=model.context_window,
                favorite=ref in favorites,
            )
        )
    return out


@router.patch("/{provider_id}/{model_name:path}", response_model=dict[str, bool])
async def toggle_model(
    provider_id: uuid.UUID, model_name: str, body: ModelPatch, db: DB, user: CurrentUser
) -> dict[str, bool]:
    provider = await db.get(Provider, provider_id)
    if provider is None or provider.user_id != user.id:
        raise not_found("provider")
    model = await db.scalar(
        select(AIModel).where(AIModel.provider_id == provider.id, AIModel.model_name == model_name)
    )
    if model is None:
        raise not_found("model")
    model.is_enabled = body.is_enabled
    await db.commit()
    return {"is_enabled": model.is_enabled}
