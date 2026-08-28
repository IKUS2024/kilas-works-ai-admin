# LAPORAN — Kilas Works Client Hub: Production Foundation (Database, Tenant Model, Provisioning)

Tanggal: 27 Agustus 2026
Status: **DIBANGUN & TERUJI LOKAL, BELUM DI-DEPLOY** (sesuai instruksi — "Do NOT deploy yet. Stop and wait for approval.")

Cycle ini melanjutkan Client Hub V1 (diterima sebelumnya) dengan fondasi produksi: database
PostgreSQL-siap, model tenant config terstruktur, feature matrix terpusat, lapisan provisioning
yang aman/idempotent, kontrak integrasi bot masa depan, dan hardening keamanan. **Tidak ada
perubahan ke `app.py` bot produksi.** Tidak ada koneksi WhatsApp nyata dibuat. Tidak ada deploy.

---

## 1. Files created/modified

**Baru:**
- `client-hub/feature_flags.py` — matriks fitur Basic/Pro terpusat (Phase 3).
- `client-hub/provisioning.py` — lapisan provisioning idempotent (Phase 4).
- `client-hub/migrations/0002_production_foundation_sqlite.sql` — tabel `tenant_configs`,
  `tenant_whatsapp_config`, index tambahan.
- `client-hub/migrations/0002_production_foundation_postgres.sql` — versi Postgres (belum
  dieksekusi, lihat catatan kejujuran di dalamnya).
- `client-hub/BOT_INTEGRATION_GUIDE.md` — dokumentasi migrasi bot (Phase 5).
- `client-hub/tests/test_production_foundation.py` — 26 test baru.
- `client-hub/shot_9_admin_review_provisioned_desktop.png` — screenshot UI provisioning baru.

**Dimodifikasi** (semua di dalam `client-hub/`, tidak ada file bot produksi):
- `client-hub/db.py` — ditulis ulang total untuk dual backend SQLite/PostgreSQL.
- `client-hub/repo.py` — `DEFAULT_FEATURES` sekarang alias ke `feature_flags.py`; 3 insert
  memakai `db.insert_returning_id()` (portable ke Postgres); bugfix `set_business_package` sekarang
  re-seed `tenant_features`; tambahan fungsi untuk `tenant_whatsapp_config` dan `tenant_configs`.
- `client-hub/security.py` — tambahan CSRF token helper + rate limiting login.
- `client-hub/app.py` — CSRF enforcement (`before_request`), security headers, debug mode
  default aman, healthz melaporkan `db_backend`.
- `client-hub/routes_admin.py` — approve/connect-whatsapp/activate/deactivate sekarang lewat
  `provisioning.py`, bukan langsung `repo.py`.
- `client-hub/routes_client.py` — `submit_for_review` menulis event `BUSINESS_SUBMITTED`.
- `client-hub/tenant_config_service.py` — 3 fungsi baru sesuai kontrak Phase 5 (`get_tenant_by_phone_number_id`,
  `get_tenant_config`, `get_tenant_knowledge`), fungsi lama tetap ada (backward compatible).
- `client-hub/templates/*.html` — token CSRF ditambahkan ke semua form POST; `review.html`
  menampilkan versi tenant config + status WhatsApp untuk admin.
- `client-hub/requirements.txt`, `.env.example` — `DATABASE_URL`, `psycopg2-binary` (opsional).

**File bot produksi**: **TIDAK ADA yang diubah.** Dikonfirmasi via `git status`.

## 2. DB architecture

`db.py` sekarang punya dua backend dipilih otomatis lewat env var `DATABASE_URL`:
- **Tidak diset** → SQLite (default, dipakai lokal & semua 48 test di sandbox ini).
- **Diset** → PostgreSQL via `psycopg2`. Kalau `DATABASE_URL` diset tapi `psycopg2` tidak
  terinstall, app **gagal start dengan error jelas** (bukan diam-diam pakai SQLite) — ini
  disengaja, supaya konfigurasi produksi yang salah tidak pernah tanpa sadar menulis data ke
  tempat yang salah.

**Kenapa bukan SQLAlchemy**: sandbox ini masih tidak punya akses PyPI (`pip install SQLAlchemy`
gagal `403 Host not in allowlist`, dites ulang di cycle ini). Jadi dibuat abstraksi tipis sendiri
(`db.execute`/`query_one`/`query_all`/`insert_returning_id`) yang menerjemahkan placeholder `?`
(gaya SQLite) ke `%s` (gaya psycopg2) secara otomatis. Semua kode lain (repo.py, provisioning.py,
dst) HANYA memanggil fungsi-fungsi ini, tidak pernah SQL mentah lewat driver — jadi kalau nanti
tim mau pakai SQLAlchemy sungguhan demi kenyamanan query builder, cuma `db.py` yang perlu diganti.

**Kejujuran penting**: jalur PostgreSQL sudah ditulis hati-hati dan diuji SEBAGIAN (translasi
placeholder, deteksi psycopg2 hilang) tapi **belum pernah dites terhadap Postgres sungguhan** —
tidak ada akses jaringan ke server Postgres di sandbox ini. Sebelum production, jalankan test suite
sekali dengan `DATABASE_URL` mengarah ke Postgres asli.

## 3. Migration strategy

Migrasi additive-only, dijalankan berurutan lewat daftar `db.MIGRATIONS` (`0001_init_*` lalu
`0002_production_foundation_*`), idempoten (`CREATE TABLE IF NOT EXISTS`/`CREATE INDEX IF NOT
EXISTS`), aman dijalankan di setiap boot app. Tidak ada `DROP TABLE`, tidak ada reset. Migrasi
0002 menambah 2 tabel baru (`tenant_configs`, `tenant_whatsapp_config`) plus 6 index baru — kolom
existing dari 0001 tidak disentuh sama sekali (backward compatible 100% dengan V1).

## 4. Tenant model (Phase 2)

Struktur config produksi (dibangun `provisioning.build_tenant_config()`, disimpan tervensi di
`tenant_configs`):

```
{tenant_id, business_name, business_type, status,
 ai: {language, tone, system_instructions, business_description, customer_salutation},
 business_info: {address, business_hours, contact_info},
 knowledge: {faq, products, services, pricing_notes, catalog_references},
 lead_behavior: {qualification_questions, lead_fields, handoff_rules},
 appointment_behavior: {meeting_enabled, meeting_types, appointment_rules},
 feature_plan: {package, features},
 whatsapp: {connection_status, phone_number_id, waba_id, credentials_reference}}
```

Ini TERPISAH dari `ai_settings.normalized_config_json` (output mentah Claude) — config ini adalah
snapshot BERVERSI (`config_version`, naik tiap kali di-provision ulang dengan data yang berubah)
yang dirakit dari data yang SUDAH divalidasi, tidak pernah dari panggilan Claude langsung.

**Secret/credentials reference**: token WhatsApp asli **TIDAK PERNAH** disimpan di tabel manapun
yang bisa dilihat lewat UI client/admin. Kolom `credentials_reference` hanya menyimpan POINTER
(contoh: `WHATSAPP_TOKEN__TENANT_7`) — string nama tempat token sungguhan disimpan (env var/secret
manager). Dites eksplisit di `test_whatsapp_credentials_reference_is_a_pointer_not_a_token`.

## 5. BASIC vs PRO feature matrix

Dipindah ke `feature_flags.py` sebagai satu-satunya sumber kebenaran:

| Fitur | Basic | Pro |
|---|---|---|
| faq | ✅ | ✅ |
| business_info | ✅ | ✅ |
| catalog | ✅ | ✅ |
| basic_lead_capture | ✅ | ✅ |
| owner_commands | ❌ | ✅ |
| advanced_history | ❌ | ✅ |
| image_understanding | ❌ | ✅ |
| voice_note | ❌ | ✅ |
| lead_qualification | ❌ | ✅ |
| appointment | ❌ | ✅ |
| payment_conversation | ❌ | ✅ |

Harga TIDAK diubah (masih Rp499rb/Rp999rb, hanya ditampilkan lewat `PACKAGE_PRICING_DISPLAY_ONLY`
sebagai cermin, bukan sumber kebenaran baru). **Bug ditemukan & diperbaiki cycle ini**: mengubah
paket bisnis sebelumnya HANYA update kolom `package`, TIDAK re-seed `tenant_features` — jadi
tenant yang di-upgrade Basic→Pro tetap terkunci fitur lama sampai ada yang sadar. Sekarang
`repo.set_business_package()` otomatis memanggil `set_tenant_features_for_package()`. Dites di
`test_change_package_reseeds_feature_flags`.

## 6. Provisioning flow (Phase 4)

```
CLIENT submit  → repo.set_business_status(READY_FOR_REVIEW) + BUSINESS_SUBMITTED (audit)
ADMIN approve  → repo.approve_business (status=APPROVED) + BUSINESS_APPROVED (audit)
               → provisioning.provision_tenant() : validasi + rakit config + simpan versi
                 + TENANT_PROVISIONED (audit) — SATU klik "Approve" mengerjakan approve+provision
ADMIN connect  → provisioning.connect_whatsapp_credentials() : simpan phone_number_id/waba_id/
                 credentials_reference (status PENDING_VALIDATION) + WHATSAPP_CONNECTED (audit)
ADMIN activate → provisioning.activate_tenant() : cek APPROVED + whatsapp_connected + config ada
                 → repo.activate_business (status=ACTIVE) + TENANT_ACTIVATED (audit)
ADMIN deactivate → provisioning.deactivate_tenant() : status=SUSPENDED + TENANT_DEACTIVATED (audit)
```

**Idempoten**: provision ulang dengan data SAMA = no-op (tidak bikin versi baru, tidak nulis audit
duplikat) — dites `test_provisioning_idempotent_duplicate_call`. Provision ulang setelah data
BERUBAH (misal admin edit FAQ) = versi naik — dites
`test_provisioning_reprovision_after_edit_bumps_version`. Activate tenant yang SUDAH ACTIVE = no-op
aman, tidak dobel audit — dites `test_activation_duplicate_activation_is_safe_noop`.

**Invalid state transition** selalu ditolak dengan pesan jelas (bukan crash/assert generik):
provision bisnis yang masih DRAFT, activate bisnis yang belum APPROVED, activate tanpa WhatsApp
terhubung — semua raise `ProvisioningError` dengan alasan spesifik, ditangkap route dan
ditampilkan ke admin lewat flash message.

**Defense-in-depth**: setiap fungsi provisioning cek ulang `actor["role"] == "KILAS_ADMIN"` sendiri
(bukan cuma mengandalkan decorator route) — kalau dipanggil langsung dengan actor non-admin,
`PermissionError` di-raise. Dites `test_provisioning_admin_only_defense_in_depth`.

## 7. Security fixes (Phase 6)

Diaudit satu per satu:
- **Password hashing** — tidak berubah, sudah aman (PBKDF2, salted). Re-dikonfirmasi.
- **Session security** — tidak berubah (Flask signed cookie, httponly+samesite).
- **CSRF** — **BARU ditambahkan**: token per-session, wajib di semua form POST HTML + header
  `X-CSRF-Token` di 2 endpoint JSON (`simulate/message`, `simulate/flag`). Tanpa dependency baru.
- **Upload validation / path traversal** — tidak berubah (sudah aman dari cycle V1, isi byte
  divalidasi bukan cuma ekstensi, nama file disanitasi).
- **IDOR** — tidak berubah, masih 404 untuk lintas-tenant. Re-dikonfirmasi tetap PASS.
- **Admin authorization** — diperkuat dengan defense-in-depth di `provisioning.py` (lihat poin 6).
- **Tenant isolation** — tidak berubah, tetap terpusat di `security.require_business_access()`.
- **SQL injection** — tidak ada risiko baru; `db.py` dual-backend tetap 100% parameterized, tidak
  ada string-formatting SQL di manapun.
- **XSS** — Jinja2 auto-escape aktif di semua template, tidak ada satupun penggunaan `|safe`.
- **Secrets exposure** — diperluas: token WhatsApp sekarang punya arsitektur reference (poin 4),
  bukan hanya "tidak expose API key" seperti sebelumnya.
- **Unsafe debug mode** — **BUG DITEMUKAN & DIPERBAIKI**: sebelumnya default `debug=True` KECUALI
  `CLIENT_HUB_ENV=='production'` eksplisit — kalau env var itu lupa di-set sama sekali di deploy
  manapun, Flask debugger (eksekusi kode arbitrer) aktif ke publik. Sekarang dibalik: default
  `debug=False`, HANYA `CLIENT_HUB_ENV=development` yang mengaktifkan. Dites
  `test_debug_mode_defaults_off`.
- **Request size limits** — tidak berubah (`MAX_CONTENT_LENGTH` 12MB sudah ada).
- **Basic login rate limiting** — **BARU**: 8 percobaan gagal per (IP+email) dalam 5 menit →
  dikunci sementara, termasuk percobaan dengan password yang BENAR sekalipun (mencegah credential
  stuffing yang kebetulan menemukan password benar setelah dikunci). In-memory (cukup untuk skala
  V1 single-process; kalau nanti scale ke banyak worker, ganti ke Redis — titik panggilnya tidak
  berubah).
- Security headers tambahan (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).

## 8. Test results

- **`tests/test_client_hub_v1.py`** (cycle sebelumnya, TIDAK diedit/dihapus): **22/22 PASS**.
- **`tests/test_production_foundation.py`** (baru, cycle ini): **26/26 PASS** — mencakup: SQLite
  default, translasi placeholder Postgres, error jelas saat psycopg2 hilang, `insert_returning_id`,
  feature matrix Basic/Pro, bugfix re-seed saat ganti paket, bentuk tenant config, config tidak
  pernah mengarang harga, provisioning butuh status APPROVED, validasi gagal tanpa AI selesai,
  provisioning idempotent, versi naik setelah edit, aktivasi duplikat aman, aktivasi tanpa WhatsApp
  diblokir, transisi status invalid dari DRAFT diblokir, admin-only defense-in-depth, semua event
  audit kanonik ada, tenant nonaktif return None ke kontrak bot, tenant aktif return config+
  knowledge, CSRF memblokir POST tanpa token, CSRF meloloskan dengan token valid, rate limiting
  login, debug mode default aman, tidak ada secret di modul baru, credentials_reference adalah
  pointer bukan token.
- **Regresi bot produksi**: **14/14 PASS**, tidak berubah dari baseline (tidak ada file bot yang
  disentuh sama sekali).

**Total: 62/62 test PASS di cycle ini** (22 + 26 + 14).

## 9. Environment variables (lengkap, superset dari cycle sebelumnya)

Lihat `client-hub/.env.example`. Tambahan cycle ini:
- `DATABASE_URL` (opsional — kalau diset, pakai PostgreSQL; kosongkan untuk SQLite lokal).

Yang lain tidak berubah: `SECRET_KEY`, `ANTHROPIC_API_KEY`, `CLIENT_HUB_MODEL`,
`CLIENT_HUB_DB_PATH`, `CLIENT_HUB_ENV`, `PORT`.

## 10. Recommended PostgreSQL provider/setup

**Render Postgres** — paling simpel kalau Client Hub juga di-deploy sebagai Render service (satu
dashboard, `DATABASE_URL` otomatis di-inject Render kalau database & service ada di project yang
sama). Alternatif: **Supabase** (Postgres + dashboard tambahan gratis untuk skala kecil, migrasi
sama persis karena keduanya Postgres standar). Rekomendasi konkret: mulai dengan **Render Postgres
tier terkecil** (cukup untuk volume onboarding klien awal), upgrade tier kalau jumlah tenant sudah
banyak. Sebelum pakai sungguhan: jalankan `migrations/0002_production_foundation_postgres.sql` +
`0001_init_postgres.sql` sekali secara manual (atau biarkan `db.init_schema()` yang menjalankannya
otomatis saat app pertama kali boot dengan `DATABASE_URL` terisi) lalu jalankan ulang test suite
dengan `DATABASE_URL` itu untuk memvalidasi jalur yang belum tereksekusi di sandbox ini.

## 11. Whether safe to deploy Client Hub to Render

**BELUM — tunggu approval eksplisit**, sesuai instruksi. Secara teknis kode ini SUDAH lebih siap
dari cycle sebelumnya (62/62 test PASS, jalur Postgres tertulis rapi meski belum tervalidasi
langsung ke server Postgres asli). Yang masih perlu diputuskan SEBELUM deploy:
1. Postgres sungguhan (Render Postgres/Supabase) — buat instance-nya, set `DATABASE_URL`, validasi
   test suite sekali terhadap itu.
2. Buat admin pertama secara manual setelah deploy (tetap tidak ada self-serve admin registration).
3. Set `CLIENT_HUB_ENV=production` di Render (WAJIB — kalau lupa, app sekarang menolak start tanpa
   `SECRET_KEY`, jadi ini aman-gagal, bukan diam-diam insecure).

## 12. Exact next step after deployment

1. Deploy sebagai Render Web Service terpisah (root `client-hub/`), attach Render Postgres.
2. Jalankan test suite sekali lagi dengan `DATABASE_URL` produksi untuk validasi jalur Postgres.
3. Buat user admin pertama manual.
4. Setup DNS `app.kilasworks.id` → service Render tersebut.
5. Test 1 alur onboarding penuh end-to-end di lingkungan production-like (bukan cuma lokal).
6. BARU setelah itu, mulai proses koneksi WhatsApp klien pertama secara manual (lihat
   `BOT_INTEGRATION_GUIDE.md` untuk migrasi bot — TIDAK dikerjakan cycle ini, sengaja).

## 13. Confirmation app.py production bot remains untouched

**Dikonfirmasi.** `git status --porcelain` di root repo menunjukkan file bot produksi
(`app.py`, `requirements.txt`, semua 14 file test bot) TIDAK muncul sebagai berubah — hanya
`client-hub/` (baru) dan file laporan/screenshot yang muncul sebagai untracked. 14/14 test bot
regresi tetap PASS tanpa perubahan apapun.
