"""Rolling summary of old chat turns, produced by the cheapest available model."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.token_saver import MODES

SUMMARY_PROMPT = (
    "Ringkas percakapan berikut menjadi poin-poin padat (maks 200 kata). "
    "Pertahankan fakta, angka, nama, keputusan, dan potongan kode penting apa adanya."
)

Summarize = Callable[[list[dict[str, Any]]], Awaitable[str]]


def needs_summary(history_len: int, mode: str, summarized_upto: int) -> tuple[bool, int]:
    """Returns (should_run, new_upto). History is all turns incl. the current prompt."""
    cfg = MODES.get(mode, MODES["normal"])
    if mode == "off" or history_len <= cfg["summary_after"]:
        return False, summarized_upto
    upto = history_len - cfg["window"]
    return upto > summarized_upto, upto


def build_request(previous: str | None, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in turns)
    if previous:
        transcript = f"Ringkasan sebelumnya:\n{previous}\n\nLanjutan percakapan:\n{transcript}"
    return [
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": transcript},
    ]
