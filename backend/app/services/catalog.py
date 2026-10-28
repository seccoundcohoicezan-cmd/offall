"""Supported providers and the default model list seeded when a provider is added.

Costs are USD per 1M tokens (approximate list prices, editable later in the DB).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display: str
    tier: str  # "strong" or "cheap"
    cost_in: float = 0.0
    cost_out: float = 0.0
    context: int = 128_000


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    display: str
    litellm_prefix: str
    needs_key: bool = True
    default_base_url: str | None = None
    models: tuple[ModelSpec, ...] = field(default_factory=tuple)


PROVIDERS: dict[str, ProviderSpec] = {
    p.name: p
    for p in (
        ProviderSpec(
            "anthropic",
            "Claude (Anthropic)",
            "anthropic",
            models=(
                ModelSpec("claude-sonnet-4-5", "Claude Sonnet 4.5", "strong", 3, 15, 200_000),
                ModelSpec("claude-haiku-4-5", "Claude Haiku 4.5", "cheap", 1, 5, 200_000),
            ),
        ),
        ProviderSpec(
            "openai",
            "OpenAI",
            "openai",
            models=(
                ModelSpec("gpt-4o", "GPT-4o", "strong", 2.5, 10),
                ModelSpec("gpt-4o-mini", "GPT-4o mini", "cheap", 0.15, 0.6),
            ),
        ),
        ProviderSpec(
            "gemini",
            "Google Gemini",
            "gemini",
            models=(
                ModelSpec("gemini-2.5-pro", "Gemini 2.5 Pro", "strong", 1.25, 10, 1_000_000),
                ModelSpec("gemini-2.5-flash", "Gemini 2.5 Flash", "cheap", 0.3, 2.5, 1_000_000),
            ),
        ),
        ProviderSpec(
            "groq",
            "Groq",
            "groq",
            models=(
                ModelSpec("llama-3.3-70b-versatile", "Llama 3.3 70B (Groq)", "cheap", 0.59, 0.79),
                ModelSpec("llama-3.1-8b-instant", "Llama 3.1 8B (Groq)", "cheap", 0.05, 0.08),
            ),
        ),
        ProviderSpec(
            "openrouter",
            "OpenRouter",
            "openrouter",
            models=(
                ModelSpec(
                    "anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5 (OpenRouter)", "strong", 3, 15, 200_000
                ),
                ModelSpec(
                    "meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B free (OpenRouter)", "cheap"
                ),
            ),
        ),
        ProviderSpec(
            "mistral",
            "Mistral",
            "mistral",
            models=(
                ModelSpec("mistral-large-latest", "Mistral Large", "strong", 2, 6),
                ModelSpec("mistral-small-latest", "Mistral Small", "cheap", 0.2, 0.6),
            ),
        ),
        ProviderSpec(
            "ollama",
            "Ollama (lokal)",
            "ollama",
            needs_key=False,
            default_base_url="http://host.docker.internal:11434",
            models=(ModelSpec("llama3.1", "Llama 3.1 (Ollama)", "cheap", context=8192),),
        ),
        ProviderSpec(
            "mock",
            "Mock (demo/test)",
            "mock",
            needs_key=True,
            models=(
                ModelSpec("mock-strong", "Mock Strong", "strong"),
                ModelSpec("mock-fast", "Mock Fast", "cheap"),
            ),
        ),
    )
}


def model_ref(provider: str, model_name: str) -> str:
    return f"{provider}/{model_name}"


def split_model_ref(ref: str) -> tuple[str, str]:
    provider, _, model_name = ref.partition("/")
    return provider, model_name
