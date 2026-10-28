from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.core.deps import DB, CurrentUser
from app.db.base import utcnow
from app.models import Provider, ProviderKey, UsageLog

router = APIRouter(prefix="/usage", tags=["usage"])


def _totals(row: Sequence[Any]) -> dict[str, float | int]:
    tin, tout, saved = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
    cost, requests, hits = float(row[3] or 0), int(row[4] or 0), int(row[5] or 0)
    spent = tin + tout
    return {
        "tokens_in": tin,
        "tokens_out": tout,
        "tokens_saved": saved,
        "cost": round(cost, 6),
        "requests": requests,
        "cache_hits": hits,
        "cache_hit_rate": round(hits / requests, 4) if requests else 0.0,
        "saving_pct": round(saved / (spent + saved) * 100, 2) if spent + saved else 0.0,
    }


def _metrics() -> tuple[Any, ...]:
    return (
        func.sum(UsageLog.tokens_in),
        func.sum(UsageLog.tokens_out),
        func.sum(UsageLog.tokens_saved),
        func.sum(UsageLog.cost),
        func.count(UsageLog.id),
        func.sum(case((UsageLog.cached.is_(True), 1), else_=0)),
    )


@router.get("/summary")
async def usage_summary(db: DB, user: CurrentUser, days: int = Query(30, ge=1, le=365)) -> dict[str, object]:
    since = utcnow() - timedelta(days=days)
    scope = (UsageLog.user_id == user.id, UsageLog.created_at >= since)

    total = (await db.execute(select(*_metrics()).where(*scope))).one()
    day_col = func.date(UsageLog.created_at)  # works on Postgres and SQLite
    per_day = (
        await db.execute(select(day_col, *_metrics()).where(*scope).group_by(day_col).order_by(day_col))
    ).all()
    per_provider = (
        await db.execute(
            select(Provider.name, *_metrics())
            .join(Provider, Provider.id == UsageLog.provider_id, isouter=True)
            .where(*scope)
            .group_by(Provider.name)
        )
    ).all()
    per_key = (
        await db.execute(
            select(ProviderKey.id, ProviderKey.label, ProviderKey.key_hint, Provider.name, *_metrics())
            .join(ProviderKey, ProviderKey.id == UsageLog.provider_key_id)
            .join(Provider, Provider.id == ProviderKey.provider_id)
            .where(*scope)
            .group_by(ProviderKey.id, ProviderKey.label, ProviderKey.key_hint, Provider.name)
        )
    ).all()
    return {
        "days": days,
        "total": _totals(total),
        "per_day": [{"day": str(r[0]), **_totals(r[1:])} for r in per_day],
        "per_provider": [{"provider": r[0] or "cache", **_totals(r[1:])} for r in per_provider],
        "per_key": [
            {"key_id": str(r[0]), "label": r[1], "key_hint": r[2], "provider": r[3], **_totals(r[4:])}
            for r in per_key
        ],
    }
