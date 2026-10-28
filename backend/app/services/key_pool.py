"""Key pool with automatic rotation across a provider's API keys.

Concurrency safety:
- status transitions are single conditional UPDATEs, so two workers marking the
  same key can't resurrect an `invalid`/`disabled` key;
- each key has a Redis lease counter capped at KEY_MAX_CONCURRENCY, so parallel
  workers spread over keys instead of piling onto one;
- round-robin uses an atomic Redis INCR cursor.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

from sqlalchemy import or_, select, update

from app.core.encryption import KeyCipher
from app.db.base import as_utc, utcnow
from app.db.session import SessionFactory
from app.models import KeyStatus, Provider, ProviderKey, RotationStrategy
from app.services.llm import (
    BadRequest,
    InvalidKey,
    LLMClient,
    QuotaExhausted,
    RateLimited,
    StreamRequest,
    TransientError,
    Usage,
)

log = logging.getLogger(__name__)

RECOVERABLE = (KeyStatus.active, KeyStatus.cooling_down, KeyStatus.exhausted)
CONTINUE_PROMPT = (
    "Jawabanmu sebelumnya terpotong. Lanjutkan tepat dari kata terakhir, tanpa mengulang teks yang sudah ada."
)


class NoKeyAvailable(Exception):
    def __init__(self, provider: str, retry_at: datetime | None = None) -> None:
        super().__init__(f"no usable key for provider {provider}")
        self.provider = provider
        self.retry_at = retry_at


class LeaseStore(Protocol):
    async def incr(self, name: str) -> int: ...
    async def decr(self, name: str) -> int: ...
    async def expire(self, name: str, time: int) -> Any: ...


@dataclass
class PoolResult:
    key_id: uuid.UUID
    text: str
    usage: Usage


def next_reset(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)


def is_usable(key: ProviderKey, now: datetime) -> bool:
    if key.status == KeyStatus.active:
        return not _over_daily_quota(key, now.date())
    if key.status == KeyStatus.cooling_down:
        until = as_utc(key.cooldown_until)
        return until is None or until <= now
    if key.status == KeyStatus.exhausted:
        until = as_utc(key.reset_at)
        return until is not None and until <= now
    return False


def recovery_time(key: ProviderKey) -> datetime | None:
    if key.status == KeyStatus.cooling_down:
        return as_utc(key.cooldown_until)
    if key.status == KeyStatus.exhausted:
        return as_utc(key.reset_at)
    if key.status == KeyStatus.active and key.daily_token_quota:
        return next_reset()
    return None


def _over_daily_quota(key: ProviderKey, today: date) -> bool:
    if not key.daily_token_quota or key.usage_day != today:
        return False
    return key.tokens_used_today >= key.daily_token_quota


def continuation_messages(messages: list[dict[str, Any]], partial: str) -> list[dict[str, Any]]:
    if not partial:
        return messages
    return [
        *messages,
        {"role": "assistant", "content": partial},
        {"role": "user", "content": CONTINUE_PROMPT},
    ]


class KeyPool:
    def __init__(
        self,
        sessions: SessionFactory,
        leases: LeaseStore,
        cipher: KeyCipher,
        llm: LLMClient,
        max_concurrency: int = 4,
        default_cooldown: int = 60,
        on_invalid: Callable[[ProviderKey], Awaitable[None]] | None = None,
        busy_wait: float = 0.5,
        busy_timeout: float = 30.0,
    ) -> None:
        self.sessions = sessions
        self.leases = leases
        self.cipher = cipher
        self.llm = llm
        self.max_concurrency = max_concurrency
        self.default_cooldown = default_cooldown
        self.on_invalid = on_invalid
        self.busy_wait = busy_wait
        self.busy_timeout = busy_timeout

    async def ordered_keys(self, provider: Provider) -> list[ProviderKey]:
        """Usable keys in the order the provider's rotation strategy wants them tried."""
        now = utcnow()
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(ProviderKey)
                    .where(ProviderKey.provider_id == provider.id)
                    .where(ProviderKey.status.in_(RECOVERABLE))
                    .order_by(ProviderKey.priority, ProviderKey.created_at)
                )
            ).all()
        keys = [k for k in rows if is_usable(k, now)]
        strategy = provider.rotation_strategy
        if strategy == RotationStrategy.least_used and keys:
            today = now.date()
            keys.sort(key=lambda k: k.tokens_used_today if k.usage_day == today else 0)
        elif strategy == RotationStrategy.round_robin and keys:
            cursor = await self.leases.incr(f"rr:{provider.id}")
            start = (cursor - 1) % len(keys)
            keys = keys[start:] + keys[:start]
        return keys

    async def earliest_recovery(self, provider_id: uuid.UUID) -> datetime | None:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(ProviderKey).where(
                        ProviderKey.provider_id == provider_id,
                        ProviderKey.status.in_(RECOVERABLE),
                    )
                )
            ).all()
        times = [t for t in (recovery_time(k) for k in rows) if t is not None]
        return min(times) if times else None

    async def stream(
        self,
        provider: Provider,
        model_name: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        on_text: Callable[[str], Awaitable[None]],
        prefix: str = "",
        should_stop: Callable[[], Awaitable[bool]] | None = None,
    ) -> PoolResult:
        """Try keys in order until one completes. `prefix` is output already shown to the
        user (from an earlier key/provider) which the next attempt must continue."""
        produced = ""
        deadline = asyncio.get_running_loop().time() + self.busy_timeout
        while True:
            keys = await self.ordered_keys(provider)
            if not keys:
                raise NoKeyAvailable(provider.name, await self.earliest_recovery(provider.id))
            all_busy = True
            for key in keys:
                lease = f"keylease:{key.id}"
                if not await self._acquire(lease):
                    continue
                all_busy = False
                try:
                    secret = self.cipher.decrypt(key.api_key_encrypted)
                    usage = Usage()
                    req = StreamRequest(
                        provider=provider.name,
                        model_name=model_name,
                        messages=continuation_messages(messages, prefix + produced),
                        api_key=secret,
                        base_url=provider.base_url,
                        max_tokens=max_tokens,
                    )
                    attempt_text = ""
                    async for text in self.llm.stream(req, usage):
                        attempt_text += text
                        produced += text
                        await on_text(text)
                        if should_stop and await should_stop():
                            break
                    await self.mark_ok(key.id, usage.tokens_in + usage.tokens_out)
                    return PoolResult(key.id, produced, usage)
                except RateLimited as exc:
                    wait = exc.retry_after or self.default_cooldown
                    await self.mark_cooling(key.id, wait, str(exc))
                except QuotaExhausted as exc:
                    await self.mark_exhausted(key.id, str(exc))
                except InvalidKey as exc:
                    await self.mark_invalid(key.id, str(exc))
                except TransientError as exc:
                    await self.note_error(key.id, str(exc))
                except BadRequest:
                    raise
                finally:
                    await self.leases.decr(lease)
                log.info(
                    "key failed, rotating",
                    extra={"provider": provider.name, "key_id": str(key.id)},
                )
            if not all_busy:
                raise NoKeyAvailable(provider.name, await self.earliest_recovery(provider.id))
            if asyncio.get_running_loop().time() > deadline:
                raise TransientError(f"all {provider.name} keys busy")
            await asyncio.sleep(self.busy_wait)

    async def _acquire(self, lease: str) -> bool:
        count = await self.leases.incr(lease)
        await self.leases.expire(lease, 3600)
        if count > self.max_concurrency:
            await self.leases.decr(lease)
            return False
        return True

    async def _set(self, key_id: uuid.UUID, **values: Any) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(ProviderKey)
                .where(ProviderKey.id == key_id)
                .where(ProviderKey.status.in_(RECOVERABLE))
                .values(**values)
            )
            await session.commit()

    async def mark_cooling(self, key_id: uuid.UUID, seconds: float, error: str) -> None:
        until = utcnow() + timedelta(seconds=seconds)
        await self._set(key_id, status=KeyStatus.cooling_down, cooldown_until=until, last_error=error[:500])

    async def mark_exhausted(self, key_id: uuid.UUID, error: str) -> None:
        await self._set(key_id, status=KeyStatus.exhausted, reset_at=next_reset(), last_error=error[:500])

    async def mark_invalid(self, key_id: uuid.UUID, error: str) -> None:
        await self._set(key_id, status=KeyStatus.invalid, last_error=error[:500])
        if self.on_invalid:
            async with self.sessions() as session:
                key = await session.get(ProviderKey, key_id)
            if key is not None:
                try:
                    await self.on_invalid(key)
                except Exception:
                    log.exception("invalid-key notification failed")

    async def note_error(self, key_id: uuid.UUID, error: str) -> None:
        await self._set(key_id, last_error=error[:500])

    async def mark_ok(self, key_id: uuid.UUID, tokens: int) -> None:
        now = utcnow()
        async with self.sessions() as session:
            key = await session.get(ProviderKey, key_id, with_for_update=True)
            if key is None:
                return
            if key.usage_day != now.date():
                key.usage_day = now.date()
                key.tokens_used_today = 0
            key.tokens_used_today += tokens
            key.last_used_at = now
            if key.status in (KeyStatus.cooling_down, KeyStatus.exhausted):
                key.status = KeyStatus.active
                key.cooldown_until = None
                key.reset_at = None
            await session.commit()


async def recover_keys(sessions: SessionFactory) -> int:
    """Flip keys whose cooldown/reset time passed back to active. Returns rows changed."""
    now = utcnow()
    async with sessions() as session:
        result = await session.execute(
            update(ProviderKey)
            .where(
                or_(
                    (ProviderKey.status == KeyStatus.cooling_down) & (ProviderKey.cooldown_until <= now),
                    (ProviderKey.status == KeyStatus.exhausted) & (ProviderKey.reset_at <= now),
                )
            )
            .values(status=KeyStatus.active, cooldown_until=None, reset_at=None)
        )
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
