"""Runs one chat job end to end. Used by the ARQ worker and directly by tests."""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.core.config import Settings
from app.db.base import utcnow
from app.db.session import SessionFactory
from app.models import (
    TERMINAL_JOB_STATUSES,
    Agent,
    AIModel,
    Chat,
    Job,
    JobStatus,
    Message,
    Provider,
    ProviderKey,
    UsageLog,
    User,
)
from app.services import router, semantic_cache, summarizer, token_saver
from app.services.events import JobEvents
from app.services.key_pool import RECOVERABLE, KeyPool, NoKeyAvailable
from app.services.llm import LLMError
from app.services.notify import Event, Notifier

log = logging.getLogger(__name__)
FLUSH_SECONDS = 0.5
FLUSH_CHARS = 400
WAITING_RECHECK = timedelta(minutes=5)


@dataclass
class _Plan:
    candidate: router.Candidate
    provider: Provider
    model: AIModel


@dataclass
class _Context:
    job: Job
    user: User
    chat: Chat
    system_prompt: str
    history: list[dict[str, Any]]
    mode: str
    plans: list[_Plan] = field(default_factory=list)


class JobRunner:
    def __init__(
        self,
        sessions: SessionFactory,
        pool: KeyPool,
        events: JobEvents,
        notifier: Notifier,
        settings: Settings,
    ) -> None:
        self.sessions = sessions
        self.pool = pool
        self.events = events
        self.notifier = notifier
        self.settings = settings

    async def run(self, job_id: uuid.UUID) -> str:
        if not await self._claim(job_id):
            return "skipped"
        jid = str(job_id)
        await self.events.publish(jid, "status", {"status": JobStatus.running})
        try:
            ctx = await self._load(job_id)
            return await self._execute(ctx)
        except Exception as exc:
            log.exception("job crashed", extra={"job_id": jid})
            await self._fail(job_id, f"internal error: {type(exc).__name__}")
            return JobStatus.failed

    async def _claim(self, job_id: uuid.UUID) -> bool:
        async with self.sessions() as session:
            result = await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .where(Job.status.in_((JobStatus.queued, JobStatus.waiting_quota)))
                .values(
                    status=JobStatus.running,
                    started_at=utcnow(),
                    attempts=Job.attempts + 1,
                    retry_at=None,
                )
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0))

    async def _load(self, job_id: uuid.UUID) -> _Context:
        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            user = await session.get(User, job.user_id)
            chat = await session.get(Chat, job.chat_id)
            prompt_msg = await session.get(Message, job.user_message_id)
            assert user is not None and chat is not None and prompt_msg is not None
            agent = await session.get(Agent, chat.agent_id) if chat.agent_id else None
            rows = (
                await session.scalars(
                    select(Message)
                    .where(Message.chat_id == chat.id, Message.created_at <= prompt_msg.created_at)
                    .where(Message.role.in_(("user", "assistant")))
                    .order_by(Message.created_at)
                )
            ).all()
            history = [{"role": m.role, "content": m.content} for m in rows]
            parts = [str(user.settings.get("system_prompt") or "").strip()]
            if agent is not None and agent.is_enabled:
                parts.append(f"Kamu adalah agent bernama {agent.name}.\n{agent.instructions}".strip())
            system_prompt = "\n\n".join(p for p in parts if p)
            mode = (
                chat.mode
                if chat.mode in token_saver.MODES
                else str(user.settings.get("save_mode") or "normal")
            )
            ctx = _Context(job, user, chat, system_prompt, history, mode)
            ctx.plans = await self._plans(session, ctx)
            return ctx

    async def _plans(self, session: Any, ctx: _Context) -> list[_Plan]:
        rows = (
            await session.execute(
                select(AIModel, Provider)
                .join(Provider, Provider.id == AIModel.provider_id)
                .where(Provider.user_id == ctx.user.id, AIModel.is_enabled.is_(True))
            )
        ).all()
        with_keys = set(
            (
                await session.scalars(
                    select(ProviderKey.provider_id)
                    .join(Provider, Provider.id == ProviderKey.provider_id)
                    .where(Provider.user_id == ctx.user.id)
                    .where(ProviderKey.status.in_(RECOVERABLE))
                )
            ).all()
        )
        by_ref: dict[str, _Plan] = {}
        for model, provider in rows:
            if provider.id not in with_keys:
                continue
            if provider.name == "mock" and not self.settings.enable_mock_provider:
                continue
            cand = router.Candidate(provider.name, model.model_name, model.tier)
            by_ref[cand.ref] = _Plan(cand, provider, model)
        prompt = str(ctx.history[-1]["content"]) if ctx.history else ""
        ordered = router.plan(
            ctx.job.model_requested,
            prompt,
            [p.candidate for p in by_ref.values()],
            list(ctx.user.settings.get("fallback_order") or []),
            bool(ctx.user.settings.get("allow_fallback", True)),
        )
        return [by_ref[c.ref] for c in ordered]

    async def _execute(self, ctx: _Context) -> str:
        jid = str(ctx.job.id)
        if not ctx.plans:
            return await self._fail(ctx.job.id, "Tidak ada model dengan key aktif untuk permintaan ini.")

        prompt = str(ctx.history[-1]["content"])
        scope = semantic_cache.scope_for(ctx.job.model_requested, ctx.system_prompt)
        use_cache = ctx.mode != "off" and len(ctx.history) == 1 and not ctx.job.partial_output
        if use_cache and (hit := await self._cache_hit(ctx, scope, prompt)) is not None:
            return hit

        summary = await self._maybe_summarize(ctx)
        saved = token_saver.apply(ctx.history, ctx.mode, ctx.system_prompt, summary)
        messages = saved.messages
        max_tokens = int(ctx.user.settings.get("max_tokens") or 1024)

        output = ctx.job.partial_output or ""
        flushed_at = time.monotonic()
        flushed_len = len(output)

        async def on_text(text: str) -> None:
            nonlocal output, flushed_at, flushed_len
            output += text
            await self.events.publish(jid, "delta", {"text": text})
            if time.monotonic() - flushed_at > FLUSH_SECONDS or len(output) - flushed_len > FLUSH_CHARS:
                await self._save_partial(ctx.job.id, output)
                flushed_at, flushed_len = time.monotonic(), len(output)

        async def should_stop() -> bool:
            return await self.events.is_cancelled(jid)

        retry_times: list[datetime | None] = []
        last_error = ""
        for plan in ctx.plans:
            try:
                result = await self.pool.stream(
                    plan.provider,
                    plan.candidate.model_name,
                    messages,
                    max_tokens,
                    on_text,
                    prefix=output,
                    should_stop=should_stop,
                )
            except NoKeyAvailable as exc:
                retry_times.append(exc.retry_at)
                last_error = f"Semua key {plan.provider.name} sedang limit/habis."
                await self.events.publish(jid, "status", {"status": "rotating", "detail": last_error})
                continue
            except LLMError as exc:
                last_error = f"{plan.candidate.ref}: {exc}"[:500]
                continue
            await self._save_partial(ctx.job.id, output)
            cancelled = await should_stop()
            return await self._finish(
                ctx, plan, output, result.key_id, result.usage, saved.tokens_saved, cancelled
            )

        await self._save_partial(ctx.job.id, output)
        known = [t for t in retry_times if t is not None]
        if known:
            return await self._wait_for_quota(ctx.job.id, min(known), last_error)
        return await self._fail(ctx.job.id, last_error or "Semua model gagal.")

    async def _cache_hit(self, ctx: _Context, scope: str, prompt: str) -> str | None:
        async with self.sessions() as session:
            entry = await semantic_cache.lookup(
                session, ctx.user.id, scope, prompt, self.settings.cache_similarity_threshold
            )
            if entry is None:
                return None
            entry.hit_count += 1
            response, model = entry.response, entry.model
            await session.commit()
        await self.events.publish(str(ctx.job.id), "delta", {"text": response})
        saved = token_saver.count_tokens(ctx.history) + token_saver.estimate_tokens(response)
        return await self._complete(
            ctx, response, model, None, None, 0, 0, saved, 0.0, cached=True, cancelled=False
        )

    async def _maybe_summarize(self, ctx: _Context) -> str | None:
        run, upto = summarizer.needs_summary(len(ctx.history), ctx.mode, ctx.chat.summary_upto)
        if not run:
            return ctx.chat.summary if ctx.chat.summary_upto else None
        turns = ctx.history[ctx.chat.summary_upto : upto]
        request = summarizer.build_request(ctx.chat.summary, turns)
        cheap = sorted(ctx.plans, key=lambda p: (p.candidate.tier != "cheap", p.model.cost_out))
        for plan in cheap[:2]:
            chunks: list[str] = []

            async def collect(text: str, sink: list[str] = chunks) -> None:
                sink.append(text)

            try:
                await self.pool.stream(plan.provider, plan.candidate.model_name, request, 400, collect)
            except (NoKeyAvailable, LLMError):
                continue
            summary = "".join(chunks).strip()
            async with self.sessions() as session:
                await session.execute(
                    update(Chat).where(Chat.id == ctx.chat.id).values(summary=summary, summary_upto=upto)
                )
                await session.commit()
            return summary
        return ctx.chat.summary

    async def _save_partial(self, job_id: uuid.UUID, output: str) -> None:
        async with self.sessions() as session:
            await session.execute(update(Job).where(Job.id == job_id).values(partial_output=output))
            await session.commit()

    async def _finish(
        self,
        ctx: _Context,
        plan: _Plan,
        output: str,
        key_id: uuid.UUID,
        usage: Any,
        tokens_saved: int,
        cancelled: bool,
    ) -> str:
        cost = (usage.tokens_in * plan.model.cost_in + usage.tokens_out * plan.model.cost_out) / 1e6
        status = await self._complete(
            ctx,
            output,
            plan.candidate.ref,
            plan.provider.id,
            key_id,
            usage.tokens_in,
            usage.tokens_out,
            tokens_saved,
            cost,
            cached=False,
            cancelled=cancelled,
        )
        if status == JobStatus.done and ctx.mode != "off" and len(ctx.history) == 1 and output:
            scope = semantic_cache.scope_for(ctx.job.model_requested, ctx.system_prompt)
            async with self.sessions() as session:
                session.add(
                    semantic_cache.make_entry(
                        ctx.user.id, scope, str(ctx.history[-1]["content"]), output, plan.candidate.ref
                    )
                )
                await session.commit()
        return status

    async def _complete(
        self,
        ctx: _Context,
        output: str,
        model_used: str,
        provider_id: uuid.UUID | None,
        key_id: uuid.UUID | None,
        tokens_in: int,
        tokens_out: int,
        tokens_saved: int,
        cost: float,
        cached: bool,
        cancelled: bool,
    ) -> str:
        """Idempotent: a job that already has a result message is left untouched."""
        final_status = JobStatus.cancelled if cancelled else JobStatus.done
        now = utcnow()
        async with self.sessions() as session:
            job = await session.get(Job, ctx.job.id, with_for_update=True)
            assert job is not None
            if job.result_message_id is not None:
                return str(job.status)
            message_id = None
            if output:
                msg = Message(
                    chat_id=ctx.chat.id,
                    role="assistant",
                    content=output,
                    model_used=model_used,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    tokens_saved=tokens_saved,
                    cached=cached,
                    created_at=now,
                )
                session.add(msg)
                await session.flush()
                message_id = msg.id
            session.add(
                UsageLog(
                    user_id=ctx.user.id,
                    job_id=job.id,
                    provider_id=provider_id,
                    provider_key_id=key_id,
                    model=model_used,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    tokens_saved=tokens_saved,
                    cost=cost,
                    cached=cached,
                )
            )
            job.result_message_id = message_id
            job.status = final_status
            job.model_used = model_used
            job.partial_output = output
            job.tokens_saved = tokens_saved
            job.finished_at = now
            job.error = None
            await session.execute(update(Chat).where(Chat.id == ctx.chat.id).values(updated_at=now))
            await session.commit()
        await self.events.publish(
            str(ctx.job.id),
            "done",
            {
                "status": final_status,
                "message_id": str(message_id) if message_id else None,
                "model_used": model_used,
                "tokens_saved": tokens_saved,
                "cached": cached,
            },
        )
        if not cancelled:
            await self.notifier.notify(
                ctx.user,
                Event("job_done", "Jawaban siap", f"{ctx.chat.title} ({model_used})", f"/chat/{ctx.chat.id}"),
            )
        log.info(
            "job finished", extra={"job_id": str(ctx.job.id), "model": model_used, "status": final_status}
        )
        return final_status

    async def _wait_for_quota(self, job_id: uuid.UUID, retry_at: datetime, reason: str) -> str:
        async with self.sessions() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == JobStatus.running)
                .values(status=JobStatus.waiting_quota, retry_at=retry_at, error=reason[:1000])
            )
            await session.commit()
        await self.events.publish(
            str(job_id),
            "status",
            {"status": JobStatus.waiting_quota, "retry_at": retry_at.isoformat(), "detail": reason},
        )
        return JobStatus.waiting_quota

    async def _fail(self, job_id: uuid.UUID, reason: str) -> str:
        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                return str(job.status) if job else JobStatus.failed
            job.status = JobStatus.failed
            job.error = reason[:1000]
            job.finished_at = utcnow()
            user = await session.get(User, job.user_id)
            await session.commit()
        await self.events.publish(str(job_id), "error", {"status": JobStatus.failed, "error": reason})
        if user is not None:
            await self.notifier.notify(user, Event("job_failed", "Job gagal", reason[:200], "/jobs"))
        return JobStatus.failed


async def due_waiting_jobs(sessions: SessionFactory, limit: int = 100) -> list[uuid.UUID]:
    """Waiting jobs whose earliest key recovery time passed. Bumps retry_at so the
    scheduler doesn't enqueue the same job every tick while it sits in the queue."""
    now = utcnow()
    async with sessions() as session:
        ids = list(
            (
                await session.scalars(
                    select(Job.id)
                    .where(Job.status == JobStatus.waiting_quota)
                    .where((Job.retry_at.is_(None)) | (Job.retry_at <= now))
                    .limit(limit)
                )
            ).all()
        )
        if ids:
            await session.execute(update(Job).where(Job.id.in_(ids)).values(retry_at=now + WAITING_RECHECK))
            await session.commit()
        return ids
