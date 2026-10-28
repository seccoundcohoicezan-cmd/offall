# AGENT_INSTRUCTIONS.md

Instruksi untuk AI coding agent (Claude Code, Cursor, Codex, dsb.) yang membangun project **AI Gateway Multi-Provider** dari nol sampai bisa dideploy.

Letakkan file ini di root repo. Jika agent mendukung file konfigurasi sendiri, salin isinya ke `CLAUDE.md` atau `AGENTS.md`.

---

## 0. Peran & Cara Kerja

Kamu adalah **senior full-stack engineer** yang membangun project ini secara bertahap dan mandiri.

Aturan kerja:

1. **Kerjakan per fase** (bagian 9). Selesaikan satu fase sampai semua *acceptance criteria*-nya lulus sebelum lanjut.
2. **Rencana dulu, kode kemudian.** Di awal tiap fase, tulis rencana singkat (file yang akan dibuat/diubah) lalu eksekusi.
3. **Commit kecil dan sering**, pesan commit memakai Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
4. **Jalankan tes, lint, dan build sendiri** setelah tiap perubahan penting. Jangan klaim "selesai" tanpa bukti perintahnya berhasil.
5. **Jangan mengarang.** Jika dokumentasi library atau versi API tidak pasti, baca dokumentasi resmi atau cek versi yang terpasang. Jangan menebak nama fungsi atau parameter.
6. **Tanya hanya jika benar-benar buntu** atau keputusan berdampak besar (biaya, keamanan, hapus data). Untuk hal kecil, ambil asumsi yang masuk akal dan catat di `docs/DECISIONS.md`.
7. **Jangan menambah fitur di luar spesifikasi** tanpa persetujuan. Jangan melakukan refactor besar yang tidak diminta.
8. Setiap akhir fase, tulis ringkasan: apa yang selesai, cara menjalankan, apa yang belum, risiko yang diketahui.

---

## 1. Tujuan Produk

Web app tempat user menambahkan banyak API key dari banyak provider AI, lalu memakai semuanya lewat **satu chat**.

Fitur inti:

- **Pilih model** lewat dropdown (`Auto` atau model spesifik), bisa diganti di tengah chat.
- **Multi-provider**: Anthropic (Claude), OpenAI, Google Gemini, Groq, OpenRouter, Mistral, Ollama (lokal).
- **Key pool + auto-rotasi**: satu provider punya banyak key. Saat key A kena limit, otomatis pindah ke key B, dan seterusnya sampai semua key habis.
- **Job tetap jalan saat offline**: proses AI berjalan di worker server, tidak terikat koneksi browser. User bisa menutup tab lalu membuka lagi dan hasilnya ada.
- **Token Saver**: membersihkan teks, membuang pengulangan, meringkas history, semantic cache, sehingga token lebih hemat.
- **Dashboard pemakaian**: token, biaya, hit cache, persen penghematan per provider dan per key.
- **Notifikasi** saat job selesai (Web Push dan/atau Telegram).

---

## 2. Batasan Kepatuhan & Etika (WAJIB)

- Sistem ini hanya boleh memakai **API key milik user sendiri atau key yang pemiliknya memberi izin**. Jangan membuat fitur untuk membuat akun massal, mengakali verifikasi, atau mengakali batas gratis provider.
- Jangan mem-bypass rate limit dengan cara selain rotasi key sah. Hormati header `retry-after` dan kebijakan tiap provider.
- Jangan membuat scraping atau otomasi terhadap antarmuka chat web (claude.ai, chatgpt.com, dst.). Hanya gunakan **API resmi**.
- Jangan pernah menulis API key asli, secret, atau data pribadi ke kode, log, test fixture, atau commit.
- Tampilkan catatan kepatuhan singkat di halaman Providers: "Gunakan hanya key milik sendiri atau yang diizinkan pemiliknya."

---

## 3. Tech Stack (jangan diganti tanpa alasan kuat)

| Lapisan | Teknologi |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| LLM adapter | **LiteLLM** |
| Worker / queue | **ARQ** (Redis) atau Celery, pilih satu dan konsisten |
| Database | PostgreSQL (SQLite hanya untuk tes lokal cepat) |
| Cache / pubsub | Redis |
| Frontend | Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui |
| State / data | TanStack Query, Zustand (ringan) |
| Streaming | Server-Sent Events (SSE) |
| Auth | JWT access + refresh token, password hash argon2 |
| Enkripsi key | AES-256-GCM (library `cryptography`) |
| Tes | pytest + pytest-asyncio + httpx (backend), Vitest + Playwright (frontend) |
| Lint/format | ruff + mypy (backend), ESLint + Prettier (frontend) |
| Kontainer | Docker, Docker Compose |
| CI/CD | GitHub Actions |

Fix versi di `pyproject.toml` dan `package.json`. Pakai versi stabil terbaru yang kompatibel, jangan versi beta.

---

## 4. Struktur Repo

```
ai-gateway/
├─ AGENT_INSTRUCTIONS.md
├─ README.md
├─ docker-compose.yml
├─ .env.example
├─ .gitignore
├─ .github/workflows/ci.yml
├─ docs/
│  ├─ DECISIONS.md
│  ├─ ARCHITECTURE.md
│  └─ API.md
├─ backend/
│  ├─ pyproject.toml
│  ├─ Dockerfile
│  ├─ alembic.ini
│  ├─ migrations/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/            (auth, chats, jobs, providers, models, usage, health)
│  │  ├─ core/           (config, security, encryption, deps, logging)
│  │  ├─ db/             (session, base)
│  │  ├─ models/         (SQLAlchemy)
│  │  ├─ schemas/        (Pydantic)
│  │  ├─ services/
│  │  │  ├─ token_saver.py
│  │  │  ├─ router.py
│  │  │  ├─ key_pool.py
│  │  │  ├─ llm.py
│  │  │  ├─ semantic_cache.py
│  │  │  ├─ summarizer.py
│  │  │  └─ notify.py
│  │  └─ worker.py
│  └─ tests/
└─ frontend/
   ├─ package.json
   ├─ Dockerfile
   ├─ app/               (login, chat, jobs, providers, models, usage, settings)
   ├─ components/        (ModelPicker, ChatBox, MessageBubble, JobStatus, KeyPoolCard, UsageChart)
   ├─ lib/               (api client, sse, auth)
   └─ tests/
```

---

## 5. Model Data (PostgreSQL)

```
users(id, email, password_hash, role, created_at)

providers(id, user_id, name, base_url, rotation_strategy, created_at)

provider_keys(id, provider_id, label, api_key_encrypted, status, priority,
              cooldown_until, reset_at, tokens_used_today, last_error, created_at)
   status: active | cooling_down | exhausted | invalid | disabled

models(id, provider_id, model_name, display_name, is_enabled,
       cost_in, cost_out, context_window)

chats(id, user_id, title, default_model, mode, created_at)

messages(id, chat_id, role, content, model_used,
         tokens_in, tokens_out, created_at)

jobs(id, chat_id, user_id, model_requested, model_used, status,
     partial_output, error, attempts, created_at, started_at, finished_at)
   status: queued | running | waiting_quota | done | failed | cancelled

usage_logs(id, user_id, provider_id, provider_key_id, model, tokens_in,
           tokens_out, tokens_saved, cost, cached, created_at)

cache_entries(id, user_id, prompt_hash, embedding, response, hit_count, created_at)
```

Semua tabel punya index yang masuk akal (`user_id`, `chat_id`, `status`, `created_at`). Gunakan migrasi Alembic, jangan `create_all` di produksi.

---

## 6. Kontrak API

Semua endpoint di bawah prefix `/api/v1`, kecuali dinyatakan lain. Semua selain auth butuh `Authorization: Bearer <token>`.

```
POST   /auth/register            (bisa dimatikan lewat env REGISTRATION_OPEN=false)
POST   /auth/login
POST   /auth/refresh

GET    /models                   → model dari provider yang punya minimal 1 key aktif
POST   /providers                → buat provider
GET    /providers                → daftar + ringkasan status key
POST   /providers/{id}/keys      → tambah key (terenkripsi, tidak pernah dikembalikan utuh)
PATCH  /providers/{id}/keys/{kid}→ aktif/nonaktif, prioritas, label
DELETE /providers/{id}/keys/{kid}
POST   /providers/{id}/keys/{kid}/test → tes koneksi
PATCH  /providers/{id}           → rotation_strategy: fill_first | round_robin | least_used

POST   /chats
GET    /chats
GET    /chats/{id}/messages
POST   /chats/{id}/messages      → body {content, model: "auto" | "<provider/model>"}
                                   respons langsung {job_id}, TIDAK menunggu AI selesai
GET    /jobs/{id}                → status + partial_output/hasil
GET    /jobs/{id}/stream         → SSE, mendukung sambung ulang (Last-Event-ID)
POST   /jobs/{id}/cancel

GET    /usage/summary            → per provider, per key, per hari
GET    /health                   → tanpa auth, untuk uptime monitor
```

Aturan API:

- Respons error seragam: `{"error": {"code": "...", "message": "..."}}`.
- Validasi input dengan Pydantic. Batasi panjang pesan dan jumlah chat per user.
- API key hanya ditampilkan sebagai `sk-...abcd` (4 karakter terakhir). Tidak pernah dikirim utuh ke frontend.
- Dokumentasi OpenAPI otomatis harus akurat. Ekspor ringkasannya ke `docs/API.md`.

---

## 7. Spesifikasi Modul Backend

### 7.1 Alur pesan (inti produk)

```
POST /chats/{id}/messages
  → simpan pesan user
  → buat job (status=queued)
  → enqueue ke Redis
  → return {job_id} segera

Worker:
  → status=running
  → ambil history → token_saver
  → tentukan daftar model (manual atau router.auto)
  → untuk tiap model: call_with_key_pool(...)
  → streaming: tulis partial_output ke DB bertahap + publish ke Redis channel job:{id}
  → selesai: simpan message assistant, usage_log, status=done, kirim notifikasi
```

Job **harus** tetap berjalan jika client terputus. SSE endpoint hanya membaca/menyambung dari Redis + `partial_output`, bukan menjalankan AI.

### 7.2 Key Pool & Auto-Rotasi (`key_pool.py`)

- Saat user memilih provider (misal Claude), ambil key `active` yang `cooldown_until` sudah lewat, urut sesuai strategi.
- **fill_first** (default): pakai key prioritas tertinggi sampai gagal karena limit, lalu key berikutnya.
- **round_robin** dan **least_used** sebagai opsi.
- Penanganan error:
  - `429` → `cooling_down` sampai `retry-after` (default 60 detik), coba key berikutnya.
  - `402`/kredit habis/quota → `exhausted` sampai `reset_at`, coba key berikutnya.
  - `401/403` → `invalid` permanen, kirim notifikasi ke user.
  - Error jaringan/5xx → coba key berikutnya, jangan tandai rusak pada kegagalan pertama.
- Jika limit terjadi **sebelum ada output**: ulangi request dengan key berikutnya, tanpa terlihat user.
- Jika terputus **di tengah streaming**: simpan `partial_output`, lanjutkan dengan key berikutnya (kirim partial sebagai konteks dan minta melanjutkan).
- Jika semua key provider habis: ikuti pengaturan user, yaitu fallback ke provider lain **atau** job menjadi `waiting_quota` lalu otomatis dijalankan ulang saat ada key pulih (scheduler periodik).
- Operasi pemilihan dan penandaan status key harus **atomic / aman konkurensi** (gunakan transaksi atau lock Redis) agar dua worker tidak memakai key yang sama secara bentrok.
- Catat setiap pemakaian ke `usage_logs` dengan `provider_key_id`.

### 7.3 Router (`router.py`)

- `model="auto"`: klasifikasikan tugas sederhana (heuristik dulu, bukan LLM): coding, tugas panjang/kompleks → model kuat; chat ringan, ringkasan → model murah/gratis.
- Urutan fallback bisa diatur user di halaman Models.
- Jika user memilih model manual dan gagal, fallback ke model lain **hanya** jika setting `allow_fallback=true`.

### 7.4 Token Saver (`token_saver.py`)

Urutan pemrosesan:

1. **Normalisasi**: rapikan spasi, hapus baris kosong berlebih, buang sapaan basa-basi yang berulang.
2. **Dedupe**: buang pesan identik atau sangat mirip dalam history (hash + similarity).
3. **Lindungi** isi code block, angka, URL, dan data terstruktur. Jangan pernah diubah atau di-dedupe.
4. **Sliding window**: kirim K pesan terakhir.
5. **Rolling summary**: setelah N pesan, ringkas bagian lama dengan model murah, simpan ringkasan agar tidak diulang.
6. **Prompt caching**: aktifkan fitur caching provider jika tersedia untuk system prompt panjang.
7. **Semantic cache**: embedding + cosine similarity di atas ambang (default 0.95). Hit → kembalikan jawaban lama. Cache dipisah per user.
8. Catat `tokens_saved` (estimasi sebelum vs sesudah) di `usage_logs`.

Token Saver wajib punya tes unit dengan kasus: teks biasa, code block, tabel, angka, pesan identik, history panjang.

### 7.5 Keamanan

- Enkripsi `api_key_encrypted` dengan AES-256-GCM, kunci dari env `MASTER_ENCRYPTION_KEY`. Simpan nonce bersama ciphertext.
- Password: argon2. JWT access (15 menit) + refresh (7 hari), refresh bisa dicabut.
- Rate limit per user dan per IP (login lebih ketat).
- CORS hanya origin yang diizinkan lewat env.
- Jangan log API key, header Authorization, atau isi chat mentah. Gunakan structured logging dengan redaksi.
- Batasi job paralel per user dan timeout per job.
- Validasi bahwa semua resource (chat, job, provider) milik user yang meminta.

### 7.6 Notifikasi

- Interface `notify(user, event)` dengan implementasi Web Push (VAPID) dan Telegram bot. Aktif sesuai pengaturan user, gagal-kirim tidak boleh menggagalkan job.

---

## 8. Spesifikasi Frontend

Halaman dan perilaku wajib:

| Halaman | Isi |
|---|---|
| `/login`, `/register` | Form auth, tampilkan pesan error jelas |
| `/chat`, `/chat/[id]` | Sidebar daftar chat, area pesan dengan markdown + code highlight, input, **ModelPicker**, tombol Stop/Retry, badge model dipakai dan token dihemat |
| `/jobs` | Daftar job + status + filter |
| `/providers` | Grup per provider, daftar key dengan badge status, sisa kuota, pemakaian hari ini, waktu pulih; tambah/tes/nonaktifkan/urutkan key; pilih strategi rotasi; catatan kepatuhan |
| `/models` | Daftar model, favorit, urutan fallback |
| `/usage` | Grafik token/biaya/cache per hari, per provider, per key |
| `/settings` | Mode hemat (off/normal/agresif), max token, izinkan fallback, notifikasi, system prompt default |

Aturan frontend:

- **Sambung ulang**: saat halaman dibuka, cek job `running` dan sambung SSE lagi, tampilkan `partial_output` yang sudah ada. Ini yang membuat fitur "tetap jalan saat offline" terasa.
- Pilihan model tersimpan per chat. Ganti model di tengah chat tidak menghapus history.
- Semua state loading, kosong, dan error harus ada (skeleton, empty state, toast).
- Responsif (mobile-first), mendukung dark mode, aksesibel (label, fokus keyboard, kontras).
- Siapkan **PWA** (manifest + service worker) untuk install di HP dan Web Push.
- Jangan simpan token JWT di `localStorage` jika memungkinkan; pakai cookie `httpOnly` atau praktik yang setara aman.
- Jangan pernah menampilkan API key penuh setelah disimpan.

---

## 9. Fase Pengerjaan & Acceptance Criteria

### Fase 0: Fondasi
- Repo, struktur folder, `docker-compose.yml` (api, worker, postgres, redis, frontend), `.env.example`, CI dasar (lint + test + build).
- **Lulus jika:** `docker compose up` menjalankan semua service, `/health` mengembalikan OK, CI hijau.

### Fase 1: Backend inti
- Auth, model data + migrasi, endpoint providers/keys (enkripsi), endpoint models, chat sinkron sederhana via LiteLLM dengan 1-2 provider.
- **Lulus jika:** tes auth, enkripsi, dan CRUD key lulus; key tidak pernah muncul utuh di respons atau log.

### Fase 2: Queue, Worker, Job
- Alur `POST messages → job → worker → hasil`, `partial_output`, SSE yang bisa disambung, cancel.
- **Lulus jika:** tes integrasi membuktikan job selesai walau client SSE diputus di tengah; sambung ulang menampilkan hasil lengkap.

### Fase 3: Key Pool & Router
- Rotasi key semua status, cooldown, strategi, fallback provider, `waiting_quota` + scheduler.
- **Lulus jika:** tes dengan provider palsu (mock) membuktikan: A kena 429 → pindah ke B; semua habis → `waiting_quota`; key pulih → job lanjut; dua worker paralel tidak bentrok.

### Fase 4: Token Saver
- Cleaner, dedupe, sliding window, rolling summary, semantic cache, pencatatan `tokens_saved`.
- **Lulus jika:** tes unit lulus, code block/angka tidak berubah, dan benchmark sederhana menunjukkan pengurangan token pada history yang berulang.

### Fase 5: Frontend
- Semua halaman bagian 8, ModelPicker, sambung ulang SSE, halaman Providers dengan key pool, Usage.
- **Lulus jika:** tes Playwright untuk alur: login → tambah key → kirim pesan → tutup tab → buka lagi → hasil muncul.

### Fase 6: Notifikasi, PWA, Hardening
- Web Push/Telegram, PWA, rate limit, logging terstruktur, backup/restore doc, uji beban ringan.
- **Lulus jika:** notifikasi terkirim saat job selesai, scan dependensi tanpa isu kritis, tidak ada secret di riwayat git.

### Fase 7: Deploy & Dokumentasi
- GitHub Actions deploy, panduan deploy (Vercel untuk frontend, Railway/Render/VPS untuk backend + worker, Neon/Supabase untuk Postgres, Upstash untuk Redis), README lengkap, `docs/ARCHITECTURE.md`, `docs/API.md`.
- **Lulus jika:** orang baru bisa menjalankan lokal dan deploy hanya dengan mengikuti README.

---

## 10. Standar Kualitas

- **Cakupan tes**: modul kritis (key_pool, token_saver, encryption, auth, worker) minimal 80%.
- **Tipe**: seluruh kode backend lulus `mypy`, frontend lulus `tsc --noEmit` tanpa `any` yang tidak perlu.
- **Lint bersih**: `ruff`, `eslint` tanpa error.
- **Fungsi kecil dan jelas**, nama deskriptif, komentar hanya untuk "kenapa", bukan "apa".
- **Idempotensi**: enqueue job dan retry tidak boleh menggandakan pesan atau tagihan.
- **Observability**: log terstruktur dengan `job_id`, `user_id`, `provider`, `key_id` (bukan secret). Endpoint `/health` memeriksa DB dan Redis.
- **Performa**: query berindeks, tidak ada N+1 di daftar chat/usage, paginasi di semua daftar.
- **Tes tidak boleh memanggil API provider asli.** Gunakan mock/fake provider.

---

## 11. Environment Variables (`.env.example`)

```
# Backend
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/aigateway
REDIS_URL=redis://redis:6379/0
MASTER_ENCRYPTION_KEY=            # 32 byte acak, base64
JWT_SECRET=
ALLOWED_ORIGINS=http://localhost:3000
REGISTRATION_OPEN=true
TELEGRAM_BOT_TOKEN=
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
```

API key provider **tidak** disimpan di env. Dimasukkan lewat UI dan disimpan terenkripsi di database.

---

## 12. Definition of Done (seluruh project)

- [ ] Semua fase 0-7 lulus acceptance criteria.
- [ ] `docker compose up` berjalan dari repo bersih hanya dengan menyalin `.env.example` ke `.env`.
- [ ] CI hijau: lint, type-check, tes, build.
- [ ] Alur utama terbukti: tambah banyak key Claude → kirim pesan → key A limit → otomatis pindah ke B → tutup tab → buka lagi → hasil ada.
- [ ] Tidak ada secret di kode atau riwayat git.
- [ ] README, ARCHITECTURE, API, dan DECISIONS terisi.
- [ ] Daftar masalah/risiko yang diketahui ditulis jujur di README bagian "Known Limitations".

---

## 13. Hal yang Dilarang

- Menyimpan API key atau secret dalam plain text, di log, di frontend, atau di git.
- Memanggil API provider asli di dalam tes otomatis.
- Menjalankan proses AI langsung di request HTTP (harus lewat worker).
- Menghapus atau mengubah history chat tanpa aksi eksplisit user.
- Menambahkan dependensi besar tanpa alasan yang dicatat di `docs/DECISIONS.md`.
- Menandai tugas selesai tanpa menjalankan tes yang relevan.

---

## 14. Prompt Pembuka untuk Agent

Salin ini ke agent setelah file ini ada di repo:

```
Baca AGENT_INSTRUCTIONS.md sampai habis. Mulai dari Fase 0.
Tulis rencana singkat fase tersebut, lalu kerjakan sampai semua acceptance
criteria lulus (jalankan sendiri perintah tes/build sebagai bukti).
Setelah selesai, beri ringkasan dan lanjut ke fase berikutnya
tanpa menunggu, kecuali ada keputusan yang butuh persetujuanku.
Catat semua asumsi di docs/DECISIONS.md.
```

