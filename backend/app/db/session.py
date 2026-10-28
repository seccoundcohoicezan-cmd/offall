from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

SessionFactory = async_sessionmaker[AsyncSession]


def make_engine(url: str) -> AsyncEngine:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    return create_async_engine(url, **kwargs)


_engine: AsyncEngine | None = None
_factory: SessionFactory | None = None


def get_session_factory() -> SessionFactory:
    global _engine, _factory
    if _factory is None:
        _engine = make_engine(get_settings().database_url)
        _factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _factory


def set_session_factory(factory: SessionFactory) -> None:
    global _factory
    _factory = factory


async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
