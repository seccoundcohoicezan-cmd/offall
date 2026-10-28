# Keputusan & Asumsi

Dicatat sesuai `AGENT_INSTRUCTIONS.md` aturan 6. Format: keputusan → alasan.

## Arsitektur

1. **Queue: ARQ (Redis)**, bukan Celery. Async-native, satu dependensi (Redis yang memang sudah wajib), cron bawaan untuk scheduler `waiting_quota`.
2. **Event job memakai Redis Streams** (`jobstream:{job_id}`), bukan pub/sub murni. Setiap chunk punya id, jadi SSE bisa disambung lagi dengan `Last-Event-ID` tanpa celah, dan klien yang datang belakangan bisa me-replay seluruh jawaban. Stream kedaluwarsa 1 jam setelah aktivitas terakhir; setelah itu SSE mengirim `snapshot` dari `jobs.partial_output` di DB.
3. **Frontend mem-proxy `/api/*` ke backend (Next.js rewrites).** Cookie auth `httpOnly` jadi first-party, tidak perlu CORS/SameSite=None, dan di Dokploy cukup satu domain publik (frontend). Akibatnya `NEXT_PUBLIC_API_URL` tidak dipakai; alamat API internal (`API_INTERNAL_URL`) di-bake saat build image frontend.
4. **Token JWT di cookie `httpOnly`** (access path `/`, refresh path `/api/v1/auth`). Header `Authorization: Bearer` tetap didukung untuk klien API. Refresh token dirotasi sekali-pakai dan disimpan (`refresh_tokens`) sehingga bisa dicabut.
5. **SSE dibaca dengan `fetch` + parser sendiri**, bukan `EventSource`, supaya bisa mengirim header `Last-Event-ID` sendiri dan me-refresh token saat 401.

## Key pool

6. **Prioritas key: angka kecil = dicoba duluan** (urutan 0, 1, 2 ... = Akun A, B, C). UI "geser urutan" menulis ulang prioritas.
7. **Aman konkurensi**: transisi status = satu `UPDATE ... WHERE status IN (...)` (key `invalid`/`disabled` tidak bisa "hidup lagi" karena race); setiap key punya lease Redis dengan batas `KEY_MAX_CONCURRENCY` (default 4) sehingga worker paralel menyebar ke key lain; job di-*claim* dengan `UPDATE ... WHERE status IN (queued, waiting_quota)` sehingga dua worker tidak menjalankan job yang sama. Diuji juga terhadap Postgres sungguhan.
8. **Klasifikasi error** (`services/llm.py`): 402 / teks berisi quota/credit/billing/insufficient_quota → `exhausted` sampai 00:00 UTC berikutnya (reset harian; untuk kredit bulanan user bisa mengaktifkan ulang manual); 429 → `cooling_down` sesuai `retry-after` (default 60 dtk); 401/403 → `invalid` + notifikasi; 400/404/413/422 → error request, tidak memutar key; lainnya (5xx/jaringan) → coba key berikutnya tanpa menandai rusak.
9. **Kuota harian opsional per key** (`daily_token_quota`) untuk menampilkan "sisa kuota" dan berhenti memakai key yang sudah mencapai batas buatan user. Provider tidak mengekspos sisa kuota secara seragam, jadi angka ini adalah batas yang user tetapkan sendiri.
10. **Lanjut di tengah streaming**: partial dikirim sebagai pesan `assistant` lalu pesan user "lanjutkan tanpa mengulang". Cara ini jalan di semua provider; hasilnya bisa sedikit tumpang-tindih (model tidak selalu patuh).

## Token Saver

11. **Estimasi token = karakter/4.** Cukup untuk metrik penghematan relatif, tanpa tokenizer berat. Angka biaya tetap memakai `usage` asli dari provider.
12. **Semantic cache memakai embedding lokal** (hash kata + trigram karakter, 512 dimensi, cosine ≥ 0.95), bukan API embedding: cache lookup tidak boleh menghabiskan token/biaya. Konsekuensinya cache menangkap parafrase yang kata-katanya mirip, bukan sinonim jauh. Cache dipisah per user, per model yang diminta + system prompt, dan **hanya untuk pesan pertama sebuah chat** (pertanyaan lanjutan bergantung konteks, jawaban lama bisa salah).
13. **Rolling summary** jalan bila history > 24 pesan (agresif: > 10), meringkas pesan di luar window (12 / 6 pesan) memakai model termurah yang tersedia; ringkasan disimpan di `chats.summary` dan diperbarui inkremental. Gagal meringkas tidak menggagalkan job.
14. Pesan yang berisi code block atau tabel tidak pernah di-near-dedupe; dedupe "mirip" mensyaratkan angka dan URL identik.
15. **Prompt caching**: untuk Anthropic, system prompt ≥ ~1024 token diberi `cache_control: ephemeral`. OpenAI dan Gemini meng-cache prefix panjang secara otomatis, jadi tidak perlu penanda.

## Lain-lain

16. **Agent** = nama + deskripsi + instruksi + model default, milik user. Satu agent aktif per chat; instruksinya digabung dengan system prompt default user. Memilih agent dengan model default mengganti model chat.
17. **Provider `mock`** (aktif jika `ENABLE_MOCK_PROVIDER=true`) menjawab tanpa API key untuk demo dan E2E. Key yang mengandung `ratelimit` / `quota` / `invalid` mensimulasikan 429 / kuota habis / 401 sehingga rotasi bisa didemokan. Matikan di produksi bila tidak perlu.
18. `.env.example` berisi secret **placeholder dev** agar `docker compose up` langsung jalan; API menolak start dengan placeholder itu saat `ENVIRONMENT=production`.
19. User pertama yang mendaftar menjadi `admin` (belum ada fitur admin khusus; disiapkan untuk ke depan).
20. Harga model di katalog = harga list perkiraan per 1M token, hanya untuk estimasi di dashboard.
21. Judul task menyebut "Banyak AI 1 kategori": ditafsirkan sebagai satu chat/kategori yang memakai banyak provider di belakangnya (model dikelompokkan per provider di picker). Jika maksudnya kategori model (mis. "Coding", "Riset") sebagai grup tersendiri, itu bisa ditambahkan sebagai iterasi berikutnya.

## Dependensi besar

- **LiteLLM** - adapter tunggal untuk semua provider (wajib di spesifikasi).
- **pywebpush** - Web Push VAPID.
- **react-markdown + remark-gfm + rehype-highlight (highlight.js)** - render markdown, tabel, dan highlight kode di chat.

## Scan dependensi (2026-10-28)

- `npm audit --omit=dev`: 0 kerentanan.
- `pip-audit` (lockfile backend): 3 CVE di `filelock 3.32.7` (CVE-2026-112907/112913/112940, fix di 4.2.1). Paket ini dependensi transitif LiteLLM (via `huggingface-hub`/`tokenizers`), dan `litellm==1.106.5` mengunci `filelock<4`, jadi belum bisa dinaikkan. Paparan rendah: aplikasi tidak memakai filelock dengan path dari input user. Naikkan begitu LiteLLM melonggarkan batasnya.

## Iterasi 2 (2026-10-28)

22. **`crypto.randomUUID` hanya ada di HTTPS/localhost.** Situs live masih HTTP, jadi idempotency key dibuat lewat `lib/uuid.ts` (fallback `getRandomValues`). Jika kirim pesan pertama gagal, chat kosong yang baru dibuat langsung dihapus agar tidak menumpuk "Chat baru".
23. **Manajemen user milik admin**: kolom `users.is_active`, `display_name`, `last_login_at` + tabel `app_settings` (saat ini `registration_open`) yang menimpa env `REGISTRATION_OPEN`, sehingga admin bisa membuka/menutup pendaftaran dari UI tanpa redeploy.
24. **Logo**: memakai mark infinity dari file brand `OFALL-logo.png` (dipotong jadi `logo-mark-wide.png`, ikon PWA, favicon); wordmark "OFALL." dirender sebagai teks agar terbaca di mode terang & gelap.
25. **Rate limit per user dinaikkan ke 600/menit** (per IP 1200/menit): dashboard melakukan beberapa polling per user, 120/menit terlalu ketat. Login/register tetap 10/menit per IP.
26. **Layout**: hero sambutan hanya di layar chat baru; panel kanan (model/agent) tampil permanen mulai 1536px, di bawahnya dibuka lewat tombol (bottom sheet di HP). HP memakai bottom navigation.
