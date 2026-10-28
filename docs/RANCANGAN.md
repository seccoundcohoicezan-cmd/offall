# Rancangan Web: AI Gateway Multi-Provider

**Satu chat, banyak AI. Pilih model sendiri, hemat token, dan job tetap jalan saat kamu offline.**

---

## Daftar Isi

1. [Konsep Utama](#1-konsep-utama)
2. [Fitur Utama](#2-fitur-utama)
3. [Arsitektur Sistem](#3-arsitektur-sistem)
4. [Modul Detail](#4-modul-detail)
5. [Halaman Web](#5-halaman-web)
6. [Desain Database](#6-desain-database)
7. [Endpoint API](#7-endpoint-api)
8. [Logika Worker](#8-logika-worker-job-tetap-jalan-saat-offline)
9. [Skeleton Kode Token Saver & Fallback](#9-skeleton-kode-token-saver--fallback)
10. [Frontend](#10-hal-penting-di-frontend)
11. [Keamanan](#11-keamanan)
12. [Tech Stack](#12-tech-stack)
13. [Struktur Folder](#13-struktur-folder)
14. [Roadmap](#14-roadmap-pembuatan)
15. [Deploy](#15-deploy-minimal)

---

## 1. Konsep Utama

Satu chat/endpoint yang di belakangnya terhubung ke banyak AI (Claude, GPT, Gemini, Groq, Mistral, OpenRouter, Ollama lokal). Kamu cukup **tambah API key**, lalu sistem otomatis:

- memilih AI yang sesuai (atau kamu pilih manual),
- menghemat token dengan menghapus kata/kalimat dobel,
- pindah ke AI lain jika kuota habis atau error,
- tetap memproses perintah walau browser ditutup atau kamu offline.

> **Catatan penting:** Gunakan API key milik sendiri dan free tier sesuai aturan tiap provider. Membuat banyak akun palsu untuk menghindari batas gratis melanggar ToS dan bisa membuat akun diblokir. Menggabungkan beberapa provider berbeda (Gemini + Groq + OpenRouter + Claude, dst.) itu aman dan legal.

---

## 2. Fitur Utama

### A. Pilih Model

- Dropdown di chat: `Auto (hemat)`, `Claude Sonnet`, `GPT-4o`, `Gemini Flash`, `Llama (Groq)`, dst.
- Daftar model diambil dari provider yang sudah di-add key-nya. Jika key dihapus, modelnya hilang dari pilihan.
- Mode **Auto** memakai router: tugas ringan ke model murah, tugas sulit ke model kuat, fallback jika error.
- Pilihan model bisa diatur **per chat** dan **diganti di tengah chat** (history tetap ikut).
- Opsional: **Mode Banding**, kirim ke 2-3 model sekaligus lalu tampilkan berdampingan.

### B. Tetap Jalan Saat Offline

Proses AI **tidak boleh terikat koneksi browser**.

```
Browser kirim pesan → API simpan job ke DB/queue → langsung balas "job_id"
                                    ↓
                        Worker (proses terpisah) menjalankan AI
                                    ↓
                  Hasil disimpan ke DB (ditulis bertahap)
                                    ↓
Browser dibuka lagi kapan saja → ambil hasil dari DB / sambung stream
```

Jika tab ditutup, HP mati, atau internet putus, worker tetap berjalan di server dan hasil menunggu di riwayat chat.

### C. Hemat Token

Pembersihan teks, dedupe, ringkasan history otomatis, dan semantic cache (detail di bagian 4C).

---

## 3. Arsitektur Sistem

```
┌──────────────────────────────────────────┐
│  FRONTEND (Next.js + Tailwind)           │
│  Chat · Model Picker · Provider · Jobs   │
└───────────────┬──────────────────────────┘
                │ REST + SSE/WebSocket
┌───────────────▼──────────────────────────┐
│  BACKEND API (FastAPI, OpenAI-compatible)│
│  Auth · Chat · Provider · Usage          │
└───────┬───────────────────────┬──────────┘
        │ enqueue job           │ read/write
┌───────▼────────┐      ┌───────▼──────────┐
│ Redis (queue + │      │ PostgreSQL       │
│ pub/sub+cache) │      │ (chat, job, key) │
└───────┬────────┘      └──────────────────┘
        │ ambil job
┌───────▼───────────────────────────────────┐
│ WORKER (Celery / ARQ / RQ)                │
│ Token Saver → Router → LiteLLM → Provider │
│ Simpan hasil bertahap + update status     │
└───────┬───────────────────────────────────┘
        │ selesai
┌───────▼────────────────────┐
│ Notifikasi: Web Push /     │
│ Telegram / Email           │
└────────────────────────────┘
```

Lapisan di dalam worker:

```
1. TOKEN SAVER   → cleaner, dedupe, rolling summary, semantic cache
2. ROUTER        → pilih model, fallback otomatis, load balance key
3. ADAPTERS      → Anthropic | OpenAI | Gemini | Groq | OpenRouter | Mistral | Ollama
4. KEY VAULT     → enkripsi key, usage tracker, logs
```

---

## 4. Modul Detail

### A. Key Manager (tinggal add API)

- Form **Add Provider**: pilih provider → tempel API key → tes koneksi → aktif.
- Key dienkripsi (AES-GCM), tidak disimpan plain text.
- Tiap key punya: status, sisa kuota, rate limit, prioritas, model yang diizinkan.

### B. Router Cerdas

| Strategi | Contoh |
|---|---|
| By tugas | coding → Claude, chat ringan → Gemini Flash/Groq, ringkas → model murah |
| By biaya | utamakan gratis, baru berbayar |
| Fallback | Claude 429 → Gemini → Groq → Ollama lokal |
| Load balance | bagi beban antar key sah milik sendiri |
| Mode Banding | kirim ke 2-3 AI, tampilkan atau gabungkan jawaban |

### B2. Key Pool & Auto-Rotasi (Banyak Akun per Provider)

Satu provider (misalnya Claude) bisa punya **banyak API key/akun**. Saat kamu memilih Claude, sistem memakai Akun A sampai limit, lalu **otomatis pindah ke Akun B, C, dst.** sampai semua benar-benar habis. Baru setelah itu fallback ke provider lain (jika diizinkan).

> **Syarat penting:** pakai key dari akun/organisasi **milik sendiri atau yang pemiliknya memberi izin** (misalnya tim, kantor, teman yang setuju). Membuat akun massal untuk menghindari batas gratis melanggar ToS dan berisiko semua akun diblokir. Perlu diingat juga: chat gratis di claude.ai **tidak punya API**, jadi yang dirotasi adalah **API key** (berbasis kredit/billing per akun).

**Status tiap key**

| Status | Arti | Aksi |
|---|---|---|
| `active` | siap dipakai | dipilih router |
| `cooling_down` | kena 429 (rate limit) | skip sampai waktu `retry-after` lewat, lalu aktif lagi otomatis |
| `exhausted` | kredit/kuota habis (402/billing/quota) | skip sampai reset (harian/bulanan) atau diisi ulang |
| `invalid` | 401/403, key salah atau dicabut | nonaktif permanen + notifikasi ke user |
| `disabled` | dimatikan manual | tidak dipakai |

**Strategi pemilihan key**

| Strategi | Cara kerja |
|---|---|
| **Fill-first (default sesuai permintaan)** | pakai A terus sampai limit, lalu B, lalu C |
| Round-robin | bergiliran supaya beban merata |
| Least-used | pilih key dengan pemakaian paling sedikit |

**Alur failover**

```
Request → pilih key aktif berprioritas tertinggi (Akun A)
        → sukses? selesai
        → 429  → tandai A: cooling_down (sesuai retry-after) → coba Akun B (request yang sama)
        → 402/quota → tandai A: exhausted → coba Akun B
        → 401  → tandai A: invalid → coba Akun B
        → ... lanjut sampai Akun terakhir
        → semua key Claude habis → (opsional) fallback ke provider lain / job status "waiting_quota"
```

**Perilaku saat job berjalan**
- Jika key kena limit **sebelum ada output**: ulang request yang sama dengan key berikutnya (pengguna tidak sadar).
- Jika terputus **di tengah streaming**: simpan `partial_output`, lalu lanjutkan dengan key berikutnya (kirim partial sebagai prefix dan minta melanjutkan).
- Jika **semua key habis** dan fallback provider dimatikan: job jadi `waiting_quota`, lalu otomatis jalan lagi saat ada key yang pulih. Cocok dengan fitur tetap jalan saat offline.
- Penggunaan tiap key tetap dicatat di `usage_logs` agar terlihat Akun A/B/C sudah terpakai berapa.

**Kode inti rotasi**

```python
import time
from litellm import acompletion
from litellm.exceptions import RateLimitError, AuthenticationError, APIConnectionError

async def call_with_key_pool(provider, model, messages, **kw):
    keys = key_pool.available(provider)          # status active & belum cooldown, urut prioritas
    if not keys:
        raise NoKeyAvailable(provider)

    for key in keys:
        try:
            resp = await acompletion(model=model, messages=messages,
                                     api_key=key.secret, **kw)
            key_pool.mark_ok(key.id)
            return resp
        except RateLimitError as e:
            wait = getattr(e, "retry_after", None) or 60
            key_pool.mark(key.id, "cooling_down", until=time.time() + wait)
        except AuthenticationError:
            key_pool.mark(key.id, "invalid")
        except APIConnectionError:
            continue                              # error jaringan, coba key lain
        except Exception as e:
            if "credit" in str(e).lower() or "quota" in str(e).lower():
                key_pool.mark(key.id, "exhausted", until=next_reset())
            else:
                raise
    raise AllKeysExhausted(provider)              # router lanjut ke provider lain / waiting_quota
```

> Alternatif tanpa menulis sendiri: **LiteLLM Router** mendukung beberapa deployment dengan `model_name` yang sama (tiap deployment beda `api_key`), plus cooldown dan retry otomatis.

**UI tambahan di halaman Providers**
- Grup per provider: Claude → daftar Akun A, B, C dengan badge status, sisa kuota, pemakaian hari ini, dan waktu pulih.
- Tombol: tambah key, tes, aktif/nonaktif, geser urutan prioritas, pilih strategi (fill-first / round-robin / least-used).
- Banner peringatan saat tersisa 1 key aktif atau semua key habis.

### C. Token Saver (inti penghematan)

1. **Normalisasi:** hapus spasi/enter berlebih, basa-basi, kalimat identik berulang.
2. **Dedupe history:** pesan sama persis atau sangat mirip dibuang (hash + similarity).
3. **Rolling summary:** setelah N pesan, history lama diringkas jadi 1 blok kecil oleh model murah.
4. **Sliding window:** kirim hanya K pesan terakhir + ringkasan.
5. **Prompt caching:** pakai fitur caching Anthropic/OpenAI untuk system prompt panjang.
6. **Semantic cache:** pertanyaan mirip → ambil jawaban lama (embedding + Redis/SQLite).
7. **Batas output:** set `max_tokens` dan instruksi "jawab ringkas" sesuai mode.
8. **Opsional:** LLMLingua untuk kompresi prompt panjang.

> ⚠️ Jangan dedupe isi code block, angka, atau data penting, karena pengulangan di situ bisa bermakna.

### D. Agent Layer (tahap lanjut)

- Tools: web search, baca file, kalkulator, eksekusi kode.
- Orkestrasi: model murah sebagai planner/router, model kuat hanya untuk tugas sulit.

### E. Dashboard

- Token terpakai per provider, estimasi biaya, hit cache, persen penghematan.

---

## 5. Halaman Web

| Halaman | Fungsi |
|---|---|
| **Login / Register** | Akun pengguna |
| **Chat** | Daftar chat di sidebar, area pesan, dropdown model, tombol Stop/Retry |
| **Jobs / Riwayat** | Status tugas: `queued`, `running`, `waiting_quota`, `done`, `failed`, `cancelled` |
| **Providers** | Add API key, tes koneksi, aktif/nonaktif, prioritas, sisa kuota |
| **Models** | Daftar model tersedia, favorit, urutan fallback |
| **Usage** | Token per provider, biaya, hit cache, persen penghematan |
| **Settings** | Mode hemat (agresif/normal/off), max token, notifikasi, system prompt default |

---

## 6. Desain Database

```
users(id, email, password_hash, created_at)

providers(id, user_id, name, base_url, rotation_strategy, created_at)

provider_keys(id, provider_id, label, api_key_encrypted,
              status, priority, cooldown_until, reset_at,
              tokens_used_today, last_error, created_at)

models(id, provider_id, model_name, display_name,
       is_enabled, cost_in, cost_out, context_window)

chats(id, user_id, title, default_model, mode, created_at)

messages(id, chat_id, role, content, model_used,
         tokens_in, tokens_out, created_at)

jobs(id, chat_id, user_id, model_requested, model_used,
     status, partial_output, error, attempts,
     created_at, started_at, finished_at)

usage_logs(id, user_id, provider_id, provider_key_id, model, tokens_in,
           tokens_out, tokens_saved, cost, cached, created_at)

cache_entries(id, prompt_hash, embedding, response, hit_count)
```

---

## 7. Endpoint API

```
POST   /auth/register | /auth/login

GET    /models                      → daftar model dari provider aktif
POST   /providers                   → add API key (dienkripsi)
POST   /providers/{id}/test         → tes koneksi
PATCH  /providers/{id}              → aktif/nonaktif, prioritas

POST   /chats                       → buat chat
POST   /chats/{id}/messages         → kirim pesan {content, model|"auto"}
                                      → return {job_id} langsung
GET    /jobs/{id}                   → status + hasil sementara/akhir
GET    /jobs/{id}/stream            → SSE, bisa disambung ulang
POST   /jobs/{id}/cancel

GET    /usage/summary
```

---

## 8. Logika Worker (Job Tetap Jalan Saat Offline)

```python
async def run_job(job_id):
    job = db.get_job(job_id)
    db.update(job_id, status="running")

    messages = token_saver(db.get_history(job.chat_id))   # clean + dedupe + summary
    models = [job.model_requested] if job.model_requested != "auto" \
             else router.pick(messages)                    # urutan fallback

    for model in models:
        try:
            async for chunk in litellm.acompletion(
                    model=model, messages=messages,
                    max_tokens=800, stream=True):
                db.append_partial(job_id, chunk)           # simpan bertahap
                redis.publish(f"job:{job_id}", chunk)      # untuk live stream
            db.finish(job_id, model_used=model)
            notify_user(job.user_id, job_id)               # push / Telegram
            return
        except (RateLimit, Timeout, ServerError):
            continue                                       # fallback ke model berikut
    db.update(job_id, status="failed")
```

**Catatan:** jika user memilih model manual lalu gagal, tanyakan dulu apakah boleh fallback, atau jadikan opsi di Settings ("izinkan fallback otomatis").

---

## 9. Skeleton Kode Token Saver & Fallback

```python
import re, hashlib
from litellm import completion

def clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def dedupe(messages):
    seen, out = set(), []
    for m in messages:
        h = hashlib.md5((m["role"] + clean(m["content"])).encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append({**m, "content": clean(m["content"])})
    return out

def trim(messages, keep_last=8):
    return messages[-keep_last:]  # + rolling summary di versi lengkap

FALLBACK = [
    "anthropic/claude-sonnet-4-5",
    "gemini/gemini-2.0-flash",
    "groq/llama-3.3-70b-versatile",
    "ollama/llama3",
]

def chat(messages):
    messages = trim(dedupe(messages))
    for model in FALLBACK:
        try:
            return completion(model=model, messages=messages, max_tokens=800)
        except Exception as e:
            print(f"{model} gagal: {e}")
    raise RuntimeError("Semua provider gagal")
```

---

## 10. Hal Penting di Frontend

- Saat halaman dibuka ulang, cek `jobs` yang masih `running`, sambung SSE lagi, dan tampilkan `partial_output` yang sudah ada.
- Tampilkan badge di tiap jawaban: model yang dipakai dan token yang dihemat.
- Simpan pilihan model terakhir per chat.
- Dukung PWA agar bisa di-install di HP dan menerima Web Push.

---

## 11. Keamanan

- API key dienkripsi (AES-GCM, kunci master di environment variable), tidak pernah dikirim balik ke frontend.
- Rate limit per user agar key tidak habis disalahgunakan.
- Batas job paralel per user dan timeout per job.
- HTTPS wajib, password pakai argon2/bcrypt, JWT dengan refresh token.
- Jangan simpan atau log isi chat sensitif tanpa sepengetahuan user.

---

## 12. Tech Stack

| Bagian | Pilihan |
|---|---|
| Backend | Python + FastAPI |
| Adapter & fallback | **LiteLLM** (100+ provider) |
| Queue / cache | Redis (atau SQLite untuk awal) |
| Database | PostgreSQL / SQLite |
| Worker | Celery / ARQ / RQ |
| UI | Next.js + Tailwind, atau Open WebUI / LibreChat diarahkan ke gateway |
| Deploy | Docker Compose di VPS kecil |

---

## 13. Struktur Folder

```
ai-gateway/
├─ backend/
│  ├─ app/
│  │  ├─ api/        (auth, chats, providers, jobs, usage)
│  │  ├─ core/       (config, security, encryption)
│  │  ├─ services/   (token_saver.py, router.py, llm.py, notify.py)
│  │  ├─ models/     (SQLAlchemy)
│  │  └─ worker.py
│  └─ Dockerfile
├─ frontend/
│  ├─ app/           (chat, jobs, providers, usage, settings)
│  ├─ components/    (ModelPicker, ChatBox, JobStatus)
│  └─ Dockerfile
└─ docker-compose.yml   (api, worker, redis, postgres, frontend)
```

---

## 14. Roadmap Pembuatan

| Tahap | Isi | Estimasi |
|---|---|---|
| **1** | Backend + LiteLLM, 3 provider, endpoint chat sinkron | 1 minggu |
| **2** | Queue + worker + tabel `jobs` (tetap jalan saat offline) | 1 minggu |
| **3** | Frontend chat + model picker + stream sambung ulang | 1-2 minggu |
| **4** | Halaman Providers (add API key terenkripsi) + Usage | 1 minggu |
| **4b** | Key Pool: banyak akun per provider + auto-rotasi + cooldown | 1 minggu |
| **5** | Token Saver lengkap (summary, semantic cache), mode Auto router | 1-2 minggu |
| **6** | Notifikasi, PWA, multi-user, deploy VPS + HTTPS | 1 minggu |

---

## 15. Deploy Minimal

VPS kecil (2 vCPU / 2-4 GB RAM) cukup untuk mulai. Jalankan `docker compose up -d` untuk api, worker, redis, postgres, dan frontend, ditambah Caddy atau Nginx untuk HTTPS.

---

## Langkah Berikutnya

- [ ] Kode MVP lengkap (FastAPI + worker + endpoint)
- [ ] Komponen UI Model Picker + halaman chat
- [ ] `docker-compose.yml` siap pakai
- [ ] Desain key vault terenkripsi
