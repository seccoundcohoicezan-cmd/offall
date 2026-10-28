"""ARQ worker: runs chat jobs outside the HTTP request and resumes waiting jobs."""

import logging
import uuid
from datetime import timedelta
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import update

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import utcnow
from app.db.session import get_session_factory
from app.models import Job, JobStatus
from app.services.jobs import JobRunner, due_waiting_jobs
from app.services.key_pool import recover_keys
from app.services.runtime import build_runner

log = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging()
    settings = get_settings()
    sessions = get_session_factory()
    ctx["sessions"] = sessions
    redis = ctx["redis"]

    async def enqueue(name: str, arg: str) -> None:
        await redis.enqueue_job(name, arg, _job_id=f"{name}:{arg}")

    ctx["runner"] = build_runner(sessions, redis, settings, enqueue=enqueue)


async def run_job(ctx: dict[str, Any], job_id: str) -> str:
    runner: JobRunner = ctx["runner"]
    return await runner.run(uuid.UUID(job_id))


async def learn_from_job(ctx: dict[str, Any], job_id: str) -> int:
    runner: JobRunner = ctx["runner"]
    return await runner.learn(uuid.UUID(job_id))


async def rebuild_profile(ctx: dict[str, Any], user_id: str) -> str | None:
    runner: JobRunner = ctx["runner"]
    return await runner.rebuild_profile(uuid.UUID(user_id))


async def resume_waiting(ctx: dict[str, Any]) -> int:
    sessions = ctx["sessions"]
    await recover_keys(sessions)
    await _requeue_stale_running(sessions)
    ids = await due_waiting_jobs(sessions)
    for job_id in ids:
        await ctx["redis"].enqueue_job("run_job", str(job_id), _job_id=f"{job_id}:{utcnow().timestamp():.0f}")
    if ids:
        log.info("re-enqueued waiting jobs", extra={"event": f"resume:{len(ids)}"})
    return len(ids)


async def _requeue_stale_running(sessions: Any) -> None:
    """A worker that died mid-job leaves it `running`; hand it back to the scheduler."""
    limit = utcnow() - timedelta(seconds=get_settings().job_timeout_seconds * 2)
    async with sessions() as session:
        await session.execute(
            update(Job)
            .where(Job.status == JobStatus.running, Job.started_at < limit)
            .values(status=JobStatus.waiting_quota, retry_at=None, error="worker restarted")
        )
        await session.commit()


class WorkerSettings:
    functions = [run_job, learn_from_job, rebuild_profile]
    cron_jobs = [cron(resume_waiting, second={0, 30}, run_at_startup=True)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = get_settings().job_timeout_seconds
    max_jobs = 20
    keep_result = 60
