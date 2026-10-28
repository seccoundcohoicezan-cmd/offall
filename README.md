# OFALL — AI Gateway & Agent Multi-Provider

**1 Chat • Banyak AI.** Tambahkan banyak API key dari banyak provider (Claude, OpenAI, Gemini, Groq, OpenRouter, Mistral, Ollama), lalu pakai semuanya dari satu chat.

- **Pilih model** per chat (atau `Auto` / Smart Routing), bisa diganti di tengah chat tanpa kehilangan history.
- **Key pool + auto-rotasi**: Akun A kena limit → otomatis pindah ke Akun B, C, ... Strategi fill-first / round-robin / least-used.
- **Tetap jalan saat offline**: AI diproses di worker. Tutup tab, buka lagi, jawaban sudah ada (stream disambung ulang).
- **AI Agents**: buat agent dengan nama, deskripsi, instruksi, dan model default; aktifkan per chat.
- **Token Saver**: rapikan teks, buang duplikat, sliding window + rolling summary, semantic cache, prompt caching.
- **Analytics**: token, biaya, cache hit, % hemat per hari / provider / key. **Notifikasi** Web Push & Telegram. **PWA**.

> Gunakan hanya API key milik sendiri atau yang pemiliknya memberi izin. Sistem ini tidak mengakali batas gratis provider; ia hanya merotasi key sah milikmu dan menghormati `retry-after`.

Dokumen: [ARCHITECTURE](docs/ARCHITECTURE.md) · [API](docs/API.md) · [DECISIONS](docs/DECISIONS.md) · [Rancangan awal](docs/RANCANGAN.md) · [Instruksi agent](AGENT_INSTRUCTIONS.md)

## Jalankan lokal (Docker)

Butuh Docker + Docker Compose.

```bash
cp .env.example .env
docker compose up -d --build
# buka http://localhost:3000 → Daftar → Multi-Provider → tambah provider & key
```

`.env.example` menyalakan provider **Mock** (tanpa biaya) agar bisa langsung dicoba: buat provider "Mock", tambah key `demo-ratelimit-A` (selalu 429) dan `demo-ok-B`, lalu kirim pesan. Akun A masuk *Cooldown*, Akun B menjawab.

Service: `frontend` (port 3000, satu-satunya yang perlu publik), `api` (FastAPI, menjalankan migrasi Alembic saat start), `worker` (ARQ), `db` (Postgres 17), `redis`. Cek kesehatan: `curl localhost:3000/health` → `{"status":"ok","db":"ok","redis":"ok"}`.

## Pengembangan tanpa Docker

```bash
# backend (Python 3.12, uv)
cd backend && uv sync
uv run pytest                      # 82 tes, SQLite; TEST_DATABASE_URL=postgresql+asyncpg://... untuk Postgres
uv run ruff check . && uv run mypy app
DATABASE_URL=... REDIS_URL=... MASTER_ENCRYPTION_KEY=... JWT_SECRET=... \
  uv run alembic upgrade head && uv run uvicorn app.main:app_factory --factory --port 8000
uv run arq app.worker.WorkerSettings   # worker, terminal lain

# frontend (Node 22)
cd frontend && npm ci
API_INTERNAL_URL=http://localhost:8000 npm run dev
npm run lint && npm run typecheck && npm test
E2E_BASE_URL=http://localhost:3000 npx playwright test   # butuh stack jalan + ENABLE_MOCK_PROVIDER=true
```

## Deploy ke Dokploy

Repo ini satu `docker-compose.yml`, cocok untuk service **Compose** di Dokploy.

1. Di project Dokploy → **Create Service → Compose**. Source: GitHub `seccoundcohoicezan-cmd/offall`, branch `main`, compose path `./docker-compose.yml`.
2. Tab **Environment**: isi variabel berikut (jangan pakai nilai dev dari `.env.example`):
   ```
   ENVIRONMENT=production
   MASTER_ENCRYPTION_KEY=<python3 -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())">
   JWT_SECRET=<python3 -c "import secrets;print(secrets.token_urlsafe(48))">
   POSTGRES_PASSWORD=<password kuat>
   ALLOWED_ORIGINS=https://<domain-kamu>
   COOKIE_SECURE=true
   REGISTRATION_OPEN=true          # set false setelah akun-akun dibuat
   ENABLE_MOCK_PROVIDER=false
   TELEGRAM_BOT_TOKEN=              # opsional
   VAPID_PUBLIC_KEY= / VAPID_PRIVATE_KEY=   # opsional (npx web-push generate-vapid-keys)
   ```
   Dokploy menulis variabel ini ke file `.env` di samping compose, yang dibaca `env_file: .env`.
3. Tab **Domains**: tambahkan domain → service `frontend`, port `3000`, HTTPS (Let's Encrypt). API tidak perlu domain sendiri.
4. Jika `initdb` gagal dengan `could not change permissions ... Operation not permitted` (host yang melarang chmod di Docker volume), set `PG_DATA_PATH=../files/pgdata` agar data Postgres memakai bind mount di folder `files` Dokploy.
5. Jika host Dokploy sudah memakai port 3000, set `WEB_PORT` ke port lain (atau hapus mapping `ports` karena Traefik Dokploy merutekan lewat network internal).
6. **Deploy**. Auto-deploy: aktifkan webhook/Autodeploy di Dokploy, **atau** isi secret repo GitHub `DOKPLOY_URL`, `DOKPLOY_API_KEY` (Dokploy → Settings → Profile → API/CLI), `DOKPLOY_COMPOSE_ID` agar `.github/workflows/deploy.yml` memanggil `POST /api/compose.deploy` setelah CI hijau.

Alternatif (lihat AGENT_INSTRUCTIONS): frontend di Vercel (`API_INTERNAL_URL` = URL publik API), API + worker di Railway/Render/VPS, Postgres di Neon/Supabase, Redis di Upstash. Satu domain lewat Dokploy lebih sederhana karena cookie tetap first-party.

## Memori (agent yang mengingat kamu)

Halaman **Memory**: profil pengguna yang dibangun otomatis, daftar fakta/preferensi (tambah, ubah, sematkan, hapus, setujui yang menunggu review), pencarian di seluruh riwayat chat, dan log aktivitas (audit). Pengaturan di **Settings → Memori** (pakai memori, belajar otomatis, review manual). Memori eksternal opsional: `MEMORY_EXTERNAL_URL` / `MEMORY_EXTERNAL_TOKEN`. Rencana fitur agent berikutnya: [docs/AGENT_ROADMAP.md](docs/AGENT_ROADMAP.md).

## 9Router / endpoint OpenAI-compatible

Multi-Provider → tambah **9Router** (atau *OpenAI-compatible*), isi Base URL, lalu **Sinkron dari /v1/models** atau tambah nama model manual. API key opsional. Base URL harus bisa dijangkau **dari server OFALL**:
- 9Router di server yang sama (di luar Docker): `http://host.docker.internal:20128/v1` (default).
- 9Router sebagai service Dokploy di server yang sama: pakai nama/URL internalnya.
- 9Router di laptop sendiri (`localhost:20128`) **tidak** bisa dijangkau server; jalankan di server atau buka lewat tunnel/HTTPS.

Rotasi key, fallback ke provider lain, token saver, dan analytics tetap berlaku untuk model 9Router.

## Manajemen user (admin)

- Akun **pertama** yang mendaftar otomatis menjadi **admin**.
- Menu avatar → **Manajemen user** (`/admin`): buat akun (email + password awal), ubah peran user/admin, nonaktifkan (sesi & job yang antre langsung dicabut), reset password, hapus user, dan buka/tutup **pendaftaran mandiri**. Saat pendaftaran ditutup, hanya admin yang bisa membuat akun.
- Selalu ada minimal satu admin aktif; admin tidak bisa menonaktifkan atau menghapus dirinya sendiri.
- Darurat (lupa akun admin): jalankan di container `api`: `python scripts/make_admin.py email@kamu.com [passwordBaru]`.

## Backup & restore

```bash
docker compose exec -T db pg_dump -U offall -Fc aigateway > backup-$(date +%F).dump
docker compose exec -T db pg_restore -U offall -d aigateway --clean < backup-YYYY-MM-DD.dump
```

Simpan `MASTER_ENCRYPTION_KEY` di tempat aman terpisah: tanpa kunci itu, API key di backup tidak bisa didekripsi. Redis hanya berisi antrean & stream sementara; tidak perlu di-backup.

## CI/CD

`.github/workflows/ci.yml`: backend (ruff, format, mypy, pytest di Postgres dengan coverage ≥ 80%, `alembic upgrade` + `alembic check`), frontend (eslint, tsc, prettier, vitest, build), lalu E2E: `docker compose up --wait` + Playwright (login → tambah key → kirim → tutup tab → buka lagi → jawaban ada; reload di tengah streaming). `deploy.yml` memicu Dokploy setelah CI hijau di `main`.

## Status fase (AGENT_INSTRUCTIONS bagian 9)

| Fase | Status |
|---|---|
| 0 Fondasi | compose, `.env.example`, CI. `docker compose up` belum dijalankan di mesin pengembang (tidak ada akses Docker di sana) — divalidasi oleh job `e2e` di CI. |
| 1 Backend inti | ✅ auth, enkripsi, CRUD provider/key/model, tes "key tidak pernah muncul utuh" (respons + log). |
| 2 Queue/Worker/Job | ✅ tes integrasi: SSE diputus di tengah, job tetap selesai, sambung ulang = teks lengkap. |
| 3 Key Pool & Router | ✅ 429 A→B, semua habis → `waiting_quota`, key pulih → job lanjut, 2 worker paralel tidak bentrok, round-robin/least-used, fallback provider. |
| 4 Token Saver | ✅ tes unit (teks, code block, tabel, angka/URL, identik, history panjang) + benchmark > 50% hemat pada history berulang. |
| 5 Frontend | ✅ semua halaman + Agents; Playwright 2 skenario lulus terhadap stack lokal. |
| 6 Notifikasi/PWA/Hardening | Sebagian: Web Push + Telegram + PWA + rate limit + log terstruktur + backup doc. Scan dependensi dijalankan (lihat DECISIONS). Belum: uji beban. |
| 7 Deploy & Docs | README/ARCHITECTURE/API/DECISIONS, workflow deploy Dokploy. Menunggu akses Dokploy untuk deploy pertama. |

## Known Limitations

- **Belum diuji ke API provider asli.** Semua tes memakai provider palsu (sesuai aturan). Pemetaan error 429/402/401 mengikuti format LiteLLM; pesan "kredit habis" tiap provider bisa berbeda dan perlu dipantau di produksi.
- **Sisa kuota** hanya akurat bila user mengisi `Kuota/hari` per key; provider tidak memberi sisa kuota yang seragam. Status `exhausted` reset otomatis 00:00 UTC; kredit bulanan perlu diaktifkan ulang manual.
- **Lanjut di tengah streaming** dengan key lain bisa menghasilkan sedikit pengulangan teks (model tidak selalu patuh instruksi "lanjutkan").
- **Semantic cache** memakai embedding lokal (kemiripan kata), hanya untuk pesan pertama chat. Sinonim jauh tidak dianggap sama.
- **Estimasi token** Token Saver = karakter/4; biaya memakai usage asli provider.
- **Mode Banding** (kirim ke 2–3 model sekaligus) dan tools agent (web search, eksekusi kode) dari rancangan belum dibuat — di luar spesifikasi fase 0–7.
- Upload file/lampiran di chat belum ada.
- Uji beban (Fase 6) belum dijalankan. Scan dependensi: npm bersih; `filelock` (transitif LiteLLM) punya 3 CVE yang belum bisa dinaikkan — lihat DECISIONS.
