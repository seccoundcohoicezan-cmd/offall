# Roadmap: OFALL Agent otonom (terinspirasi Hermes Agent)

Dikerjakan berurutan 1 → 10; tiap tahap baru dianggap selesai setelah tes otomatis +
E2E lulus. Aturan global untuk semua tahap:

- **Konfirmasi wajib** untuk aksi berisiko: hapus file, perintah root/sudo, kirim pesan
  keluar (Telegram/Discord/Slack/WhatsApp/email), akses jaringan ke host baru. Agent
  membuat *permintaan aksi* (status `awaiting_approval`), user menyetujui dari UI/chat.
- **Kredensial** hanya lewat environment variable / secret store terenkripsi
  (AES-GCM seperti API key), tidak pernah di prompt, log, atau git.
- **Audit log** (`audit_logs`, halaman Memory → Log aktivitas) untuk setiap aksi agent.
- **Self-improvement eksperimental**: semua hasil belajar (memori/skill) bisa dimatikan
  dan bisa dipaksa lewat review manual sebelum dipakai permanen.

| # | Fitur | Status | Rencana singkat |
|---|---|---|---|
| 1 | Memori persisten | ✅ selesai (iterasi 3) | lihat bawah |
| 2 | Skill yang belajar sendiri | berikutnya | tabel `skills` (nama, deskripsi, langkah, versi, status draft/approved, built-in/optional, dependensi); setelah job multi-langkah sukses → worker menyusun draft skill (review manual); skor keberhasilan per pemakaian → revisi versi; skill bawaan: coding, pencarian, dokumen, multimedia; skill opsional ditandai butuh dependensi. |
| 3 | Penjadwal (cron) | | parser jadwal bahasa natural ("tiap pagi jam 7") → cron expression via LLM murah + validasi; tabel `schedules`; ARQ cron memicu job tanpa pengawasan; hasil dikirim lewat notifikasi/platform pesan (kirim keluar = perlu persetujuan sekali per jadwal). |
| 4 | Subagent paralel | | job induk memecah tugas → N subjob dengan konteks & toolset sendiri, dijalankan paralel di worker, hasil digabung (map-reduce) ke jawaban utama; batas paralel per user. |
| 5 | Multi-platform messaging | | adapter Telegram (bot), Discord, Slack, WhatsApp (Cloud API) → chat masuk diteruskan ke gateway; layanan dijalankan sebagai container (setara systemd, `restart: unless-stopped`) + unit systemd contoh untuk VPS. |
| 6 | Multi-model | ✅ sebagian (sudah ada) | adapter LiteLLM + 9Router + ganti model di tengah chat tanpa kehilangan konteks sudah jalan; tinggal "per-langkah model" untuk agent/subagent. |
| 7 | Terminal backend | | sandbox eksekusi: Docker (default, tanpa jaringan, limit CPU/RAM/timeout), lalu SSH, Daytona, Modal; Local hanya untuk self-host dengan izin eksplisit; hasil nyata (stdout/stderr/exit code/file) dikembalikan & dicatat di audit. |
| 8 | CLI | | `ofall` CLI (Python, prompt_toolkit): multiline, autocomplete slash-command, riwayat, Ctrl+C interrupt-and-redirect, streaming output tool; login memakai token API. |
| 9 | Browser & suara | | tool browser via Playwright di sandbox; percakapan suara: STT (Whisper API/lokal) + TTS di frontend (Web Speech/OpenAI TTS). |
| 10 | Library & pemeliharaan | | paket Python `ofall-client` (SDK ke API), perintah `ofall update` (cek rilis GitHub, pull image, migrasi). |

## Tahap 1 — Memori persisten (selesai)

- **Fakta, preferensi, konteks** per user di tabel `memories` (bisa ditambah, diubah,
  disematkan, dihapus di halaman **Memory**). Memori yang relevan dengan pertanyaan
  (embedding lokal, tanpa biaya token) + memori yang disematkan ikut dikirim ke model di
  setiap chat; jawaban menampilkan badge "N memori".
- **Belajar otomatis (eksperimental)**: setelah jawaban selesai, task worker terpisah
  (`learn_from_job`) meminta model termurah mengekstrak fakta tentang user. Data sensitif
  (password, API key, nomor kartu) disaring. Bisa dimatikan, atau diwajibkan **review
  manual** (memori baru berstatus *menunggu review*).
- **Model pengguna**: ringkasan profil ≤80 kata yang diperbarui otomatis saat ada memori
  baru (atau tombol *Susun ulang*), disuntikkan ke setiap chat.
- **Pencarian riwayat**: tab *Cari riwayat* + otomatis saat user menulis "kita pernah
  bahas ...": cuplikan percakapan lama yang relevan ikut dikirim ke model.
- **Memori eksternal**: `MEMORY_EXTERNAL_URL` (+ `MEMORY_EXTERNAL_TOKEN`) — tulis
  dicerminkan, hasil cari digabung; penyimpanan bawaan tetap utuh. Kontrak:
  `POST /memories {user_id, content, kind}`, `GET /search?user_id&q&k → {results:[{content}]}`.
- **Audit log** untuk aksi agent/user/admin (memori, key, user management, sync model).
