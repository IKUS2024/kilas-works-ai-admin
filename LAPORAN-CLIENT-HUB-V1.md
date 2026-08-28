# LAPORAN — Kilas Works Client Hub V1 (Self-Service Multi-Tenant Onboarding)

Tanggal: 27 Agustus 2026
Status kerja: **SELESAI DIBANGUN, TERUJI LOKAL, BELUM DI-DEPLOY** (sesuai instruksi — "JANGAN deploy otomatis").

Semua kode ada di folder baru `client-hub/`, terpisah total dari `app.py` (bot produksi). Tidak ada satupun file bot produksi yang diubah di cycle ini — dikonfirmasi via `git status` (hanya file dokumentasi/gambar sisa cycle sebelumnya yang untracked, tidak ada perubahan pada file bot).

---

## 1. Arsitektur yang dipilih

Aplikasi Flask **kedua**, sepenuhnya terpisah dari bot produksi:

```
kilas-works-ai-admin/
├── app.py                  ← BOT PRODUKSI, TIDAK DISENTUH
├── (14 file test bot, semua masih PASS)
└── client-hub/              ← APLIKASI BARU, 100% ADDITIVE
    ├── app.py               (entrypoint Flask sendiri, port 5050 secara default)
    ├── db.py, repo.py, security.py, ai_onboarding.py, file_utils.py
    ├── tenant_config_service.py   (interface masa depan ke bot, BELUM disambungkan)
    ├── routes_auth.py, routes_client.py, routes_admin.py
    ├── templates/*.html
    ├── migrations/0001_init_sqlite.sql, 0001_init_postgres.sql
    ├── requirements.txt, .env.example
    └── tests/test_client_hub_v1.py  (22 test, semua PASS)
```

Client Hub adalah **service yang berdiri sendiri** — bisa dijalankan, dites, dan (nanti) di-deploy independen dari bot WhatsApp. Bot tetap berjalan tanpa tahu Client Hub ada.

## 2. File/folder yang ditambahkan

Semua di bawah `client-hub/` (baru, 100%): `app.py`, `db.py`, `repo.py`, `security.py`, `ai_onboarding.py`, `file_utils.py`, `tenant_config_service.py`, `routes_auth.py`, `routes_client.py`, `routes_admin.py`, `migrations/0001_init_sqlite.sql`, `migrations/0001_init_postgres.sql`, `templates/base.html`, `templates/login.html`, `templates/register.html`, `templates/client_dashboard.html`, `templates/wizard.html`, `templates/review.html`, `templates/simulate.html`, `templates/admin_dashboard.html`, `requirements.txt`, `.env.example`, `tests/test_client_hub_v1.py`, plus 8 screenshot PNGs (`shot_1..8`) dan laporan ini.

## 3. File existing yang diubah

**Tidak ada.** `app.py` bot produksi, `requirements.txt` bot, dan seluruh 14 file test bot tidak disentuh sama sekali.

## 4. Database yang dipilih

SQLite (`sqlite3` bawaan Python), file lokal `client_hub_dev.db`.

**Kenapa bukan Postgres langsung**: sandbox tempat saya membangun ini tidak punya akses ke PyPI (terkonfirmasi — `pip install` diblokir dengan `403 Host not in allowlist: pypi.org`), jadi `psycopg2`/`SQLAlchemy` tidak bisa diinstall atau dites di sini, walaupun `psycopg2-binary` sudah ada di `requirements.txt` bot produksi untuk Render.

**Ini BUKAN rekomendasi final untuk produksi nyata.** Disk Render itu ephemeral — file SQLite di sana akan hilang setiap kali redeploy/restart, artinya semua data onboarding klien bisa hilang. Sebelum benar-benar dipakai klien nyata, pilih salah satu:
1. Arahkan `CLIENT_HUB_DB_PATH` ke Render Persistent Disk (mount volume), ATAU
2. Migrasi ke Postgres (Render Postgres atau Supabase) — saya sudah siapkan `migrations/0001_init_postgres.sql` sebagai terjemahan manual dari schema SQLite (belum pernah dijalankan/dites, karena tidak ada akses Postgres di sandbox ini).

Karena semua akses SQL SELALU lewat `db.py`/`repo.py` (tidak ada SQL inline di routes), migrasi ke Postgres nanti hanya butuh 3 perubahan: (a) ganti fungsi koneksi di `db.py` jadi psycopg2 + `DATABASE_URL`, (b) ganti placeholder `?` jadi `%s` di `repo.py`, (c) ganti akses `sqlite3.Row` jadi `RealDictCursor`. Tidak ada kode route/template yang perlu berubah.

## 5. Skema database

14 tabel: `users`, `businesses` (tenant_id = id), `business_memberships`, `business_profiles`, `business_services`, `business_faqs`, `business_files`, `ai_settings`, `tenant_features`, `onboarding_sessions` (append-only), `onboarding_status`, `tenant_activation`, `simulation_messages`, `audit_log` (append-only). Detail lengkap ada di `migrations/0001_init_sqlite.sql` (dikomentari per bagian).

## 6. Pendekatan autentikasi

Flask signed-cookie session (bawaan Flask, pakai `itsdangerous` yang sudah jadi dependency Flask) — **bukan** sistem custom. Password di-hash pakai `werkzeug.security.generate_password_hash` (PBKDF2, sudah bawaan Flask/Werkzeug, tidak perlu dependency baru). Verified: dua hash dari password yang sama selalu beda (salted) — lihat `test_security_password_never_plaintext_and_hashed_uniquely`. Aplikasi **menolak untuk start** kalau `CLIENT_HUB_ENV=production` tapi `SECRET_KEY` tidak diset (mencegah default key insecure kepakai di produksi).

## 7. Pendekatan isolasi tenant

Satu fungsi terpusat wajib: `security.require_business_access(business_id, user)`. Semua route yang menyentuh data satu business memanggil ini. Logikanya: KILAS_ADMIN boleh akses semua; CLIENT_OWNER hanya boleh kalau ada baris `business_memberships` yang cocok — kalau tidak, **404** (bukan 403), supaya penyerang tidak bisa membedakan "business tidak ada" vs "business ada tapi bukan punya kamu" (anti-IDOR-enumeration). Diuji: `test_tenant_cannot_access_another_business`, `test_security_file_download_scoped_to_tenant`.

## 8. Raw data vs AI-normalized data

Setiap `business_services`/`business_faqs` punya kolom `raw_input` (teks asli klien, tidak pernah diubah/dihapus otomatis) terpisah dari kolom hasil normalisasi AI (`service_name`, `price_from`, dll, nullable, hanya terisi setelah AI berhasil). Baris `needs_review=1` sampai AI berhasil menormalisasi. Ada juga `onboarding_sessions` — tabel append-only terpisah yang mencatat SETIAP submit wizard mentah, untuk audit, terlepas dari apapun yang ada di tabel "current". Diuji: `test_onboarding_ai_never_invents_price_needs_review_flag`, `test_onboarding_ai_failure_never_loses_raw_data_and_allows_retry`.

## 9. Alur onboarding dengan Claude API

`ai_onboarding.py` memanggil Claude API langsung (pola request yang sama persis dengan yang sudah dipakai bot produksi: `requests.post` ke `api.anthropic.com/v1/messages`, header `x-api-key`, tanpa SDK baru). Dipanggil OTOMATIS oleh aplikasi saat klien klik "Jalankan AI Setup" — admin Kilas Works **tidak perlu** copy-paste manual ke Claude. System prompt eksplisit melarang mengarang data ("JANGAN PERNAH mengarang..."), minta output JSON murni, dan setiap harga ambigu wajib `needs_review=true`. Respons AI divalidasi bentuknya (key wajib ada, `services`/`faqs` harus list) SEBELUM ditulis ke DB — AI tidak pernah menyentuh SQL langsung.

## 10. Feature flags (Basic vs Pro)

`tenant_features` — 10 boolean per tenant, di-seed otomatis saat business dibuat sesuai paket (`repo.DEFAULT_FEATURES`). Basic: faq/business_info/catalog/basic_lead_capture=true, sisanya false. Pro: semua true. Ini enforcement BACKEND, bukan cuma prompt wording — bisa dicek lewat `tenant_config_service.get_tenant_features(tenant_id)`. Diuji: `test_feature_flags_basic_vs_pro`.

## 11. Perilaku Basic vs Pro

Basic: FAQ, info bisnis, katalog, basic lead capture. Pro: tambahan owner_commands, advanced_history, image_understanding, voice_note, lead_qualification, appointment, payment_conversation. Perubahan paket lewat dashboard admin (`change_package`), tidak perlu ubah kode.

## 12. Implementasi upload file

`file_utils.py`: validasi isi file (bukan cuma ekstensi) — PDF harus mulai dengan `%PDF`, gambar dibuka+diverifikasi via Pillow, txt harus UTF-8 valid. Nama file disanitasi (hanya `[A-Za-z0-9._-]`). Maks 10MB. File yang gagal validasi **ditolak, tidak disimpan** (diuji: PDF palsu & file `.exe` ditolak). File disimpan sebagai BLOB di SQLite untuk V1 — **catatan skalabilitas**: sebelum volume klien besar, pindahkan ke object storage (Supabase Storage/Cloudflare R2/S3).

## 13. Implementasi simulasi (Test AI)

Tabel terpisah `simulation_messages`, dikunci per `(business_id, session_token)` acak per sesi. **Tidak pernah** memanggil `send_whatsapp_message`, tidak menyentuh tabel appointment/payment/conversation produksi. Diuji: `test_simulation_isolated_no_production_side_effects`, dan skenario dua tenant (`test_staging_two_tenants_no_cross_talk`) membuktikan simulasi Client B (Dental XYZ) tidak meninggalkan jejak apapun di tabel simulasi Client A (Kopi ABC).

## 14. Alur review admin

Dashboard admin (`/admin/`) dengan filter status. Klik satu business → halaman review lengkap (info bisnis, produk/harga, FAQ, files, AI knowledge, raw vs normalized, audit log). Tombol aksi: Test AI, Approve, Minta Revisi, Hubungkan WhatsApp, Activate, Deactivate, Ubah Paket — semuanya lewat klik, **tidak perlu ubah kode** untuk mengaktifkan tenant baru.

## 15. Alur aktivasi

APPROVE (lolos review manusia) dan ACTIVATE (config boleh dipakai bot produksi) sengaja dipisah. Business tidak bisa langsung ACTIVE setelah APPROVE — harus admin klik "Hubungkan WhatsApp" dulu (isi `whatsapp_phone_number_id` + nomor owner terpercaya secara manual, TIDAK ada otomasi Meta), baru tombol Activate aktif. Ini yang menjawab section 30: status APPROVED-tapi-belum-connect ditampilkan sebagai "APPROVED — WAITING_WHATSAPP_CONNECTION" di UI. Diuji: `test_admin_review_approve_activate_flow` (mencoba Activate sebelum connect-whatsapp — status TETAP APPROVED, tidak lompat ke ACTIVE).

## 16. Integrasi dengan bot yang sudah ada

`tenant_config_service.py` dibuat sebagai interface bersih, read-only, tanpa dependency Flask — **BELUM disambungkan ke `../app.py`** di cycle ini (sengaja, sesuai instruksi "jangan migrate semua sekaligus kalau berisiko"). Tiga fungsi: `resolve_tenant_id_by_whatsapp_phone_number_id()` (SATU-SATUNYA cara resolve tenant, berdasarkan `whatsapp_phone_number_id`, hanya tenant ACTIVE), `get_trusted_owner_phone()`, `get_tenant_ai_config()`. Diuji: `test_tenant_config_service_only_resolves_active_tenants` (tenant yang belum ACTIVE selalu return `None`, tidak pernah bocor config draft).

**Patch minimal yang disarankan untuk masa depan** (belum dikerjakan): di webhook `app.py`, setelah menerima `phone_number_id` dari payload Meta, panggil `tenant_config_service.resolve_tenant_id_by_whatsapp_phone_number_id(phone_number_id)`; kalau dapat tenant_id selain Kilas Works sendiri, load `get_tenant_ai_config()` dan suntikkan sebagai knowledge tambahan ke system prompt SAAT ITU JUGA (bukan permanen), di belakang feature flag supaya bot Kilas Works sendiri tetap jadi default kalau resolve gagal.

## 17. Koneksi WhatsApp: manual atau otomatis?

**Manual**, sesuai instruksi eksplisit ("JANGAN mengotomatisasi Meta onboarding secara asal"). Admin Kilas Works yang melakukan koneksi Meta secara nyata di luar aplikasi, lalu mengetik `whatsapp_phone_number_id` dan nomor owner terpercaya ke form admin.

## 18. Migrasi

`migrations/0001_init_sqlite.sql` (dijalankan otomatis & idempoten oleh `db.init_schema()` saat app start — `CREATE TABLE IF NOT EXISTS`) dan `migrations/0001_init_postgres.sql` (belum dijalankan, ditulis manual, ada catatan kejujuran di file itu). Tidak ada `DROP TABLE` di manapun. Tidak ada reset database.

## 19. Temuan keamanan

- Password selalu di-hash, tidak pernah plaintext (diverifikasi test).
- Tenant isolation: 404 untuk lintas-tenant, dites dengan percobaan IDOR langsung (ganti business_id, ganti file_id) — semua diblokir.
- Role escalation: CLIENT_OWNER yang coba akses `/admin/*` selalu dapat 403.
- Tidak ada API key/secret (Anthropic, Meta, DB) yang pernah masuk ke template atau response — diverifikasi dengan pengecekan source routes.
- File upload divalidasi isi byte-nya, bukan cuma ekstensi — file `.exe` menyamar `.pdf` ditolak.
- Tidak ada satupun tempat AI diizinkan generate SQL — semua tulisan DB lewat `repo.py` yang parameterized.

## 20. Hasil test — Client Hub V1

**22/22 PASS** (`client-hub/tests/test_client_hub_v1.py`), mencakup semua kategori section 36: AUTH, TENANT, ONBOARDING, SIMULATION, ADMIN, FEATURE, SECURITY, plus staging dua-tenant (Kopi ABC Indonesia vs Dental XYZ English) dan tenant_config_service. Jalankan dengan: `cd client-hub && python3 tests/test_client_hub_v1.py`.

## 21. Hasil regresi bot yang sudah ada

**14/14 PASS**, tidak ada yang berubah dari baseline sebelum cycle ini dimulai: `test_appointment_flow_fix.py`, `test_appointment_payment_update.py`, `test_appointment_reminders.py`, `test_appointments.py`, `test_demo_ux.py`, `test_final_launch_qa.py`, `test_language_layer.py`, `test_owner_catalog.py`, `test_owner_nlu.py`, `test_prelaunch_hardening.py`, `test_production_hardening.py`, `test_sales_engine.py`, `test_voice_note.py`, `test_voice_note_production_bugfix.py`. `git status` mengonfirmasi tidak ada file bot yang berubah.

## 22. Environment variables yang dibutuhkan

Lihat `client-hub/.env.example` — ringkasnya: `SECRET_KEY` (wajib di produksi), `ANTHROPIC_API_KEY` (untuk fitur AI), `CLIENT_HUB_MODEL` (opsional, default `claude-sonnet-4-6`), `CLIENT_HUB_DB_PATH` (opsional — **wajib diarahkan ke disk persistent kalau deploy ke Render**), `CLIENT_HUB_ENV=production`, `PORT`.

## 23. Setup manual di Render (kalau nanti deploy)

1. Buat Web Service baru (terpisah dari bot), root directory `client-hub/`.
2. Build command: `pip install -r requirements.txt`. Start command: `gunicorn app:app`.
3. Set semua env var di atas.
4. **Wajib**: tambahkan Render Persistent Disk, mount ke path tertentu, set `CLIENT_HUB_DB_PATH` ke path itu — atau selesaikan migrasi Postgres dulu. Jangan biarkan SQLite di disk ephemeral default.
5. Buat user admin pertama secara manual (lewat shell Render atau script kecil) — tidak ada halaman "daftar sebagai admin" di V1 (sengaja, supaya role admin tidak bisa self-serve).

## 24. Setup DNS untuk app.kilasworks.id

Tambahkan CNAME (atau A record sesuai instruksi Render) dari `app.kilasworks.id` ke hostname service Render yang baru dibuat di langkah 23. Aktifkan custom domain + SSL otomatis di pengaturan Render service tersebut.

## 25. Risiko yang tersisa

- SQLite di V1 belum production-grade untuk data klien nyata bervolume tinggi — perlu Postgres atau disk persistent sebelum onboarding klien sungguhan dalam jumlah banyak.
- `business_files.content` disimpan sebagai BLOB di DB — akan jadi berat kalau banyak katalog PDF besar; migrasi ke object storage direkomendasikan sebelum volume besar.
- Belum ada rate-limiting/brute-force protection di endpoint login/register.
- Belum ada verifikasi email saat register (siapapun bisa daftar dengan email apapun tanpa konfirmasi).
- Integrasi ke bot produksi (`tenant_config_service`) baru berupa interface, belum pernah dipanggil oleh `app.py` — masih perlu patch kecil terpisah + testing regresi lagi sebelum benar-benar multi-tenant live.
- Belum ada pytest asli terpasang di sandbox ini (memakai konvensi script `assert` seperti 14 test bot yang sudah ada) — kalau nanti pindah ke CI, pertimbangkan setup pytest yang benar.

## 26. Screenshot

Dilampirkan terpisah (desktop & mobile): register, client dashboard, wizard onboarding, login mobile, client dashboard mobile, admin dashboard desktop, admin review desktop, admin dashboard mobile.

## 27. Langkah selanjutnya untuk Anda

1. Review laporan ini dan folder `client-hub/` (saya kirim semua file).
2. Jalankan lokal kalau mau coba sendiri: `cd client-hub && export SECRET_KEY=... && export ANTHROPIC_API_KEY=... && python3 app.py`, buka `http://localhost:5050`.
3. Putuskan: SQLite + Render Disk (cepat) vs migrasi Postgres dulu (lebih aman jangka panjang) — beri tahu saya pilihannya kalau mau saya proses.
4. Kalau sudah oke, saya siapkan langkah deploy Render + DNS `app.kilasworks.id` (belum saya jalankan apapun ke Render/DNS sekarang, sesuai instruksi).
5. Buat user admin pertama (Anda) secara manual setelah deploy.
6. Rencanakan kapan mulai menyambungkan `tenant_config_service` ke bot produksi (patch kecil terpisah, dengan regresi test ulang).

## 28. Rekomendasi deploy

**NOT YET — TIDAK deploy dulu.** Semua fitur V1 berfungsi dan lulus 22 test lokal + 14 regresi bot tanpa kegagalan, tapi ada 2 hal yang sebaiknya diputuskan dulu sebelum live dengan klien sungguhan: (1) strategi database persisten (SQLite+disk vs Postgres) — jangan biarkan data klien pertama hilang karena disk ephemeral, dan (2) siapa admin pertama & bagaimana akunnya dibuat. Setelah dua hal itu diputuskan, aplikasi ini siap di-deploy sebagai service terpisah tanpa risiko ke bot produksi yang sudah jalan.
