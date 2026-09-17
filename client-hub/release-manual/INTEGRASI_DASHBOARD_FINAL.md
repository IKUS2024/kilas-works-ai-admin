# Integrasi dashboard pelanggan dan owner/admin — laporan final

Melanjutkan commit `69acf4d5281804b07faf091a7e76ceb726092923` pada repository existing. Phase 6C dan semua pekerjaan sebelumnya dipertahankan. SHA commit yang dikemas tercatat pada `FINAL_REVIEW_METADATA/current-commit.txt` dan `review-metadata/commit.json`.

## Perubahan

- Beranda self-service memulihkan Ajari Kilas Brain dan Booking & Pembayaran memakai `/business/<id>/memory` serta `/business/<id>/settings` existing. Ajari Brain tersedia pada READY_FOR_REVIEW, APPROVED dan ACTIVE; status setup awal tetap mengikuti UI existing. Review, Simulasi, status langganan dan Inbox ACTIVE dipertahankan. Tombol memakai flex-wrap agar dapat turun baris.
- Rekening pada Booking & Pembayaran adalah milik bisnis pelanggan, terpisah dari rekening Kilas Works penerima langganan Finance. Tidak ada sistem pengaturan baru.
- Action Center menghitung TRIAL_ACTIVE menggunakan service entitlement authoritative, termasuk bisnis Finance tanpa Brain. PAID_ACTIVE mendapat prioritas dan trial kedaluwarsa tidak dihitung. Tautan `/admin/?finance=trial` menampilkan nama, status dan waktu berakhir WIB. Trial tidak membutuhkan approval admin.
- Action Center menghitung seluruh `finance_subscription_bills` berstatus REVIEW, terpisah dari pembayaran proyek/layanan, dan menautkan `/admin/finance-subscription-bills`. Antrean existing tetap menampilkan maksimal 200 tagihan; hitungan Action Center mencakup semuanya.
- Pengaman admin dan tenant, CSRF serta seluruh route/service Finance dan pembayaran tidak diubah. Halaman trial admin hanya membaca data; tidak membuat entitlement atau pembayaran.
- Builder ZIP menerima commit turunan Phase 6C tanpa mengubah history dan tetap mensyaratkan working tree bersih. Source diambil dari commit final, termasuk seluruh pekerjaan lokal sebelumnya.

## File yang berubah

Semua di `client-hub/`:

- `routes_admin.py`
- `templates/product_dashboard.html`
- `templates/admin_dashboard.html`
- `tests/test_dashboard_finance_integration.py`
- `scripts/build_final_package.py`
- `release-manual/PANDUAN_PENGGUNA_ID.md`
- `release-manual/MULAI_DI_SINI.md`
- `release-manual/HASIL_UJI.md` (hasil rilis sebelumnya ditandai sebagai historis)
- `release-manual/INTEGRASI_DASHBOARD_FINAL.md` (dokumen ini)

## Hasil tes

PATCH INTEGRASI DASHBOARD — HASIL PENGUJIAN TERBARU
183 tes lulus: 13 tes terfokus + 170 regresi Client Hub; 0 failure, 0 error, 0 skip.
Dijalankan dari client-hub dengan runner existing: proses terisolasi, SQLite disposable, outbound Python diblokir, provider dimock.
Tidak menjalankan ulang suite root atau seluruh repository. Hasil 1.975 test case + 11 script check dari rilis sebelumnya bukan hasil pengujian ulang patch ini; bukti historis ada di manual/HASIL_UJI.md.

test_dashboard_finance_integration: 13 lulus
test_final_product_flow: 86 lulus
test_business_hub_v2_phase_e: 5 lulus
test_business_hub_v2_final_ops_polish: 35 lulus
test_subscription_lifecycle: 31 lulus
test_knowledge_setup_v2: 13 lulus

PERINTAH:
python -B tests/run_finance_regressions.py test_dashboard_finance_integration
python -B tests/run_finance_regressions.py test_final_product_flow test_business_hub_v2_phase_e test_business_hub_v2_final_ops_polish test_subscription_lifecycle test_knowledge_setup_v2

CAKUPAN:
Kontrol Brain READY_FOR_REVIEW/APPROVED/ACTIVE, Inbox hanya ACTIVE, bisnis tanpa Brain, pembatasan tenant editor.
Finance NOT_ACTIVATED/TRIAL_ACTIVE/PAID_ACTIVE/EXPIRED read-only; trial oleh pelanggan tanpa approval; setup, unggah bukti, approve/reject, idempotensi, CSRF, dan pemisahan langganan.
Action Center angka nol/non-nol, daftar trial/nama/status/kedaluwarsa, paid precedence dan expiry, tautan antrean existing, item lama tetap utuh, penolakan non-admin.

BELUM DIVERIFIKASI:
PostgreSQL nyata/migrasi/concurrency, browser visual/mobile, Anthropic nyata, dokumen struk/bank nyata, integrasi email/Meta/WhatsApp dan production.
Knowledge UI JavaScript historis tetap belum terverifikasi; 13 regresi Python knowledge bukan pengganti browser/JavaScript UI.
Dependency requirements dipasang pada runtime lokal yang sudah ada; bukan uji instalasi deployment dari lingkungan kosong.
Tidak ada push, deployment, production migration.

## Migrasi dan konfigurasi

Tidak ada migrasi atau konfigurasi baru untuk patch ini. Environment Finance self-service, rekening pembayaran, provider AI dan role KILAS_ADMIN tetap mengikuti `CONFIG_EXAMPLE.txt` dan `DEPLOYMENT_ID.md`. Schema existing termasuk 0032 tetap harus tersedia pada deployment aktual. Tidak menjalankan migrasi production.

## Pemeriksaan paket

Paket dibuat setelah commit. Builder memeriksa CRC dan byte ZIP. Verifikasi akhir membandingkan semua source dengan HEAD, checksum manifest, struktur metadata, pengecualian file runtime dan pemindaian pola secret. Hasil aktual tersimpan pada `review-metadata/package-verification.json`. Pemindaian statis tidak membuktikan semua kemungkinan secret; file konfigurasi contoh berisi placeholder dan fixtures tes bukan kredensial production.

Tidak ada push, deployment, atau production migration. ZIP berada di luar repository dan tidak dilacak Git.
