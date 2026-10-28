"""Persistent user memory (Hermes-style): facts & preferences that outlive a chat.

- Built-in store: the `memories` table, ranked by local embeddings (no token cost).
- Optional external store (MEMORY_EXTERNAL_URL): writes are mirrored and its search
  results are merged in; the built-in store is never bypassed or cleared.
- After each answer the worker asks a cheap model to extract durable facts
  (experimental; can be switched off or put behind manual review in Settings).
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import Chat, Memory, MemoryKind, MemoryStatus, Message, User
from app.services import audit
from app.services.semantic_cache import cosine, embed

log = logging.getLogger(__name__)

MAX_INJECTED = 8
MIN_RELEVANCE = 0.12
DUPLICATE_SIMILARITY = 0.88
MAX_MEMORIES_PER_USER = 1000

EXTRACT_PROMPT = """Kamu modul memori asisten AI. Dari percakapan di bawah, ambil HANYA informasi
tentang PENGGUNA yang berguna untuk percakapan lain di masa depan: identitas, pekerjaan,
proyek yang sedang dikerjakan, preferensi gaya jawaban, bahasa, alat yang dipakai, tujuan.
Jangan simpan isi tugas sekali-pakai, jawaban asisten, kata sandi, API key, nomor kartu,
atau data sensitif lain. Jika pengguna berkata "ingat bahwa ..." / "remember that ...",
simpan itu. Tulis tiap memori sebagai satu kalimat orang ketiga, maks 200 karakter.
Balas HANYA JSON: {"memories":[{"kind":"fact|preference|context","content":"..."}]}
Jika tidak ada yang layak disimpan, balas {"memories":[]}."""

PROFILE_PROMPT = """Ringkas memori berikut menjadi profil pengguna singkat (maks 80 kata,
bahasa Indonesia, orang ketiga): siapa dia, apa yang sedang dikerjakan, dan bagaimana dia
suka dijawab. Jangan menambah fakta yang tidak ada."""

RECALL_CUE = re.compile(
    r"\b(pernah (kita )?(bahas|bicara|diskusi|ngobrol)|kita pernah|sebelumnya kita|waktu itu (kita|kamu)|"
    r"yang (kemarin|lalu) (kita|kamu)|remember when|we (talked|discussed)|last time we|"
    r"earlier (we|you) (said|discussed))\b",
    re.IGNORECASE,
)
SECRET_LIKE = re.compile(
    r"(sk-[a-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|password|kata ?sandi|\b\d{13,19}\b)", re.IGNORECASE
)
STOPWORDS = set(
    "yang dan atau di ke dari ini itu untuk dengan pada adalah kita kamu saya aku apa bagaimana kenapa "
    "pernah bahas tentang soal the and or a an of to in is are was we you i what how why about did".split()
)


class ExternalStore(Protocol):
    async def add(self, user_id: uuid.UUID, content: str, kind: str) -> None: ...
    async def search(self, user_id: uuid.UUID, query: str, k: int) -> list[str]: ...


class HttpMemoryStore:
    """Generic HTTP memory backend.

    POST {url}/memories  {"user_id","content","kind"}
    GET  {url}/search?user_id=&q=&k=  -> {"results":[{"content": "..."}]}
    Bearer token from MEMORY_EXTERNAL_TOKEN. Failures never break a chat.
    """

    def __init__(self, url: str, token: str = "", transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=5, headers=self.headers, transport=self.transport)

    async def add(self, user_id: uuid.UUID, content: str, kind: str) -> None:
        try:
            async with self._client() as client:
                await client.post(
                    f"{self.url}/memories", json={"user_id": str(user_id), "content": content, "kind": kind}
                )
        except httpx.HTTPError:
            log.warning("external memory add failed", extra={"user_id": str(user_id)})

    async def search(self, user_id: uuid.UUID, query: str, k: int) -> list[str]:
        try:
            async with self._client() as client:
                resp = await client.get(
                    f"{self.url}/search", params={"user_id": str(user_id), "q": query, "k": k}
                )
                resp.raise_for_status()
                return [str(r["content"]) for r in resp.json().get("results", [])][:k]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            log.warning("external memory search failed", extra={"user_id": str(user_id)})
            return []


def settings_of(user: User) -> dict[str, bool]:
    s = user.settings or {}
    return {
        "enabled": bool(s.get("memory_enabled", True)),
        "auto": bool(s.get("memory_auto_extract", True)),
        "review": bool(s.get("memory_review", False)),
    }


async def relevant(
    session: AsyncSession, user_id: uuid.UUID, prompt: str, k: int = MAX_INJECTED
) -> list[Memory]:
    """Pinned memories always, then the most similar ones; bumps their usage stats."""
    rows = (
        await session.scalars(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.status == MemoryStatus.active)
            .order_by(Memory.pinned.desc(), Memory.use_count.desc())
            .limit(MAX_MEMORIES_PER_USER)
        )
    ).all()
    if not rows:
        return []
    query = embed(prompt)
    pinned = [m for m in rows if m.pinned]
    scored = sorted(
        ((cosine(query, m.embedding), m) for m in rows if not m.pinned), key=lambda x: x[0], reverse=True
    )
    picked = pinned[:k] + [m for score, m in scored if score >= MIN_RELEVANCE][: max(0, k - len(pinned))]
    now = utcnow()
    for m in picked:
        m.use_count += 1
        m.last_used_at = now
    return picked


def keywords(text: str, limit: int = 4) -> list[str]:
    words = [w for w in re.findall(r"\w{4,}", text.lower()) if w not in STOPWORDS]
    seen: list[str] = []
    for w in sorted(words, key=len, reverse=True):
        if w not in seen:
            seen.append(w)
    return seen[:limit]


@dataclass
class HistoryHit:
    chat_id: uuid.UUID
    chat_title: str
    message_id: uuid.UUID
    role: str
    snippet: str
    created_at: Any


def _snippet(content: str, terms: list[str], width: int = 220) -> str:
    low = content.lower()
    pos = min((low.find(t) for t in terms if t in low), default=0)
    start = max(0, pos - width // 3)
    text = content[start : start + width].replace("\n", " ")
    return ("…" if start else "") + text + ("…" if start + width < len(content) else "")


async def search_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    limit: int = 20,
    exclude_chat_id: uuid.UUID | None = None,
) -> list[HistoryHit]:
    """Keyword search over all of the user's past messages (newest first)."""
    terms = keywords(query) or [query.strip().lower()]
    terms = [t for t in terms if t]
    if not terms:
        return []
    stmt = (
        select(Message, Chat.title)
        .join(Chat, Chat.id == Message.chat_id)
        .where(Chat.user_id == user_id)
        .where(or_(*[func.lower(Message.content).contains(t) for t in terms]))
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    if exclude_chat_id is not None:
        stmt = stmt.where(Message.chat_id != exclude_chat_id)
    rows = (await session.execute(stmt)).all()
    return [
        HistoryHit(m.chat_id, title, m.id, m.role, _snippet(m.content, terms), m.created_at)
        for m, title in rows
    ]


def context_block(
    profile: str, memories: list[Memory], external: list[str], history: list[HistoryHit]
) -> str:
    parts: list[str] = []
    if profile:
        parts.append(f"Profil pengguna:\n{profile}")
    lines = [f"- {m.content}" for m in memories] + [f"- {e}" for e in external]
    if lines:
        parts.append("Yang kamu ingat tentang pengguna (dari percakapan sebelumnya):\n" + "\n".join(lines))
    if history:
        hist = "\n".join(f'- [{h.chat_title}] {h.role}: "{h.snippet}"' for h in history)
        parts.append("Cuplikan percakapan lama yang relevan dengan pertanyaan ini:\n" + hist)
    if not parts:
        return ""
    return (
        "\n\n".join(parts) + "\n\nGunakan informasi ini hanya bila relevan, "
        "dan jangan menyebut bahwa kamu membaca catatan memori."
    )


def wants_recall(prompt: str) -> bool:
    return bool(RECALL_CUE.search(prompt))


def parse_extraction(text: str) -> list[dict[str, str]]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    items = data.get("memories") if isinstance(data, dict) else None
    out: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        kind = str(item.get("kind", "fact"))
        if not content or len(content) > 300 or SECRET_LIKE.search(content):
            continue
        out.append({"kind": kind if kind in MemoryKind.__members__ else "fact", "content": content[:300]})
    return out[:10]


def extraction_request(user_text: str, answer: str) -> list[dict[str, str]]:
    convo = f"PENGGUNA: {user_text[:4000]}\n\nASISTEN: {answer[:2000]}"
    return [{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": convo}]


def profile_request(memories: list[Memory]) -> list[dict[str, str]]:
    listing = "\n".join(f"- ({m.kind}) {m.content}" for m in memories)
    return [{"role": "system", "content": PROFILE_PROMPT}, {"role": "user", "content": listing}]


async def remember(
    session: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    kind: str,
    source: str,
    status: str = MemoryStatus.active,
    chat_id: uuid.UUID | None = None,
    actor: str = "user",
) -> tuple[Memory, bool]:
    """Insert, or refresh a near-duplicate. Returns (memory, created)."""
    vector = embed(content)
    existing = (
        await session.scalars(
            select(Memory).where(Memory.user_id == user_id, Memory.status != MemoryStatus.rejected)
        )
    ).all()
    for m in existing:
        if cosine(vector, m.embedding) >= DUPLICATE_SIMILARITY:
            if m.content != content:
                m.content, m.embedding, m.updated_at = content, vector, utcnow()
                audit.record(session, user_id, actor, "memory.update", str(m.id), content=content[:120])
            return m, False
    memory = Memory(
        user_id=user_id,
        kind=kind,
        content=content,
        source=source,
        status=status,
        embedding=vector,
        source_chat_id=chat_id,
    )
    session.add(memory)
    await session.flush()
    audit.record(
        session, user_id, actor, "memory.create", str(memory.id), content=content[:120], status=status
    )
    return memory, True
