"""Builds the shared service graph (used by the API process and the worker)."""

from typing import Any

from app.core.config import Settings
from app.core.encryption import KeyCipher
from app.db.session import SessionFactory
from app.models import ProviderKey
from app.services.events import JobEvents
from app.services.jobs import JobRunner
from app.services.key_pool import KeyPool
from app.services.llm import LiteLLMClient, LLMClient, MockLLMClient, RoutingLLMClient
from app.services.notify import Event, Notifier, build_notifier


def build_llm(settings: Settings) -> LLMClient:
    mock = MockLLMClient() if settings.enable_mock_provider else None
    return RoutingLLMClient(LiteLLMClient(), mock)


def build_runner(
    sessions: SessionFactory,
    redis: Any,
    settings: Settings,
    llm: LLMClient | None = None,
    notifier: Notifier | None = None,
    **pool_options: Any,
) -> JobRunner:
    notifier = notifier or build_notifier(sessions, settings)

    async def on_invalid(key: ProviderKey) -> None:
        from app.models import Provider, User

        async with sessions() as session:
            provider = await session.get(Provider, key.provider_id)
            user = await session.get(User, provider.user_id) if provider else None
        if user is not None and provider is not None:
            await notifier.notify(
                user,
                Event(
                    "key_invalid",
                    "API key ditolak",
                    f"Key '{key.label}' ({provider.name}) ditandai invalid (401/403).",
                    "/providers",
                ),
            )

    options: dict[str, Any] = {
        "max_concurrency": settings.key_max_concurrency,
        "default_cooldown": settings.default_cooldown_seconds,
        **pool_options,
    }
    pool = KeyPool(
        sessions,
        redis,
        KeyCipher(settings.master_encryption_key),
        llm or build_llm(settings),
        on_invalid=on_invalid,
        **options,
    )
    return JobRunner(sessions, pool, JobEvents(redis, settings.stream_ttl_seconds), notifier, settings)
