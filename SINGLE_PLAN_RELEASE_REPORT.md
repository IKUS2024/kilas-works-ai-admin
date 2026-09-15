# Kilas Brain Single Plan — release report

Baseline: `1424ac4620f46f789db70ccc79100181a4887937`  
Final local commit: `7d2e11933a100c9134ef31421e90cad74a1d9371`  
Branch: `refactor/kilas-brain-single-plan-cost-control`  
Tanggal: 2026-09-15. Satu commit lokal; tidak push dan tidak deploy. Worktree lama tidak diubah.

## Hasil

Penjualan baru memakai satu paket **Kilas Brain Rp499.000/bulan**, internal `AI_ADMIN` / `ai_admin`. `NONE` tetap ada untuk bisnis yang tidak menggunakan Brain. Semua 11 flag fitur Pro yang sudah ada digunakan oleh paket baru; ini tidak menciptakan fitur baru atau membuka akses tanpa entitlement/langganan yang berlaku. Ruang layanan tetap 1 bisnis / 1 nomor WhatsApp. Data/model tenaga kerja, harga Content/Event/hosting/Ads, transport, quotation, dan invoice historis tidak ditulis ulang.

Catalog seed menambahkan baris baru secara idempotent dan mengarsipkan Basic/Pro. Baris lama tetap ada untuk referensi transaksi. Query katalog aktif dan editor admin juga menolak penjualan kembali kedua penawaran lama. Pembaruan boot tidak me-reset harga paket baru yang kemudian diedit admin. UI paket baru, checkout, feature defaults, dan konteks penjualan platform memakai definisi pusat BRAIN_PLAN; identifier dan label historis Basic/Pro dipertahankan untuk membaca data lama.

Legacy Basic dan Pro tidak dimigrasikan massal. Subscription, periode dan harga transaksi lama tetap berlaku. Pesanan lama yang belum selesai dapat dilanjutkan melalui jalur historisnya; pembelian baru menggunakan ai_admin. Perpindahan legacy ke AI_ADMIN membutuhkan pembayaran paket tujuan yang diverifikasi, kemudian package/config/subscription disinkronkan lewat helper yang sudah ada. Invoice yang sudah terkunci tidak dihitung ulang. Semua kemampuan legacy yang sebelumnya sah tetap berlaku sampai lifecycle yang sudah ada menonaktifkannya.

## Konteks dan runtime

Satu helper `compact_history` digunakan customer, owner platform, dan owner tenant. Dari riwayat yang sudah dimiliki jalur tersebut, request mengirim paling banyak 8 pesan terbaru (termasuk pesan user saat ini) + 4 pesan lama yang relevan secara lexical. Hasil deduplikasi berurutan kronologis. Tidak ada summarization API, classification API baru, model kedua, retry baru, atau perubahan model default. Structured business/customer memory, shared brain, natural-language rules, knowledge retrieval, cache breakpoint pada prompt stabil, guard tindakan, tenant resolution, dan Human Takeover tetap menggunakan arsitektur yang ada. Riwayat DB lengkap tidak dipangkas; ketersediaan konteks lama mengikuti load/storage yang sudah ada.

Vision menormalkan EXIF, mempertahankan rasio aspek, tidak upscale, dan membatasi sisi terpanjang 2048 px. PNG diprioritaskan untuk teks; gambar yang akan melebihi 4.5 MB memakai JPEG kualitas 92. Jika tetap terlalu besar, ditolak sebelum request provider. File asli, jalur media Inbox, dan audio tidak diubah. Normal Haiku-first; Sonnet tetap pada seleksi vision/analisis yang sudah ada. Retry/fallback lama hanya pada kondisi kegagalan yang sebelumnya ditangani; tidak ada loop baru.

Ledger menyimpan usage Anthropic yang benar-benar dikembalikan provider, scope business/platform, model, klasifikasi normal/vision/complex, token, estimasi biaya dan waktu UTC. Tidak ada nomor telepon, isi chat, knowledge, foto, URL privat, atau credential di ledger/log baru. Koneksi pencatatan terpisah tidak dapat commit/rollback transaksi aplikasi. Kegagalan pencatatan fail-open dengan alasan aman; jawaban bot tetap berjalan. Respons valid dibedakan dari model call yang berbiaya tetapi hasilnya tidak berisi teks. Ledger bukan bukti pengiriman WhatsApp ke penerima.

Admin `/admin/ai-usage` melihat ringkasan per business/platform bulan UTC; client hanya jumlah respons business yang telah diotorisasi. Soft fair use default 2000 respons/business/bulan; WARNING mulai 75%, HIGH mulai 100%, tidak ada hard stop atau penghentian langganan. Peringatan tambahan untuk cost, proporsi Sonnet, dan konteks normal tinggi. Detail formula, keterbatasan dan ENV ada dalam AI_COST_MODEL.md.

## Meta dan batas kesiapan produksi

Copy menjelaskan biaya WhatsApp Business Platform dari Meta terpisah. Belum dapat dijamin biaya langsung ditagihkan ke WABA milik client: callback Embedded Signup saat ini belum menuntaskan exchange/binding credential server-side. Kanal manual existing tidak diganti. Sebelum menjanjikan direct billing, operator wajib mengonfirmasi kepemilikan WABA, nomor, payment method, dan pengaturan penagihan Meta. Tidak ada rahasia/config produksi dibaca atau diubah.

Dua layanan Render harus menjalankan release yang kompatibel dan memakai PostgreSQL bersama. PostgreSQL/Docker/Podman lokal tidak tersedia; eksekusi migration/concurrency nyata di PostgreSQL belum diuji. Ini adalah gate staging sebelum deploy, bukan klaim PASS PostgreSQL. Migrasi 0026 harus berjalan dahulu. Jangan rollback ke kode lama yang tidak mengenali AI_ADMIN setelah bisnis baru dibuat. Prosedur ada pada MIGRATION_NOTES_SINGLE_PLAN.md.

Knowledge Setup/Assist hanya mendapat pencatatan usage pada panggilan yang memang sudah ada. Tidak ada panggilan pada load/save/readiness. Static official PDF dan endpoint /catalog.pdf tidak diubah. File HTML landing di repo hanya dibersihkan dari pilihan tier lama; tidak ada publikasi/perubahan website eksternal. Salinan historis root routes/templates yang tidak diimpor runtime dibiarkan sebagai historical artifacts.

## Verifikasi

Runner offline utama meliputi semua 89 file Python yang didaftarkan runner repo. Full pass awal: 60 lulus / 29 gagal; 21 dari 29 kegagalan tersebut juga direproduksi pada baseline yang tidak diubah. Ekspektasi harga/tier/bundle/route lama serta fixture schema/gambar diperbaiki tanpa menonaktifkan security assertion. Setelah targeted reruns: 89/89 file lulus. Tambahan 2 file Python di tests/ lulus (27 cases), 8/8 kasus JS UI lulus, dan 32 kasus baru lulus. Tidak ada paid AI/API call saat tes. Rincian dan seluruh hasil per file dalam TEST_REPORT_SINGLE_PLAN.md.

## Manifest delta

ZIP berisi full blob final dari 58 file di bawah, plus empat laporan release. Laporan adalah artifact export yang merujuk SHA commit; tidak menambah commit kedua. Bukan repository lengkap: overlay ke baseline yang sesuai. Tidak ada penghapusan file dalam diff.

- _test_bootstrap.py
- app.py
- client-hub/ai_onboarding.py
- client-hub/ai_payment_review.py
- client-hub/ai_usage.py
- client-hub/app.py
- client-hub/catalog_service.py
- client-hub/db.py
- client-hub/display_labels.py
- client-hub/feature_flags.py
- client-hub/knowledge_assist.py
- client-hub/migrations/0026_ai_usage_postgres.sql
- client-hub/migrations/0026_ai_usage_sqlite.sql
- client-hub/payment_service.py
- client-hub/pricing_config.py
- client-hub/repo.py
- client-hub/routes_admin.py
- client-hub/routes_client.py
- client-hub/subscription_service.py
- client-hub/templates/_brain_plan_notice.html
- client-hub/templates/admin_ai_usage.html
- client-hub/templates/base.html
- client-hub/templates/business_settings.html
- client-hub/templates/checkout.html
- client-hub/templates/client_dashboard.html
- client-hub/templates/review.html
- client-hub/templates/wizard.html
- client-hub/tests/brief_test_helpers.py
- client-hub/tests/test_absolute_final_production_patch.py
- client-hub/tests/test_ai_admin_single_purchase_path.py
- client-hub/tests/test_app_service_briefs.py
- client-hub/tests/test_business_hub_v2_ecosystem_sync.py
- client-hub/tests/test_business_hub_v2_final_ops_polish.py
- client-hub/tests/test_business_hub_v2_phase_bcd.py
- client-hub/tests/test_business_sales_upgrade.py
- client-hub/tests/test_catalog_editor_removed.py
- client-hub/tests/test_client_hub_ux_batch.py
- client-hub/tests/test_client_hub_v1.py
- client-hub/tests/test_repo_ai_settings_postgres_json_compat.py
- client-hub/tests/test_service_selection_purchase_flow.py
- client-hub/tests/test_single_plan_release.py
- client-hub/tests/test_targeted_production_upgrade.py
- client-hub/tests/test_ux_catalog_final.py
- context_engine.py
- generate_katalog_pdf.py
- landing-page-kilasworks.html
- test_astra_production_fix.py
- test_business_hub_v2_whatsapp_integration.py
- test_ecosystem_sync_bot.py
- test_multi_tenant_runtime_safety.py
- test_owner_catalog.py
- test_prelaunch_hardening.py
- test_price_transport_uncertainty_guardrails.py
- test_sales_engine.py
- test_single_plan_context.py
- test_tenant_owner_media_and_isolation.py
- test_tenant_persistence_and_payment_review.py
- test_voice_note.py

Laporan tambahan:
- SINGLE_PLAN_RELEASE_REPORT.md
- AI_COST_MODEL.md
- MIGRATION_NOTES_SINGLE_PLAN.md
- TEST_REPORT_SINGLE_PLAN.md
