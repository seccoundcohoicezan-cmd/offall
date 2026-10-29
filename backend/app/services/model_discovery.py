"""Reads the live model list from each provider so OFALL never relies on a stale,
hard-coded model name (providers retire models; Gemini 2.5 Flash was one).

Only metadata endpoints are called, never a completion: safe in an HTTP request.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModel, Provider
from app.services.catalog import PROVIDERS
from app.services.llm import NO_KEY

MAX_MODELS = 300
SKIP = re.compile(
    r"(embed|whisper|tts|transcri|dall-e|imagen|image-gen|moderation|guard|audio|realtime|"
    r"speech|aqa|vision-only|search-preview|computer-use|babbage|davinci|omni-moderation|veo|lyria)",
    re.IGNORECASE,
)
# Whole-word matching: "mini" must not match inside "gemini".
CHEAP = re.compile(
    r"(?<![a-z0-9])(mini|nano|flash|haiku|small|lite|[1-9]b|instant|free|tiny)(?![a-z])", re.IGNORECASE
)
STRONG = re.compile(
    r"(?<![a-z0-9])(gpt-[45][a-z0-9.]*|(opus|sonnet|o1|o3|o4|pro|large|70b|405b|r1|coder|ultra)(?![a-z]))",
    re.IGNORECASE,
)

OFFICIAL_BASES = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
}


class DiscoveryError(Exception):
    pass


@dataclass
class Found:
    name: str
    display: str
    tier: str
    context: int = 128_000
    cost_in: float = 0.0
    cost_out: float = 0.0


@dataclass
class SyncResult:
    added: list[str]
    disabled: list[str]
    total: int


def guess_tier(name: str) -> str:
    if CHEAP.search(name):
        return "cheap"
    return "strong" if STRONG.search(name) else "cheap"


def _base(provider: Provider) -> str:
    spec = PROVIDERS.get(provider.name)
    base = (
        provider.base_url
        or (spec.default_base_url if spec else None)
        or OFFICIAL_BASES.get(provider.name, "")
    )
    return base.rstrip("/")


def _openai_style(data: dict[str, Any]) -> list[Found]:
    out = []
    for m in data.get("data", []):
        mid = str(m.get("id") or "")
        if not mid or SKIP.search(mid):
            continue
        pricing = m.get("pricing") or {}
        try:  # OpenRouter publishes USD per token
            cost_in = float(pricing.get("prompt", 0)) * 1e6
            cost_out = float(pricing.get("completion", 0)) * 1e6
        except (TypeError, ValueError):
            cost_in = cost_out = 0.0
        tier = "cheap" if mid.endswith(":free") else guess_tier(mid)
        context = int(
            m.get("context_length") or m.get("context_window") or m.get("max_context_length") or 128_000
        )
        out.append(
            Found(mid, str(m.get("name") or m.get("display_name") or mid), tier, context, cost_in, cost_out)
        )
    return out


async def discover(
    provider: Provider, secret: str | None, transport: httpx.AsyncBaseTransport | None = None
) -> list[Found]:
    base = _base(provider)
    if not base:
        raise DiscoveryError("Base URL provider belum diisi.")
    has_key = bool(secret) and secret != NO_KEY
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as client:
            if provider.name == "gemini":
                found: list[Found] = []
                token = ""
                for _ in range(5):  # paginated
                    params = {"pageSize": "1000", **({"pageToken": token} if token else {})}
                    resp = await client.get(
                        f"{base}/models", params=params, headers={"x-goog-api-key": secret or ""}
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    for m in body.get("models", []):
                        name = str(m.get("name", "")).removeprefix("models/")
                        methods = m.get("supportedGenerationMethods") or []
                        if not name or "generateContent" not in methods or SKIP.search(name):
                            continue
                        found.append(
                            Found(
                                name,
                                str(m.get("displayName") or name),
                                guess_tier(name),
                                int(m.get("inputTokenLimit") or 128_000),
                            )
                        )
                    token = body.get("nextPageToken") or ""
                    if not token:
                        break
                return found
            if provider.name == "anthropic":
                resp = await client.get(
                    f"{base}/models",
                    params={"limit": "100"},
                    headers={"x-api-key": secret or "", "anthropic-version": "2023-06-01"},
                )
                resp.raise_for_status()
                return [
                    Found(
                        str(m["id"]), str(m.get("display_name") or m["id"]), guess_tier(str(m["id"])), 200_000
                    )
                    for m in resp.json().get("data", [])
                    if m.get("id")
                ]
            if provider.name == "ollama":
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                return [
                    Found(str(m["name"]), str(m["name"]), "cheap", 8192)
                    for m in resp.json().get("models", [])
                    if m.get("name") and not SKIP.search(str(m["name"]))
                ]
            headers = {"Authorization": f"Bearer {secret}"} if has_key else {}
            resp = await client.get(f"{base}/models", headers=headers)
            resp.raise_for_status()
            return _openai_style(resp.json())
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        hint = "key ditolak" if status in (401, 403) else f"HTTP {status}"
        raise DiscoveryError(f"Provider menolak permintaan daftar model ({hint}).") from exc
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise DiscoveryError(f"Gagal membaca daftar model: {type(exc).__name__}") from exc


async def sync(
    db: AsyncSession,
    provider: Provider,
    secret: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SyncResult:
    """Adds new models, re-enables ones that came back and disables the ones the
    provider no longer lists. Caller commits."""
    found = (await discover(provider, secret, transport))[:MAX_MODELS]
    if not found:
        raise DiscoveryError("Provider tidak mengembalikan model chat apa pun untuk key ini.")
    live = {f.name: f for f in found}
    rows = {
        m.model_name: m
        for m in (await db.scalars(select(AIModel).where(AIModel.provider_id == provider.id))).all()
    }
    added, disabled = [], []
    for name, f in live.items():
        row = rows.get(name)
        if row is None:
            db.add(
                AIModel(
                    id=uuid.uuid4(),
                    provider_id=provider.id,
                    model_name=name,
                    display_name=f.display[:200],
                    tier=f.tier,
                    context_window=f.context,
                    cost_in=f.cost_in,
                    cost_out=f.cost_out,
                )
            )
            added.append(name)
        elif not row.is_enabled and row.display_name.endswith("(tidak tersedia)"):
            row.is_enabled = True
            row.display_name = row.display_name.removesuffix(" (tidak tersedia)")
    for name, row in rows.items():
        if name not in live and row.is_enabled:
            row.is_enabled = False
            if not row.display_name.endswith("(tidak tersedia)"):
                row.display_name = f"{row.display_name} (tidak tersedia)"[:200]
            disabled.append(name)
    return SyncResult(added, disabled, len(live))


async def retire(db: AsyncSession, provider_id: uuid.UUID, model_name: str) -> None:
    row = await db.scalar(
        select(AIModel).where(AIModel.provider_id == provider_id, AIModel.model_name == model_name)
    )
    if row is not None and row.is_enabled:
        row.is_enabled = False
        if not row.display_name.endswith("(tidak tersedia)"):
            row.display_name = f"{row.display_name} (tidak tersedia)"[:200]
