"""Model selection. `auto` uses a cheap keyword/length heuristic, not an LLM call."""

import re
from dataclasses import dataclass

from app.services.catalog import model_ref

CODE_HINTS = re.compile(
    r"```|\b(code|kode|coding|bug|error|debug|function|fungsi|class|python|javascript|"
    r"typescript|sql|regex|api|script|deploy|docker|refactor|compile|stack ?trace)\b",
    re.IGNORECASE,
)
COMPLEX_HINTS = re.compile(
    r"\b(analisis|analisa|analyze|analysis|jelaskan secara (rinci|detail)|step by step|"
    r"langkah demi langkah|bandingkan|compare|strategi|strategy|rancang|design|arsitektur|"
    r"architecture|proof|buktikan|essay|esai|laporan|report|research|riset)\b",
    re.IGNORECASE,
)
LIGHT_HINTS = re.compile(
    r"\b(ringkas|ringkasan|summari[sz]e|summary|terjemah|translate|halo|hai|hi|hello|"
    r"thanks|terima kasih|apa kabar)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    provider: str
    model_name: str
    tier: str

    @property
    def ref(self) -> str:
        return model_ref(self.provider, self.model_name)


def classify(text: str) -> str:
    """Return "coding", "complex" or "light"."""
    if CODE_HINTS.search(text):
        return "coding"
    if COMPLEX_HINTS.search(text) or len(text) > 1500:
        return "complex"
    if LIGHT_HINTS.search(text) or len(text) < 200:
        return "light"
    return "complex"


UNSTABLE = re.compile(r"(preview|exp\b|experimental|-latest|\d{2}-\d{4}|\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _apply_order(candidates: list[Candidate], order: list[str]) -> list[Candidate]:
    """User order first; otherwise stable models before preview/experimental ones."""
    rank = {ref: i for i, ref in enumerate(order)}
    return sorted(
        candidates,
        key=lambda c: (rank.get(c.ref, len(rank)), bool(UNSTABLE.search(c.model_name)), c.model_name),
    )


def plan(
    requested: str,
    prompt: str,
    available: list[Candidate],
    fallback_order: list[str],
    allow_fallback: bool,
) -> list[Candidate]:
    """Ordered list of models to try for one job."""
    ordered = _apply_order(available, fallback_order)
    if requested != "auto":
        chosen = [c for c in ordered if c.ref == requested]
        if not allow_fallback:
            return chosen
        return chosen + [c for c in ordered if c.ref != requested]

    want = "strong" if classify(prompt) in ("coding", "complex") else "cheap"
    if fallback_order:
        # A user-defined order wins, but the tier still decides who goes first.
        first = [c for c in ordered if c.tier == want]
        rest = [c for c in ordered if c.tier != want]
        return first + rest
    return [c for c in ordered if c.tier == want] + [c for c in ordered if c.tier != want]
