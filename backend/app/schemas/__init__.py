import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ProviderName = Literal[
    "anthropic",
    "openai",
    "gemini",
    "groq",
    "openrouter",
    "mistral",
    "ollama",
    "9router",
    "openai_compatible",
    "mock",
]
Strategy = Literal["fill_first", "round_robin", "least_used"]
SaveMode = Literal["off", "normal", "aggressive"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class UserOut(ORM):
    id: uuid.UUID
    email: str
    role: str
    display_name: str = ""
    is_active: bool = True
    created_at: datetime


Role = Literal["admin", "user"]


class AdminUserOut(UserOut):
    last_login_at: datetime | None
    chats: int = 0
    tokens_30d: int = 0
    providers: int = 0


class AdminUserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = "user"
    display_name: str = Field(default="", max_length=80)


class AdminUserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class InstanceSettings(BaseModel):
    registration_open: bool


class InstanceSettingsPatch(BaseModel):
    registration_open: bool | None = None


class SettingsIn(BaseModel):
    save_mode: SaveMode | None = None
    max_tokens: int | None = Field(default=None, ge=64, le=32_000)
    allow_fallback: bool | None = None
    fallback_order: list[str] | None = Field(default=None, max_length=100)
    favorite_models: list[str] | None = Field(default=None, max_length=100)
    system_prompt: str | None = Field(default=None, max_length=8000)
    notify_telegram_chat_id: str | None = Field(default=None, max_length=64)
    notify_webpush: bool | None = None
    memory_enabled: bool | None = None
    memory_auto_extract: bool | None = None
    memory_review: bool | None = None


class SettingsOut(BaseModel):
    save_mode: str
    max_tokens: int
    allow_fallback: bool
    fallback_order: list[str]
    favorite_models: list[str]
    system_prompt: str
    notify_telegram_chat_id: str
    notify_webpush: bool
    memory_enabled: bool
    memory_auto_extract: bool
    memory_review: bool
    vapid_public_key: str
    telegram_enabled: bool


_URL_RE = re.compile(r"^https?://[^\s/?#]+[^\s]*$", re.IGNORECASE)
_KEYISH_RE = re.compile(r"(sk-|sk_|gsk_|AIza|xai-|key-)[A-Za-z0-9_\-]{8,}")


def check_base_url(value: str | None) -> str | None:
    """Base URL must be an http(s) address. Pasting an API key here would store and
    display it in plain text, so it is rejected outright."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return ""
    if _KEYISH_RE.search(value):
        raise ValueError("Ini terlihat seperti API key. Isi API key di kolom 'API key', bukan Base URL.")
    if not _URL_RE.match(value):
        raise ValueError("Base URL harus berupa alamat http:// atau https:// (contoh: http://host:20128/v1).")
    return value.rstrip("/")


class ProviderIn(BaseModel):
    name: ProviderName
    base_url: str | None = Field(default=None, max_length=500)
    rotation_strategy: Strategy = "fill_first"

    _check_url = field_validator("base_url")(check_base_url)


class ProviderPatch(BaseModel):
    rotation_strategy: Strategy | None = None
    base_url: str | None = Field(default=None, max_length=500)

    _check_url = field_validator("base_url")(check_base_url)


class KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    api_key: str = Field(default="", max_length=500)
    priority: int | None = Field(default=None, ge=0, le=1000)
    daily_token_quota: int | None = Field(default=None, ge=1)


class KeyPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    daily_token_quota: int | None = Field(default=None, ge=0)


class KeyOut(ORM):
    id: uuid.UUID
    label: str
    key_hint: str
    status: str
    priority: int
    cooldown_until: datetime | None
    reset_at: datetime | None
    tokens_used_today: int
    daily_token_quota: int | None
    last_used_at: datetime | None
    last_error: str | None
    created_at: datetime


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    base_url: str | None
    rotation_strategy: str
    created_at: datetime
    keys: list[KeyOut]
    status_counts: dict[str, int]
    usable_keys: int


class KeyTestOut(BaseModel):
    ok: bool
    status: str
    message: str


class ModelOut(BaseModel):
    id: str
    provider: str
    provider_display: str
    model_name: str
    display_name: str
    tier: str
    is_enabled: bool
    cost_in: float
    cost_out: float
    context_window: int
    favorite: bool


class ModelPatch(BaseModel):
    is_enabled: bool


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    instructions: str = Field(default="", max_length=20_000)
    default_model: str = Field(default="auto", max_length=250)
    is_enabled: bool = True


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    instructions: str | None = Field(default=None, max_length=20_000)
    default_model: str | None = Field(default=None, max_length=250)
    is_enabled: bool | None = None


class AgentOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    instructions: str
    default_model: str
    is_enabled: bool
    created_at: datetime


class ChatIn(BaseModel):
    title: str = Field(default="Chat baru", min_length=1, max_length=200)
    default_model: str = Field(default="auto", max_length=250)
    agent_id: uuid.UUID | None = None
    mode: Literal["default", "off", "normal", "aggressive"] = "default"


class ChatPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    default_model: str | None = Field(default=None, max_length=250)
    agent_id: uuid.UUID | None = None
    clear_agent: bool = False
    mode: Literal["default", "off", "normal", "aggressive"] | None = None


class ChatOut(ORM):
    id: uuid.UUID
    title: str
    default_model: str
    mode: str
    agent_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None


class MessageIn(BaseModel):
    content: str = Field(min_length=1)
    model: str = Field(default="auto", max_length=250)
    idempotency_key: str | None = Field(default=None, max_length=80)


class MessageOut(ORM):
    id: uuid.UUID
    role: str
    content: str
    model_used: str | None
    tokens_in: int
    tokens_out: int
    tokens_saved: int
    cached: bool
    memories_used: int = 0
    created_at: datetime


class JobCreated(BaseModel):
    job_id: uuid.UUID
    message_id: uuid.UUID


class JobOut(ORM):
    id: uuid.UUID
    chat_id: uuid.UUID
    model_requested: str
    model_used: str | None
    status: str
    partial_output: str
    error: str | None
    attempts: int
    tokens_saved: int
    retry_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_message_id: uuid.UUID | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class PushSubIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: dict[str, str]


MemoryKindName = Literal["fact", "preference", "context"]


class MemoryIn(BaseModel):
    content: str = Field(min_length=3, max_length=300)
    kind: MemoryKindName = "fact"
    pinned: bool = False


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=3, max_length=300)
    kind: MemoryKindName | None = None
    pinned: bool | None = None
    status: Literal["active", "rejected"] | None = None


class MemoryOut(ORM):
    id: uuid.UUID
    kind: str
    content: str
    source: str
    status: str
    pinned: bool
    use_count: int
    last_used_at: datetime | None
    source_chat_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None


class ProfileOut(BaseModel):
    summary: str
    updated_at: str | None
    active: int
    pending: int


class HistoryHitOut(BaseModel):
    chat_id: uuid.UUID
    chat_title: str
    message_id: uuid.UUID
    role: str
    snippet: str
    created_at: datetime


class AuditOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID | None
    actor: str
    action: str
    target: str
    detail: dict[str, object]
    created_at: datetime


class CustomModelIn(BaseModel):
    model_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=200)
    tier: Literal["strong", "cheap"] = "cheap"
    cost_in: float = Field(default=0.0, ge=0)
    cost_out: float = Field(default=0.0, ge=0)
    context_window: int = Field(default=128_000, ge=1024)


class ModelSyncOut(BaseModel):
    added: list[str]
    disabled: list[str] = []
    total: int
