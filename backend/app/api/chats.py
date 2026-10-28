import uuid
from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import DB, AppSettings, CurrentUser, Queue
from app.core.errors import ApiError, not_found
from app.db.base import utcnow
from app.models import ACTIVE_JOB_STATUSES, Agent, Chat, Job, Message
from app.schemas import ChatIn, ChatOut, ChatPatch, JobCreated, MessageIn, MessageOut, Page

router = APIRouter(prefix="/chats", tags=["chats"])


async def owned_chat(db: DB, user_id: uuid.UUID, chat_id: uuid.UUID) -> Chat:
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.user_id != user_id:
        raise not_found("chat")
    return chat


async def _check_agent(db: DB, user_id: uuid.UUID, agent_id: uuid.UUID | None) -> None:
    if agent_id is None:
        return
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.user_id != user_id:
        raise not_found("agent")


@router.get("", response_model=Page[ChatOut])
async def list_chats(
    db: DB, user: CurrentUser, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> Page[ChatOut]:
    base = select(Chat).where(Chat.user_id == user.id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await db.scalars(
            base.order_by(func.coalesce(Chat.updated_at, Chat.created_at).desc()).limit(limit).offset(offset)
        )
    ).all()
    return Page(items=[ChatOut.model_validate(c) for c in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ChatOut, status_code=201)
async def create_chat(body: ChatIn, db: DB, user: CurrentUser, settings: AppSettings) -> Chat:
    count = await db.scalar(select(func.count()).select_from(Chat).where(Chat.user_id == user.id))
    if (count or 0) >= settings.max_chats_per_user:
        raise ApiError(400, "too_many_chats", "Batas jumlah chat tercapai. Hapus chat lama dulu.")
    await _check_agent(db, user.id, body.agent_id)
    chat = Chat(
        user_id=user.id,
        title=body.title,
        default_model=body.default_model,
        agent_id=body.agent_id,
        mode=body.mode,
        updated_at=utcnow(),
    )
    db.add(chat)
    await db.commit()
    return chat


@router.get("/{chat_id}", response_model=ChatOut)
async def get_chat(chat_id: uuid.UUID, db: DB, user: CurrentUser) -> Chat:
    return await owned_chat(db, user.id, chat_id)


@router.patch("/{chat_id}", response_model=ChatOut)
async def patch_chat(chat_id: uuid.UUID, body: ChatPatch, db: DB, user: CurrentUser) -> Chat:
    chat = await owned_chat(db, user.id, chat_id)
    if body.title is not None:
        chat.title = body.title
    if body.default_model is not None:
        chat.default_model = body.default_model
    if body.mode is not None:
        chat.mode = body.mode
    if body.clear_agent:
        chat.agent_id = None
    elif body.agent_id is not None:
        await _check_agent(db, user.id, body.agent_id)
        chat.agent_id = body.agent_id
    await db.commit()
    return chat


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    chat = await owned_chat(db, user.id, chat_id)
    await db.delete(chat)
    await db.commit()


@router.get("/{chat_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    chat_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[MessageOut]:
    await owned_chat(db, user.id, chat_id)
    base = select(Message).where(Message.chat_id == chat_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    # newest page first, returned in chronological order
    rows = (await db.scalars(base.order_by(Message.created_at.desc()).limit(limit).offset(offset))).all()
    items = [MessageOut.model_validate(m) for m in reversed(rows)]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/{chat_id}/messages", response_model=JobCreated, status_code=202)
async def send_message(
    chat_id: uuid.UUID, body: MessageIn, db: DB, user: CurrentUser, queue: Queue, settings: AppSettings
) -> JobCreated:
    """Stores the prompt, creates a job and returns at once; the worker does the AI call."""
    chat = await owned_chat(db, user.id, chat_id)
    if len(body.content) > settings.max_message_chars:
        raise ApiError(422, "message_too_long", f"Pesan maksimal {settings.max_message_chars} karakter.")
    if body.idempotency_key:
        existing = await db.scalar(
            select(Job).where(Job.user_id == user.id, Job.idempotency_key == body.idempotency_key)
        )
        if existing is not None:
            return JobCreated(job_id=existing.id, message_id=existing.user_message_id)
    running = await db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.user_id == user.id, Job.status.in_(ACTIVE_JOB_STATUSES))
        .where(Job.created_at > utcnow() - timedelta(days=1))
    )
    if (running or 0) >= settings.max_parallel_jobs_per_user:
        raise ApiError(429, "too_many_jobs", "Masih ada job berjalan. Tunggu atau batalkan dulu.")

    now = utcnow()
    message = Message(chat_id=chat.id, role="user", content=body.content, created_at=now)
    db.add(message)
    await db.flush()
    job = Job(
        chat_id=chat.id,
        user_id=user.id,
        user_message_id=message.id,
        model_requested=body.model,
        idempotency_key=body.idempotency_key,
    )
    db.add(job)
    chat.default_model = body.model
    chat.updated_at = now
    if chat.title == "Chat baru":
        chat.title = body.content.strip().splitlines()[0][:60] or chat.title
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ApiError(409, "duplicate_request", "Permintaan yang sama sedang diproses.") from exc
    await queue.enqueue_job("run_job", str(job.id), _job_id=str(job.id))
    return JobCreated(job_id=job.id, message_id=message.id)
