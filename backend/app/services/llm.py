"""LLM adapter: wraps LiteLLM streaming and normalises provider errors.

Everything above this module only sees `LLMError` subclasses, so the key pool
can decide whether to cool down, exhaust, invalidate or just skip a key.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.catalog import PROVIDERS

log = logging.getLogger(__name__)

NO_KEY = "local"  # stored for providers that don't need a key (Ollama, keyless 9Router)


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExhausted(LLMError):
    pass


class InvalidKey(LLMError):
    pass


class TransientError(LLMError):
    pass


class BadRequest(LLMError):
    """Request itself is wrong (e.g. context too long). Retrying another key won't help."""


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class StreamRequest:
    provider: str
    model_name: str
    messages: list[dict[str, Any]]
    api_key: str | None
    base_url: str | None
    max_tokens: int


class LLMClient(Protocol):
    def stream(self, req: StreamRequest, usage: Usage) -> AsyncIterator[str]: ...


_QUOTA_HINTS = ("insufficient_quota", "credit", "billing", "quota", "payment required")


def classify_error(exc: Exception) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if status == 402 or any(h in text for h in _QUOTA_HINTS):
        return QuotaExhausted(_short(exc))
    if status == 429:
        return RateLimited(_short(exc), _retry_after(exc))
    if status in (401, 403):
        return InvalidKey(_short(exc))
    if status in (400, 404, 413, 422):
        return BadRequest(_short(exc))
    return TransientError(_short(exc))


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after") if hasattr(headers, "get") else None
    if value is None:
        match = re.search(r"retry after (\d+(?:\.\d+)?)", str(exc).lower())
        value = match.group(1) if match else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


PROMPT_CACHE_MIN_CHARS = 4096  # ~1024 tokens, Anthropic's minimum cacheable prefix
PROMPT_CACHE_PROVIDERS = ("anthropic",)


def with_prompt_cache(provider: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Marks a long system prompt as cacheable. OpenAI/Gemini cache long prefixes
    automatically; Anthropic needs an explicit cache_control breakpoint."""
    if provider not in PROMPT_CACHE_PROVIDERS:
        return messages
    out = []
    for m in messages:
        content = m.get("content")
        if m.get("role") == "system" and isinstance(content, str) and len(content) >= PROMPT_CACHE_MIN_CHARS:
            m = {
                **m,
                "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}],
            }
        out.append(m)
    return out


class LiteLLMClient:
    def _kwargs(self, req: StreamRequest, stream: bool) -> dict[str, Any]:
        spec = PROVIDERS[req.provider]
        kwargs: dict[str, Any] = {
            "model": f"{spec.litellm_prefix}/{req.model_name}",
            "messages": with_prompt_cache(req.provider, req.messages),
            "max_tokens": req.max_tokens,
            "num_retries": 0,
            "timeout": 120 if stream else 30,
        }
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        if req.api_key and (spec.needs_key or req.api_key != NO_KEY):
            kwargs["api_key"] = req.api_key
        elif spec.litellm_prefix == "openai":
            kwargs["api_key"] = "sk-no-key"  # OpenAI client insists on a value; keyless gateways ignore it
        if req.base_url or spec.default_base_url:
            kwargs["api_base"] = req.base_url or spec.default_base_url
        return kwargs

    async def stream(self, req: StreamRequest, usage: Usage) -> AsyncIterator[str]:
        import litellm

        try:
            response = await litellm.acompletion(**self._kwargs(req, stream=True))
            async for chunk in response:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage.tokens_in = int(getattr(chunk_usage, "prompt_tokens", 0) or 0)
                    usage.tokens_out = int(getattr(chunk_usage, "completion_tokens", 0) or 0)
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    text = getattr(delta, "content", None)
                    if text:
                        yield text
        except Exception as exc:  # provider SDKs raise many types; normalise them
            raise _logged(req, exc) from exc

    async def ping(self, req: StreamRequest) -> None:
        """Smallest real request (non-streaming) used by the "Tes" button."""
        import litellm

        try:
            await litellm.acompletion(**self._kwargs(req, stream=False))
        except Exception as exc:
            raise _logged(req, exc) from exc


def root_cause(exc: BaseException) -> str:
    """Innermost exception in the chain. LiteLLM scrubs paths/private hosts out of its
    own messages, which can hide the real reason (e.g. which host failed)."""
    seen: set[int] = set()
    cur: BaseException = exc
    while id(cur) not in seen:
        seen.add(id(cur))
        nxt = cur.__cause__ or cur.__context__
        if nxt is None:
            break
        cur = nxt
    return "" if cur is exc else f"{type(cur).__name__}: {str(cur)[:300]}"


def _logged(req: StreamRequest, exc: Exception) -> LLMError:
    err = classify_error(exc)
    cause = root_cause(exc)
    if cause and cause not in str(err):
        err.args = (f"{err} | penyebab: {cause}",)
    # The formatter redacts key-like strings; provider error bodies don't echo keys.
    log.warning(
        "provider call failed: %s",
        str(err)[:700],
        extra={"provider": req.provider, "model": req.model_name, "event": type(err).__name__},
    )
    return err


class MockLLMClient:
    """Deterministic offline provider for demos and E2E tests (ENABLE_MOCK_PROVIDER=true).

    The API key controls behaviour so rotation can be demoed without real accounts:
    a key containing "ratelimit" always 429s, "quota" is exhausted, "invalid" 401s.
    """

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay

    async def stream(self, req: StreamRequest, usage: Usage) -> AsyncIterator[str]:
        key = (req.api_key or "").lower()
        if "ratelimit" in key:
            raise RateLimited("mock 429", retry_after=60)
        if "quota" in key:
            raise QuotaExhausted("mock quota exhausted")
        if "invalid" in key:
            raise InvalidKey("mock 401")
        last_user = next((m["content"] for m in reversed(req.messages) if m["role"] == "user"), "")
        if isinstance(last_user, list):
            last_user = " ".join(str(p.get("text", "")) for p in last_user)
        reply = f"[{req.model_name}] Jawaban untuk: {str(last_user)[:200]}"
        usage.tokens_in = sum(len(str(m["content"])) // 4 + 1 for m in req.messages)
        for word in reply.split(" "):
            await asyncio.sleep(self.delay)
            usage.tokens_out += 1
            yield word + " "


async def ping_via_stream(client: LLMClient, req: StreamRequest) -> None:
    async for _ in client.stream(req, Usage()):
        break


class RoutingLLMClient:
    """Sends the mock provider to MockLLMClient and everything else to LiteLLM."""

    def __init__(self, real: LLMClient, mock: LLMClient | None) -> None:
        self.real = real
        self.mock = mock

    def stream(self, req: StreamRequest, usage: Usage) -> AsyncIterator[str]:
        if req.provider == "mock":
            if self.mock is None:
                raise InvalidKey("mock provider disabled")
            return self.mock.stream(req, usage)
        return self.real.stream(req, usage)

    async def ping(self, req: StreamRequest) -> None:
        if req.provider == "mock":
            if self.mock is None:
                raise InvalidKey("mock provider disabled")
            await ping_via_stream(self.mock, req)
            return
        real_ping = getattr(self.real, "ping", None)
        if real_ping is not None:
            await real_ping(req)
            return
        await ping_via_stream(self.real, req)
