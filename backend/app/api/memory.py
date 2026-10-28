import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser, Queue
from app.core.errors import ApiError, not_found
from app.db.base import utcnow
from app.models import AuditLog, Memory, MemoryStatus
from app.schemas import AuditOut, HistoryHitOut, MemoryIn, MemoryOut, MemoryPatch, Page, ProfileOut
from app.services import audit, memory
from app.services.semantic_cache import embed

router = APIRouter(tags=["memory"])


async def _owned(db: DB, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
    item = await db.get(Memory, memory_id)
    if item is None or item.user_id != user_id:
        raise not_found("memory")
    return item


@router.get("/memories", response_model=Page[MemoryOut])
async def list_memories(
    db: DB,
    user: CurrentUser,
    status: str | None = None,
    q: str = "",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[MemoryOut]:
    base = select(Memory).where(Memory.user_id == user.id)
    base = (
        base.where(Memory.status == status) if status else base.where(Memory.status != MemoryStatus.rejected)
    )
    if q.strip():
        base = base.where(func.lower(Memory.content).contains(q.strip().lower()))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await db.scalars(
            base.order_by(Memory.pinned.desc(), Memory.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return Page(items=[MemoryOut.model_validate(m) for m in rows], total=total, limit=limit, offset=offset)


@router.post("/memories", response_model=MemoryOut, status_code=201)
async def create_memory(body: MemoryIn, db: DB, user: CurrentUser, queue: Queue) -> Memory:
    count = await db.scalar(select(func.count()).select_from(Memory).where(Memory.user_id == user.id))
    if (count or 0) >= memory.MAX_MEMORIES_PER_USER:
        raise ApiError(400, "too_many_memories", "Batas jumlah memori tercapai. Hapus yang lama dulu.")
    item, _ = await memory.remember(db, user.id, body.content.strip(), body.kind, "manual")
    item.pinned = body.pinned or item.pinned
    item.status = MemoryStatus.active
    await db.commit()
    # Refresh the user model in the background (worker), never inside this request.
    await queue.enqueue_job("rebuild_profile", str(user.id), _job_id=f"rebuild_profile:{user.id}")
    return item


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def patch_memory(memory_id: uuid.UUID, body: MemoryPatch, db: DB, user: CurrentUser) -> Memory:
    item = await _owned(db, user.id, memory_id)
    changes = body.model_dump(exclude_none=True)
    if "content" in changes:
        item.content = changes["content"].strip()
        item.embedding = embed(item.content)
    for field in ("kind", "pinned", "status"):
        if field in changes:
            setattr(item, field, changes[field])
    item.updated_at = utcnow()
    action = {"active": "memory.approve", "rejected": "memory.reject"}.get(
        changes.get("status", ""), "memory.edit"
    )
    audit.record(db, user.id, "user", action, str(item.id), fields=sorted(changes))
    await db.commit()
    return item


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    item = await _owned(db, user.id, memory_id)
    audit.record(db, user.id, "user", "memory.delete", str(item.id), content=item.content[:120])
    await db.delete(item)
    await db.commit()


@router.get("/memories/profile", response_model=ProfileOut)
async def get_profile(db: DB, user: CurrentUser) -> ProfileOut:
    counts = dict(
        (
            await db.execute(
                select(Memory.status, func.count()).where(Memory.user_id == user.id).group_by(Memory.status)
            )
        ).all()
    )
    s = user.settings or {}
    return ProfileOut(
        summary=str(s.get("memory_profile") or ""),
        updated_at=s.get("memory_profile_at"),
        active=int(counts.get(MemoryStatus.active, 0)),
        pending=int(counts.get(MemoryStatus.pending, 0)),
    )


@router.post("/memories/profile/rebuild", status_code=202)
async def rebuild_profile(user: CurrentUser, queue: Queue) -> dict[str, str]:
    """The model call happens in the worker, never inside the HTTP request."""
    await queue.enqueue_job("rebuild_profile", str(user.id), _job_id=f"rebuild_profile:{user.id}")
    return {"status": "queued"}


@router.get("/search/messages", response_model=list[HistoryHitOut])
async def search_messages(
    db: DB,
    user: CurrentUser,
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(30, ge=1, le=100),
) -> list[HistoryHitOut]:
    hits = await memory.search_history(db, user.id, q, limit=limit)
    return [HistoryHitOut(**h.__dict__) for h in hits]


@router.get("/audit", response_model=Page[AuditOut])
async def list_audit(
    db: DB,
    user: CurrentUser,
    all_users: bool = False,
    action: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[AuditOut]:
    base = select(AuditLog)
    if not (all_users and user.role == "admin"):
        base = base.where(AuditLog.user_id == user.id)
    if action:
        base = base.where(AuditLog.action.startswith(action))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(base.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[AuditOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)
