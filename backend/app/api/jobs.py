import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update

from app.core.deps import DB, AppSettings, CurrentUser, Queue, Redis
from app.core.errors import ApiError, not_found
from app.db.base import utcnow
from app.db.session import get_session_factory
from app.models import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES, Job, JobStatus
from app.schemas import JobCreated, JobOut, Page
from app.services.events import JobEvents

router = APIRouter(prefix="/jobs", tags=["jobs"])
KEEPALIVE_MS = 15_000


async def owned_job(db: DB, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = await db.get(Job, job_id)
    if job is None or job.user_id != user_id:
        raise not_found("job")
    return job


@router.get("", response_model=Page[JobOut])
async def list_jobs(
    db: DB,
    user: CurrentUser,
    status: str | None = None,
    chat_id: uuid.UUID | None = None,
    active: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[JobOut]:
    base = select(Job).where(Job.user_id == user.id)
    if status:
        base = base.where(Job.status == status)
    if active:
        base = base.where(Job.status.in_(ACTIVE_JOB_STATUSES))
    if chat_id:
        base = base.where(Job.chat_id == chat_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await db.scalars(base.order_by(Job.created_at.desc()).limit(limit).offset(offset))).all()
    return Page(items=[JobOut.model_validate(j) for j in rows], total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: DB, user: CurrentUser) -> Job:
    return await owned_job(db, user.id, job_id)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: uuid.UUID, db: DB, user: CurrentUser, redis: Redis, settings: AppSettings
) -> Job:
    job = await owned_job(db, user.id, job_id)
    if job.status in TERMINAL_JOB_STATUSES:
        return job
    was_running = job.status == JobStatus.running
    await db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status.in_(ACTIVE_JOB_STATUSES))
        .values(status=JobStatus.cancelled, finished_at=utcnow())
    )
    await db.commit()
    await db.refresh(job)
    events = JobEvents(redis, settings.stream_ttl_seconds)
    await events.request_cancel(str(job.id))
    if not was_running:
        await events.publish(str(job.id), "done", {"status": JobStatus.cancelled, "message_id": None})
    return job


@router.post("/{job_id}/retry", response_model=JobCreated, status_code=202)
async def retry_job(job_id: uuid.UUID, db: DB, user: CurrentUser, queue: Queue) -> JobCreated:
    """Re-run a failed/cancelled job for the same user message (no duplicate prompt)."""
    job = await owned_job(db, user.id, job_id)
    if job.status not in (JobStatus.failed, JobStatus.cancelled):
        raise ApiError(409, "not_retryable", "Hanya job gagal/dibatalkan yang bisa diulang.")
    if job.result_message_id is not None:
        raise ApiError(409, "not_retryable", "Job ini sudah punya jawaban.")
    clone = Job(
        chat_id=job.chat_id,
        user_id=user.id,
        user_message_id=job.user_message_id,
        model_requested=job.model_requested,
    )
    db.add(clone)
    await db.commit()
    await queue.enqueue_job("run_job", str(clone.id), _job_id=str(clone.id))
    return JobCreated(job_id=clone.id, message_id=job.user_message_id)


def sse(event_id: str | None, kind: str, data: dict[str, Any]) -> str:
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {kind}\ndata: {json.dumps(data)}\n\n"


def _final(job: Job) -> list[str]:
    kind = "error" if job.status == JobStatus.failed else "done"
    return [
        sse(None, "snapshot", {"text": job.partial_output, "status": job.status}),
        sse(
            None,
            kind,
            {
                "status": job.status,
                "message_id": str(job.result_message_id) if job.result_message_id else None,
                "model_used": job.model_used,
                "tokens_saved": job.tokens_saved,
                "error": job.error,
            },
        ),
    ]


async def job_event_stream(
    events: JobEvents,
    load_job: Callable[[], Awaitable[Job | None]],
    job_id: str,
    last_event_id: str | None,
    block_ms: int = KEEPALIVE_MS,
) -> AsyncIterator[str]:
    """Replays the job's Redis stream from the start (or from Last-Event-ID) and then
    follows it live. Only reads — the worker is the one producing output."""
    after = last_event_id or "0"
    if not await events.has_stream(job_id):
        job = await load_job()
        if job is None:
            return
        if job.status in TERMINAL_JOB_STATUSES:
            for chunk in _final(job):
                yield chunk
            return
        if last_event_id:
            # Stream expired while the client was away: resend what is persisted.
            yield sse(None, "snapshot", {"text": job.partial_output, "status": job.status})
    while True:
        batch = await events.read(job_id, after, block_ms)
        if not batch:
            job = await load_job()
            if job is None:
                return
            if job.status in TERMINAL_JOB_STATUSES and not await events.has_stream(job_id):
                for chunk in _final(job):
                    yield chunk
                return
            yield ": keepalive\n\n"
            continue
        for event_id, kind, data in batch:
            after = event_id
            yield sse(event_id, kind, data)
            if kind in ("done", "error"):
                return


@router.get("/{job_id}/stream")
async def stream_job(
    job_id: uuid.UUID,
    request: Request,
    db: DB,
    user: CurrentUser,
    redis: Redis,
    settings: AppSettings,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    await owned_job(db, user.id, job_id)
    # EventSource can't send headers on first connect; allow ?last_event_id= too.
    resume_from = last_event_id or request.query_params.get("last_event_id")
    factory = get_session_factory()

    async def load() -> Job | None:
        async with factory() as session:
            return await session.get(Job, job_id)

    events = JobEvents(redis, settings.stream_ttl_seconds)
    return StreamingResponse(
        job_event_stream(events, load, str(job_id), resume_from),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
