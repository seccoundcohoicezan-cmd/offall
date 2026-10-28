from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, agents, auth, chats, health, jobs, memory, models, providers, settings, usage
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging


async def _connect(cfg: Settings) -> tuple[Any, Any]:
    from arq import create_pool
    from arq.connections import RedisSettings

    queue = await create_pool(RedisSettings.from_dsn(cfg.redis_url))
    return queue, queue  # ArqRedis is a redis.asyncio.Redis subclass


DEV_PLACEHOLDERS = (
    "ZGV2LW9ubHktbWFzdGVyLWtleS1jaGFuZ2UtbWUhISE=",
    "dev-only-jwt-secret-change-me-before-deploying",
)


def check_secrets(cfg: Settings) -> None:
    if not cfg.master_encryption_key or not cfg.jwt_secret:
        raise RuntimeError("MASTER_ENCRYPTION_KEY and JWT_SECRET must be set")
    if cfg.environment == "production":
        if {cfg.master_encryption_key, cfg.jwt_secret} & set(DEV_PLACEHOLDERS):
            raise RuntimeError("Replace the dev placeholder secrets from .env.example before production")
        if len(cfg.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")


def create_app(redis: Any = None, queue: Any = None) -> FastAPI:
    cfg = get_settings()
    check_secrets(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        setup_logging()
        if redis is None:
            app.state.redis, app.state.queue = await _connect(cfg)
        yield
        if redis is None:
            await app.state.redis.aclose()

    app = FastAPI(title=cfg.app_name, version="0.1.0", lifespan=lifespan)
    app.state.redis = redis
    app.state.queue = queue
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    api = APIRouter(prefix="/api/v1")
    for module in (auth, providers, models, agents, chats, jobs, usage, settings, admin, memory):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api/v1")
    return app


def app_factory() -> FastAPI:
    return create_app()
