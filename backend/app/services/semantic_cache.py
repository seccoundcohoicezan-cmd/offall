"""Per-user semantic cache.

Embeddings are computed locally (hashed word + character-trigram vectors) so a
cache lookup never spends provider tokens. It catches rephrasings with mostly the
same wording; see docs/DECISIONS.md for why no external embedding model is used.
"""

import hashlib
import math
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CacheEntry

DIM = 512
WORD = re.compile(r"\w+", re.UNICODE)
MAX_ENTRIES_SCANNED = 500


def _bucket(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big") % DIM


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    normalized = " ".join(WORD.findall(text.lower()))
    for word in normalized.split():
        vec[_bucket("w:" + word)] += 2.0
    padded = f"  {normalized}  "
    for i in range(len(padded) - 2):
        vec[_bucket("c:" + padded[i : i + 3])] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def prompt_hash(scope: str, text: str) -> str:
    return hashlib.sha256(f"{scope}\x00{text.strip().lower()}".encode()).hexdigest()


def scope_for(model_requested: str, system_prompt: str) -> str:
    return hashlib.sha256(f"{model_requested}\x00{system_prompt}".encode()).hexdigest()[:64]


async def lookup(
    session: AsyncSession, user_id: uuid.UUID, scope: str, text: str, threshold: float
) -> CacheEntry | None:
    digest = prompt_hash(scope, text)
    exact = await session.scalar(
        select(CacheEntry).where(
            CacheEntry.user_id == user_id,
            CacheEntry.scope == scope,
            CacheEntry.prompt_hash == digest,
        )
    )
    if exact is not None:
        return exact
    query_vec = embed(text)
    rows = await session.scalars(
        select(CacheEntry)
        .where(CacheEntry.user_id == user_id, CacheEntry.scope == scope)
        .order_by(CacheEntry.created_at.desc())
        .limit(MAX_ENTRIES_SCANNED)
    )
    best: tuple[float, CacheEntry | None] = (0.0, None)
    for entry in rows:
        score = cosine(query_vec, entry.embedding)
        if score > best[0]:
            best = (score, entry)
    return best[1] if best[0] >= threshold else None


def make_entry(user_id: uuid.UUID, scope: str, text: str, response: str, model: str) -> CacheEntry:
    return CacheEntry(
        user_id=user_id,
        scope=scope,
        prompt_hash=prompt_hash(scope, text),
        embedding=embed(text),
        response=response,
        model=model,
    )
