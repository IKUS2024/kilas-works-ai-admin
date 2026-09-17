# Pemasangan dan rencana deployment

Dokumen ini adalah instruksi untuk operator. **Tidak ada langkah production di bawah yang telah dijalankan saat membuat paket.**

## Pahami dua service

| Service | Direktori kerja dari paket | Build | Start |
|---|---|---|---|
| Client Hub, seluruh Finance dan halaman Produk baru | `source/client-hub` | `pip install -r requirements.txt` | `gunicorn --workers 1 --threads 1 --bind 0.0.0.0:$PORT app:app` |
| Bot/Brain existing | `source` | `pip install -r requirements.txt` | `gunicorn -c gunicorn.conf.py app:app` |

Entrypoint keduanya bernama `app:app`; **direktori kerja harus benar**. Rilis ini tidak mengubah runtime root, Meta, WhatsApp, atau prompt Brain. Tidak perlu mengganti service bot jika hanya menerapkan perubahan Client Hub dan versi root production sudah sama/lebih baru. Source root disertakan lengkap untuk keterlacakan dan instalasi baru.

Gunakan Python 3.11+ pada Linux; pengujian paket menggunakan Python 3.12. Flask **3.1 atau lebih baru** diperlukan oleh batas upload per request Phase 6B. Parser PDF memakai `resource` pada subprocess Linux, batas memori 384 MiB, CPU 5 detik, timeout induk 8 detik; lingkungan tanpa resource isolation menolak PDF, bukan menonaktifkan proteksinya.

Gunakan satu worker/satu replica Client Hub pada tahap ini: kuota AI dan login limiter masih berada dalam memori proses. Jangan mengklaim kuota terdistribusi bila menggandakan worker/replica. Database mengamankan konkurensi ledger tetapi bukan distribusi kuota AI.

## Memasang ke repository yang sudah ada

1. Verifikasi hash ZIP yang diberikan dan ekstrak ke direktori baru, bukan langsung menimpa checkout kerja/production.
2. Periksa `review-metadata/commit.json`, `changed-files.txt`, `deleted-files.txt`, `release.diff`, dan `cumulative.diff`.
3. Bandingkan dengan **commit deployment aktual**, bukan menganggap server ada di SHA yang diharapkan. Paket berawal dari Phase 6C `b8b22046d02d150c84c059250aaaf56170f4f280`. Remote/main lokal ketika inspeksi adalah `6886dccdc86e2cd4d9aec3c96b0672b031e0e664`; remote tidak di-fetch dalam tugas ini.
4. Buat branch/cadangan checkout sendiri. Terapkan file yang sesuai setelah review; pertahankan perubahan repository yang lebih baru. Jangan reset, rebase, overwrite otomatis, atau menghapus pekerjaan lain. Diff disediakan untuk review, source lengkap disediakan untuk instalasi.
5. Perhatikan daftar file terhapus. Jika daftar kosong, tidak ada penghapusan rilis yang harus diterapkan. Tidak boleh menghapus file production hanya karena tidak ada di ZIP: database, secrets, upload, cache dan dependency memang dikecualikan.
6. Jangan mengunggah ZIP sebagai satu file ke GitHub lalu menganggap aplikasi telah diperbarui. Isi `source/` harus diterapkan pada struktur source yang benar. Push/deploy adalah keputusan operator terpisah, tidak dilakukan oleh pembuat paket.

## Instalasi staging/disposable

Di direktori `source/client-hub`:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Isi variabel environment dengan nilai **staging**, sesuai `CONFIG_EXAMPLE.txt`. Jangan mengarah ke database production. Tidak diperlukan API key untuk menjalankan tes offline atau pencatatan manual. Model vision/text memakai konfigurasi Anthropic existing; pastikan akun provider mendukung modelnya sebelum uji nyata.

Untuk SQLite uji, ikuti generator fixture pada `PANDUAN_UJI_ID.md`. Untuk staging PostgreSQL yang sengaja dibuat baru, atur `DATABASE_URL` staging, lalu jalankan migrasi melalui runner existing:

```sh
python scripts/run_migrations.py
```

Semua migrasi sebelumnya tetap diperlukan. `db.MIGRATIONS` adalah daftar resmi. Finance memakai 0028 (ledger), 0029 (receivables), 0030 (recurring), 0031 (bank staging); rilis ini menambah **0032_finance_subscription** versi SQLite dan PostgreSQL. Migrasi 0032 membuat entitlement, tagihan Finance, identitas request tagihan, dan idempotensi setup bisnis; tidak mengaktifkan trial/pelanggan lama secara massal. Tidak ada tabel chat Finance.

Setelah migrasi, gunakan `RUN_MIGRATIONS_ON_BOOT=false` secara eksplisit. Jangan membuka aplikasi versi baru pada skema yang belum siap. Runner bawaan bisa menjalankan seluruh migrasi; operator wajib memeriksa versi dan backup, bukan menyalakan migrasi boot tanpa kendali. File migrasi historis tidak diubah.

Jika instalasi baru belum mempunyai admin, gunakan `scripts/bootstrap_admin_env.py`, setelah schema siap. Isi `BOOTSTRAP_ADMIN_CONFIRM=CREATE_FIRST_KILAS_ADMIN`, `BOOTSTRAP_ADMIN_EMAIL`, dan `BOOTSTRAP_ADMIN_PASSWORD` minimal 12 karakter melalui environment; jalankan `python scripts/bootstrap_admin_env.py`. Hapus variabel bootstrap setelah berhasil. Script menolak jika admin sudah ada dan tidak menaikkan role akun lama. Jangan memakai kredensial demo di production.

## Prasyarat konfigurasi manual

- Database production/staging berbeda, backup yang sudah diuji restorasinya, akses DB dengan hak secukupnya.
- `SECRET_KEY` acak minimal 32 karakter, HTTPS, secure cookies, waktu server tersinkron.
- `PUBLIC_APP_BASE_URL` adalah origin HTTPS Client Hub tanpa path/query/credentials.
- Mode Finance: `internal_beta` mempertahankan beta gate/allowlist; `self_service` memerlukan entitlement aktif untuk setiap write/AI. Dalam self-service, pilih `KILAS_FINANCE_ANALYST_ENABLED` dan `KILAS_FINANCE_OPERATOR_ENABLED` secara eksplisit.
- Isi ketiga `KILAS_FINANCE_PAYMENT_BANK_*` dengan rekening yang benar. Tagihan Finance tidak dibuat ketika petunjuk pembayaran belum lengkap.
- Admin pemeriksa pembayaran harus akun `KILAS_ADMIN` existing. Jangan memberikan role tersebut kepada pelanggan.
- Atur Anthropic hanya jika menggunakan AI. Provider gagal tidak berarti transaksi dicatat. CSV, form manual dan laporan deterministik tetap tidak memerlukan provider.
- SMTP/Resend dan konfigurasi Brain existing harus diverifikasi sesuai deployment sendiri. Environment bot dan Client Hub harus mengarah pada data tenant yang benar bila integrasi multi-tenant digunakan. Finance mandiri tidak mensyaratkan aktivasi WhatsApp.

## Checklist sebelum production — belum dieksekusi

1. Backup production dan uji restore terpisah.
2. Jalankan seluruh migrasi hingga 0032 pada PostgreSQL staging/disposable.
3. Jalankan smoke test concurrency PostgreSQL nyata: trial bersamaan, verifikasi bayar bersamaan, POST bank vs MATCH, biaya rutin terpilih. Pengujian SQLite tidak membuktikan locking PostgreSQL.
4. Uji satu akun pelanggan biasa: bisnis baru dan bisnis existing, trial, aktif, habis, perpanjangan dan bukti ditolak.
5. Uji satu struk nyata, satu PDF myBCA nyata, satu screenshot mutasi nyata. Periksa koreksi tanggal/arah/nominal dan totals sebelum/sesudah explicit confirm.
6. Uji mobile 360/390/430 px dan desktop, kamera/galeri/PDF, kehilangan koneksi, kembali/refresh, dan token kedaluwarsa.
7. Uji pemisahan tenant dan role admin, CSRF, secure cookies/HTTPS, no-store, audit/log aman.
8. Siapkan rencana rollback, lalu baru jadwalkan migrasi/rollout production secara terkendali.

## Rollback dan mematikan akses

- `KILAS_FINANCE_EMERGENCY_DISABLE=true` memblokir write dan AI Finance melalui service; data, laporan, dan billing tetap tersedia. Ini pilihan darurat, bukan bukti pelanggan belum membayar.
- Matikan hanya Analyst/Operator melalui capability flag jika masalahnya terbatas pada AI. Ketiadaan API key tidak mematikan form manual.
- Kembali ke `internal_beta` + `KILAS_FINANCE_BETA=false` menutup Finance pelanggan biasa; admin tetap memiliki akses internal sesuai kebijakan existing. Jangan gunakan langkah ini sebagai cara trial gratis tersembunyi.
- **Jangan mengembalikan kode ke Phase 6C lama lalu membuka akses pelanggan:** versi lama belum mengenal entitlement. Jika rollback kode diperlukan, tutup ingress Finance dulu. Pertahankan seluruh tabel 0031/0032; jangan drop atau menghapus riwayat. Restore database hanya sebagai prosedur insiden terencana, dengan memperhitungkan data baru setelah backup.
- Trial aktif, periode berbayar, bukti, dan keputusan rekonsiliasi tidak dihapus ketika akses dimatikan. Tidak ada cron yang wajib dijalankan untuk menandai trial habis.
