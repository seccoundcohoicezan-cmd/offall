import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.expression import true as sa_true

from app.db.base import Base, CreatedMixin, IdMixin


class KeyStatus(enum.StrEnum):
    active = "active"
    cooling_down = "cooling_down"
    exhausted = "exhausted"
    invalid = "invalid"
    disabled = "disabled"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    waiting_quota = "waiting_quota"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_JOB_STATUSES = (JobStatus.queued, JobStatus.running, JobStatus.waiting_quota)
TERMINAL_JOB_STATUSES = (JobStatus.done, JobStatus.failed, JobStatus.cancelled)


class RotationStrategy(enum.StrEnum):
    fill_first = "fill_first"
    round_robin = "round_robin"
    least_used = "least_used"


def default_settings() -> dict[str, Any]:
    return {
        "save_mode": "normal",
        "max_tokens": 1024,
        "allow_fallback": True,
        "fallback_order": [],
        "favorite_models": [],
        "system_prompt": "",
        "notify_telegram_chat_id": "",
        "notify_webpush": False,
        "memory_enabled": True,
        "memory_auto_extract": True,
        "memory_review": False,
    }


class User(IdMixin, CreatedMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=default_settings)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true())
    display_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    """Instance-wide switches the admin controls from the UI (override env defaults)."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class RefreshToken(CreatedMixin, Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Provider(IdMixin, CreatedMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rotation_strategy: Mapped[str] = mapped_column(String(20), default=RotationStrategy.fill_first)


class ProviderKey(IdMixin, CreatedMixin, Base):
    __tablename__ = "provider_keys"
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(80))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=KeyStatus.active, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_used_today: Mapped[int] = mapped_column(Integer, default=0)
    usage_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AIModel(IdMixin, Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("provider_id", "model_name"),)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    model_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tier: Mapped[str] = mapped_column(String(10), default="cheap")
    cost_in: Mapped[float] = mapped_column(Float, default=0.0)
    cost_out: Mapped[float] = mapped_column(Float, default=0.0)
    context_window: Mapped[int] = mapped_column(Integer, default=8192)


class Agent(IdMixin, CreatedMixin, Base):
    __tablename__ = "agents"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    default_model: Mapped[str] = mapped_column(String(250), default="auto")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Chat(IdMixin, CreatedMixin, Base):
    __tablename__ = "chats"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Chat baru")
    default_model: Mapped[str] = mapped_column(String(250), default="auto")
    # "default" follows the user's save_mode setting; otherwise off|normal|aggressive
    mode: Mapped[str] = mapped_column(String(20), default="default")
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_upto: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class Message(IdMixin, CreatedMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_chat_created", "chat_id", "created_at"),)
    chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(String(250), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saved: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    memories_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Job(IdMixin, CreatedMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("messages.id"))
    result_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_requested: Mapped[str] = mapped_column(String(250))
    model_used: Mapped[str | None] = mapped_column(String(250), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.queued, index=True)
    partial_output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saved: Mapped[int] = mapped_column(Integer, default=0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageLog(IdMixin, CreatedMixin, Base):
    __tablename__ = "usage_logs"
    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("provider_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(250))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saved: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)


class CacheEntry(IdMixin, CreatedMixin, Base):
    __tablename__ = "cache_entries"
    __table_args__ = (Index("ix_cache_user_scope", "user_id", "scope"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    response: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(250), default="")
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class PushSubscription(IdMixin, CreatedMixin, Base):
    __tablename__ = "push_subscriptions"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    keys: Mapped[dict[str, str]] = mapped_column(JSON)


class MemoryKind(enum.StrEnum):
    fact = "fact"
    preference = "preference"
    context = "context"


class MemoryStatus(enum.StrEnum):
    active = "active"
    pending = "pending"  # auto-extracted, waiting for the user's review
    rejected = "rejected"


class Memory(IdMixin, CreatedMixin, Base):
    """Long-lived knowledge about a user, shared across all of their chats."""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_status", "user_id", "status"),)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default=MemoryKind.fact)
    content: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | auto
    status: Mapped[str] = mapped_column(String(20), default=MemoryStatus.active)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_chat_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(IdMixin, CreatedMixin, Base):
    """Append-only record of what the agent, the user or an admin changed."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_user_created", "user_id", "created_at"),)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(20))  # user | agent | admin | system
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
