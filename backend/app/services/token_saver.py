"""Shrinks chat history before it is sent to a model.

Pipeline: normalise -> dedupe -> sliding window (+ rolling summary handled by
summarizer.py). Code blocks, inline code, tables, numbers and URLs are protected:
they are never rewritten, and messages that carry them are never near-deduped.
"""

import difflib
import hashlib
import re
from dataclasses import dataclass
from typing import Any

FENCE = re.compile(r"(```.*?(?:```|$)|~~~.*?(?:~~~|$)|`[^`\n]+`)", re.DOTALL)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
URL = re.compile(r"https?://\S+")
PLEASANTRY = re.compile(
    r"^\s*(?:(?:halo|hai|hi|hello|hey|selamat (?:pagi|siang|sore|malam)|"
    r"terima ?kasih(?: banyak)?|makasih|thanks?(?: you)?|thank you|tolong ya|please|"
    r"mohon bantuannya|sama-sama|you're welcome|oke+|ok|baik)[\s,.!]*)+",
    re.IGNORECASE,
)

MODES: dict[str, dict[str, int]] = {
    "off": {"window": 10_000, "summary_after": 10_000},
    "normal": {"window": 12, "summary_after": 24},
    "aggressive": {"window": 6, "summary_after": 10},
}
NEAR_DUP_RATIO = 0.92


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4 if text else 0


def count_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens(str(m.get("content", ""))) + 4 for m in messages)


def _split_protected(text: str) -> list[tuple[bool, str]]:
    parts: list[tuple[bool, str]] = []
    pos = 0
    for match in FENCE.finditer(text):
        if match.start() > pos:
            parts.append((False, text[pos : match.start()]))
        parts.append((True, match.group(0)))
        pos = match.end()
    if pos < len(text):
        parts.append((False, text[pos:]))
    return parts


def _normalize_prose(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if TABLE_ROW.match(line):
            lines.append(line.rstrip())  # keep table alignment untouched
        else:
            lines.append(re.sub(r"[ \t]+", " ", line).rstrip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _drop_repeated_sentences(text)


def _drop_repeated_sentences(text: str) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for line in text.split("\n"):
        if TABLE_ROW.match(line) or not line.strip():
            out.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = []
        for s in sentences:
            k = s.strip().lower()
            if len(k) > 20 and k in seen:
                continue
            seen.add(k)
            kept.append(s)
        out.append(" ".join(kept))
    return "\n".join(out)


def normalize(text: str, strip_pleasantries: bool = False) -> str:
    parts = _split_protected(text)
    result = []
    for i, (protected, chunk) in enumerate(parts):
        if protected:
            result.append(chunk)
            continue
        chunk = _normalize_prose(chunk)
        if strip_pleasantries and i == 0:
            stripped = PLEASANTRY.sub("", chunk, count=1)
            chunk = stripped if stripped.strip() else chunk
        result.append(chunk)
    return "".join(result).strip()


def is_protected(text: str) -> bool:
    return bool(FENCE.search(text) or TABLE_ROW.search(text))


def _fingerprint(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return tuple(NUMBER.findall(text)), tuple(URL.findall(text))


def _is_pleasantry_only(text: str) -> bool:
    return not PLEASANTRY.sub("", text).strip(" \n\t.,!?")


def dedupe(messages: list[dict[str, Any]], aggressive: bool = False) -> list[dict[str, Any]]:
    """Drop repeated messages. The last message (the current prompt) is always kept."""
    if not messages:
        return []
    *history, current = messages
    seen_hashes: set[str] = set()
    kept: list[dict[str, Any]] = []
    for msg in history:
        content = str(msg["content"])
        digest = hashlib.sha256(f"{msg['role']}\x00{content}".encode()).hexdigest()
        if digest in seen_hashes:
            continue
        if aggressive and _is_pleasantry_only(content):
            continue
        if not is_protected(content) and _near_duplicate(msg, kept):
            continue
        seen_hashes.add(digest)
        kept.append(msg)
    return _merge_same_role([*kept, current])


def _near_duplicate(msg: dict[str, Any], kept: list[dict[str, Any]]) -> bool:
    content = str(msg["content"])
    fp = _fingerprint(content)
    for other in kept[-20:]:
        other_content = str(other["content"])
        if other["role"] != msg["role"] or is_protected(other_content):
            continue
        if _fingerprint(other_content) != fp:
            continue  # different numbers/URLs means different meaning
        ratio = difflib.SequenceMatcher(None, content.lower(), other_content.lower()).ratio()
        if ratio >= NEAR_DUP_RATIO:
            return True
    return False


def _merge_same_role(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"] and msg["role"] != "system":
            merged[-1] = {**merged[-1], "content": f"{merged[-1]['content']}\n\n{msg['content']}"}
        else:
            merged.append(dict(msg))
    return merged


@dataclass
class SaverResult:
    messages: list[dict[str, Any]]
    tokens_before: int
    tokens_after: int

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)


def apply(
    history: list[dict[str, Any]],
    mode: str = "normal",
    system_prompt: str = "",
    summary: str | None = None,
) -> SaverResult:
    """`history` is user/assistant turns ending with the current user message."""
    cfg = MODES.get(mode, MODES["normal"])
    system = [{"role": "system", "content": system_prompt}] if system_prompt else []
    before = count_tokens(system + history)
    if mode == "off":
        return SaverResult(system + list(history), before, before)

    aggressive = mode == "aggressive"
    cleaned = [
        {**m, "content": normalize(str(m["content"]), strip_pleasantries=i < len(history) - 1)}
        for i, m in enumerate(history)
    ]
    deduped = dedupe(cleaned, aggressive=aggressive)

    window = cfg["window"]
    recent = deduped[-window:]
    if len(recent) > 1 and recent[0]["role"] == "assistant":
        recent = recent[1:]  # a window should start on a user turn

    context = list(system)
    if summary:
        context.append({"role": "system", "content": f"Ringkasan percakapan sebelumnya:\n{summary}"})
    final = context + recent
    return SaverResult(final, before, count_tokens(final))
