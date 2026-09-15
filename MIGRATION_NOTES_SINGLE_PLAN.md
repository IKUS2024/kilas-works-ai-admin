# Migration dan deployment manual

Release `7d2e11933a100c9134ef31421e90cad74a1d9371`, parent `1424ac4620f46f789db70ccc79100181a4887937`. Tidak ada push/deploy otomatis.

## Migrasi wajib

Tambahan **0026**:
- `client-hub/migrations/0026_ai_usage_sqlite.sql`
- `client-hub/migrations/0026_ai_usage_postgres.sql`
- registrasi pada `client-hub/db.py`.

Hanya CREATE TABLE IF NOT EXISTS ai_usage_ledger dan dua CREATE INDEX IF NOT EXISTS. Foreign key tenant_id -> businesses.id nullable untuk scope platform; token BIGINT PostgreSQL/INTEGER SQLite; timestamp TIMESTAMPTZ PostgreSQL/teks ISO8601 UTC SQLite. Tidak ada DROP/DELETE, perubahan tabel transaksi, atau rewrite invoice/project/subscription/knowledge. Kolom is_reply membedakan respons valid dan call model. Schema SQLite diuji fresh/repeated; PostgreSQL dibaca untuk kompatibilitas tetapi tidak dieksekusi karena server/container lokal tidak ada.

Migration 0024 (knowledge) dan 0025 (WhatsApp checkout) tetap, tidak dimodifikasi. Tidak ada migrasi per-business config. Catalog seed existing menambahkan ai_admin lalu mengarsipkan penawaran Basic/Pro, bukan menghapusnya. Paket legacy tetap kompatibel di repo/subscription/feature flags dan label historis.

## Urutan paling aman

1. Backup database produksi, simpan rollback artifact dan SHA yang aktif. Pastikan baseline aplikasi sesuai; ZIP ini delta 58 file, bukan replacement repository lengkap.
2. Overlay file ZIP dengan path relatif yang tepat pada checkout baseline. Empat Markdown adalah dokumentasi, tidak perlu dijadikan kode runtime. Jangan salin .env/DB dari workspace mana pun.
3. Di staging PostgreSQL jalankan migrasi dari kode release. Verifikasi record historis dan ID tetap, query ledger, scoped response count, legacy active Basic/Pro, expired entitlement, serta purchase AI_ADMIN yang baru.
4. Jalankan migration 0026 pada PostgreSQL produksi bersama **sebelum** mengaktifkan aplikasi release, menggunakan mekanisme existing:

   ```sh
   cd client-hub
   python3 scripts/run_migrations.py
   ```

   Gunakan DATABASE_URL existing dari service; jangan menyalin credential ke terminal/chat/log. Migration runner existing dapat menjalankan semua migrasi terdaftar idempotently. Alternatif existing RUN_MIGRATIONS_ON_BOOT=true untuk satu deploy saja, lalu kembalikan seperti sebelumnya; one-off migration lebih jelas. Jangan menganggap PostgreSQL otomatis migrasi saat boot default.
5. Pastikan bot `kilas-works-ai-admin` dan Hub `kilas-works-client-hub` memakai PostgreSQL yang sama dan model pricing/FX config yang konsisten. Nilai ENV produksi tidak diverifikasi dalam workspace ini. SQLite hanya untuk lokal, tidak untuk ledger lintas service Render.
6. Jeda penerimaan penjualan Brain baru secara operasional selama pergantian versi. Deploy bot release lebih dahulu, lalu Hub release, sehingga customer tidak menciptakan AI_ADMIN baru ketika bot masih kode lama. Pastikan kedua service memakai SHA release yang kompatibel sebelum melanjutkan penjualan. Hindari campuran versi berkepanjangan.
7. Smoke test manual: katalog hanya satu Brain499k; semua flag current plan; legacy invoice masih nominal lama; existing verified subscription bekerja; unpaid new plan tidak melewati payment gate; tenant A tidak melihat B; satu chat Haiku masuk ledger business yang tepat; owner/vision sesuai; client hanya counter miliknya; admin dashboard biaya/unknown sesuai ENV; fair-use warning tidak mematikan AI.
8. Pastikan Meta WABA ownership, nomor, dan billing secara manual sebelum menjanjikan penagihan langsung ke client. Callback Embedded Signup existing belum merupakan bukti tersambung/billing langsung. Copy rilis hanya menjanjikan biaya Meta terpisah.

## ENV

Tidak ada credential baru atau perubahan model wajib. Tetap gunakan DATABASE_URL, kredensial Anthropic dan WhatsApp existing. Optional AI_COST_USD_IDR harus kurs sah; jika unset dashboard IDR unknown. Optional pricing/threshold ENV lengkap dalam AI_COST_MODEL.md. Set konsisten pada kedua service. Jangan ubah CLIENT_HUB_MODEL, CLIENT_HUB_SIMULATION_MODEL, CLIENT_HUB_ASSIST_MODEL atau provider/model WhatsApp untuk memasang rilis ini.

## Rollback

Ledger additive dapat dibiarkan; jangan DROP atau hapus transaksi untuk rollback. Setelah AI_ADMIN baru digunakan, kode baseline lama tidak mengenali paket tersebut: rollback penuh ke baseline tidak aman tanpa compatibility release atau memulihkan backup terkoordinasi yang telah direkonsiliasi. Jangan mass-convert subscription atau mengubah historical invoice untuk memaksa rollback. Jika masalah hanya usage monitoring, jangan menonaktifkan payment/tenant guard; perbaiki ledger/schema/connectivity sambil mengandalkan fail-open recording. Selalu simpan record historis.
