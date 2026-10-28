"""Runs one chat job end to end. Used by the ARQ worker and directly by tests."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
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
    Memory,
    MemoryStatus,
    Message,
    Provider,
    ProviderKey,
    UsageLog,
    User,
)
from app.services import audit, memory, router, semantic_cache, summarizer, token_saver
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
    memories_used: int = 0


class JobRunner:
    def __init__(
        self,
        sessions: SessionFactory,
        pool: KeyPool,
        events: JobEvents,
        notifier: Notifier,
        settings: Settings,
        external_memory: memory.ExternalStore | None = None,
        enqueue: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self.sessions = sessions
        self.pool = pool
        self.events = events
        self.notifier = notifier
        self.settings = settings
        self.external_memory = external_memory
        self.enqueue = enqueue

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
            prompt = history[-1]["content"] if history else ""
            memories_used = 0
            if memory.settings_of(user)["enabled"] and prompt:
                block, memories_used = await self._memory_context(session, user, chat.id, str(prompt))
                parts.append(block)
                await session.commit()
            system_prompt = "\n\n".join(p for p in parts if p)
            mode = (
                chat.mode
                if chat.mode in token_saver.MODES
                else str(user.settings.get("save_mode") or "normal")
            )
            ctx = _Context(job, user, chat, system_prompt, history, mode, memories_used=memories_used)
            ctx.plans = await self._plans(session, user, job.model_requested, str(prompt))
            return ctx

    async def _memory_context(
        self, session: Any, user: User, chat_id: uuid.UUID, prompt: str
    ) -> tuple[str, int]:
        mems = await memory.relevant(session, user.id, prompt)
        hits = (
            await memory.search_history(session, user.id, prompt, limit=5, exclude_chat_id=chat_id)
            if memory.wants_recall(prompt)
            else []
        )
        external = (
            await self.external_memory.search(user.id, prompt, memory.MAX_INJECTED)
            if self.external_memory
            else []
        )
        profile = str((user.settings or {}).get("memory_profile") or "")
        block = memory.context_block(profile, mems, external, hits)
        return block, len(mems) + len(external) + len(hits)

    async def _plans(self, session: Any, user: User, requested: str, prompt: str) -> list[_Plan]:
        rows = (
            await session.execute(
                select(AIModel, Provider)
                .join(Provider, Provider.id == AIModel.provider_id)
                .where(Provider.user_id == user.id, AIModel.is_enabled.is_(True))
            )
        ).all()
        with_keys = set(
            (
                await session.scalars(
                    select(ProviderKey.provider_id)
                    .join(Provider, Provider.id == ProviderKey.provider_id)
                    .where(Provider.user_id == user.id)
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
        ordered = router.plan(
            requested,
            prompt,
            [p.candidate for p in by_ref.values()],
            list(user.settings.get("fallback_order") or []),
            bool(user.settings.get("allow_fallback", True)),
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
        summary = await self._cheap_call(ctx.plans, request, 400)
        if summary is None:
            return ctx.chat.summary
        async with self.sessions() as session:
            await session.execute(
                update(Chat).where(Chat.id == ctx.chat.id).values(summary=summary, summary_upto=upto)
            )
            await session.commit()
        return summary

    async def _cheap_call(
        self, plans: list[_Plan], request: list[dict[str, Any]], max_tokens: int
    ) -> str | None:
        """One non-streamed call on the cheapest available model (summaries, memory)."""
        cheap = sorted(plans, key=lambda p: (p.candidate.tier != "cheap", p.model.cost_out))
        for plan in cheap[:2]:
            chunks: list[str] = []

            async def collect(text: str, sink: list[str] = chunks) -> None:
                sink.append(text)

            try:
                await self.pool.stream(plan.provider, plan.candidate.model_name, request, max_tokens, collect)
            except (NoKeyAvailable, LLMError):
                continue
            return "".join(chunks).strip()
        return None

    async def learn(self, job_id: uuid.UUID) -> int:
        """Experimental self-learning step, run as its own background task after an
        answer: extract durable facts about the user from that exchange."""
        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != JobStatus.done or job.result_message_id is None:
                return 0
            user = await session.get(User, job.user_id)
            prompt_msg = await session.get(Message, job.user_message_id)
            answer_msg = await session.get(Message, job.result_message_id)
            if user is None or prompt_msg is None or answer_msg is None:
                return 0
            prefs = memory.settings_of(user)
            if not (prefs["enabled"] and prefs["auto"]):
                return 0
            plans = await self._plans(session, user, "auto", prompt_msg.content)
        raw = await self._cheap_call(
            plans, memory.extraction_request(prompt_msg.content, answer_msg.content), 300
        )
        items = memory.parse_extraction(raw or "")
        if not items:
            return 0
        status = MemoryStatus.pending if prefs["review"] else MemoryStatus.active
        created = 0
        async with self.sessions() as session:
            for item in items:
                mem, is_new = await memory.remember(
                    session,
                    user.id,
                    item["content"],
                    item["kind"],
                    "auto",
                    status,
                    job.chat_id,
                    actor="agent",
                )
                created += int(is_new)
                if is_new and status == MemoryStatus.active and self.external_memory:
                    await self.external_memory.add(user.id, mem.content, mem.kind)
            await session.commit()
        if created and status == MemoryStatus.active:
            await self.rebuild_profile(user.id, plans)
        return created

    async def rebuild_profile(self, user_id: uuid.UUID, plans: list[_Plan] | None = None) -> str | None:
        """Refresh the short user model that is injected into every chat."""
        async with self.sessions() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            mems = (
                await session.scalars(
                    select(Memory)
                    .where(Memory.user_id == user_id, Memory.status == MemoryStatus.active)
                    .order_by(Memory.pinned.desc(), Memory.use_count.desc(), Memory.created_at.desc())
                    .limit(40)
                )
            ).all()
            if plans is None:
                plans = await self._plans(session, user, "auto", "ringkas profil")
            if not mems:
                text = ""
            else:
                text = await self._cheap_call(plans, memory.profile_request(list(mems)), 250) or ""
            user.settings = {
                **(user.settings or {}),
                "memory_profile": text,
                "memory_profile_at": utcnow().isoformat(),
            }
            audit.record(session, user_id, "agent", "memory.profile_rebuild", "", memories=len(mems))
            await session.commit()
            return text

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
        prefs = memory.settings_of(ctx.user)
        if status == JobStatus.done and self.enqueue and prefs["enabled"] and prefs["auto"]:
            await self.enqueue("learn_from_job", str(ctx.job.id))
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
                    memories_used=ctx.memories_used,
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
