# Kilas Finance — patch UX dan keandalan AI

Basis workspace: `3df1a53c95a315ad57181e94c81767e35bcec653`. Patch melanjutkan source existing; tidak mengubah ledger, pembayaran, skema database, model atau API key. SHA final dicatat dalam `PATCH_METADATA.json` di ZIP.

## Penyebab yang terbukti dari kode dan tes

1. Parser provider sebelumnya langsung memakai json.loads: JSON valid yang dibungkus satu pagar `json` ditolak. Parser bersama ini dipakai Analyst, Operator, Receipt dan ekstraksi bank. Patch menerima satu objek JSON lengkap atau satu objek dalam pagar json lengkap. Teks sebelum/sesudah, beberapa objek, duplicate key, NaN/Infinity/overflow, respons terpotong dan skema tidak valid tetap ditolak. Body JSON request HTTP tetap ketat; dukungan pagar hanya pada respons provider.
2. ReceiptError mewarisi ValueError. Exception handler lama menangkap kembali upstream_failure dan menggantinya dengan invalid_result; network/timeout juga kehilangan kategorinya. analyze lalu membuat review kosong dengan fallback. HTTP 200 hanya berarti halaman review dirender, bukan bukti ekstraksi berhasil.
3. Pemilihan foto sebelumnya hanya mengganti input, tanpa aksi berikutnya yang jelas. Kini label menjadi Baca Struk dan fokus diarahkan ke tombol. Tidak ada pengiriman isi file sebelum klik eksplisit.

Penyebab tepat insiden production belum dipastikan: tidak ada request/payload provider atau log live yang diakses. Keberhasilan flow Anthropic lain tidak membuktikan key/model salah. Tidak mengganti key/model, tidak menambah retry otomatis atau panggilan AI tambahan.

## Perilaku baru

- Satu tombol AI Assistant pada dashboard. Analyst/Operator/Receipt/Bank tetap memakai route dan engine existing. Alat manual, laporan, piutang, biaya rutin/proyek dan rekonsiliasi tersedia dalam Alat Finance Lainnya.
- Filter dashboard memakai dropdown bulan Indonesia dan tahun, tanpa JavaScript wajib. Server memvalidasi lalu mengarahkan ke `?month=YYYY-MM`, mempertahankan filter arah transaksi. Pilihan tahun mencakup sepuluh tahun sebelumnya hingga lima tahun berikutnya serta tahun terpilih dari tautan existing. Perhitungan laporan tidak diubah. Pada lebar <=480px kontrol ditumpuk; min-width:0 dan width:100% mencegah overflow kontrol.
- Foto/pilih struk pada mode struk → Baca Struk → Membaca struk → Review Hasil. File ambigu tetap meminta pilihan struk/mutasi; CSV tetap memakai alur bank. Pengiriman ganda selama proses diblokir di UI.
- Merchant, tanggal, total IDR dan deskripsi hasil ekstraksi mengisi form review existing. Saran kategori ditampilkan; akun/kategori akhir tetap pilihan pengguna. Hanya konfirmasi eksplisit yang menulis; konfirmasi ulang sama tetap idempotent.
- Kegagalan atau hasil kosong, bahkan readable=true tanpa field berguna, menampilkan pesan jelas, tautan pilih ulang, dan form manual. Tidak menyimpan transaksi otomatis.
- Log internal hanya `FINANCE_AI receipt_reason=` dengan kategori success, not_configured, upstream_failure, network_failure, timeout, invalid_result, unreadable, rate_limited. Tidak mencatat exception, payload, filename, token, ID atau nilai keuangan. Analyst menampilkan pesan aman beserta opsi Laporan & Export; error browser mentah tidak ditampilkan.
- Auth, tenant, CSRF, validasi file, signed review, entitlement dan expired/read-only tetap dipertahankan. Tidak ada migrasi atau konfigurasi baru.

## Hasil pengujian

**480 tes lulus: 462 Python + 18 Node DOM; 0 gagal/error/skip.** Rerun tidak dijumlahkan. Hanya tes terfokus dan regresi Finance terkait; root dan suite repository keseluruhan tidak dijalankan.

| Suite | Tes lulus |
|---|---:|
| test_finance_phase1a | 15 |
| test_finance_phase4a | 15 |
| test_finance_phase4b | 35 |
| test_finance_phase4c | 25 |
| test_finance_phase6a | 53 |
| test_finance_phase6b | 114 |
| test_finance_phase6c | 103 |
| test_final_product_flow | 86 |
| test_finance_ux_ai_fix | 16 |
| test_finance_assistant_ui.cjs (termasuk error UI Analyst) | 18 |

Perintah dari client-hub:

```sh
python -B tests/run_finance_regressions.py test_finance_ux_ai_fix
python -B tests/run_finance_regressions.py test_finance_phase1a test_finance_phase4a test_finance_phase4b test_finance_phase4c test_finance_phase6a test_finance_phase6b test_finance_phase6c test_final_product_flow
node --test tests/test_finance_assistant_ui.cjs
```

Regresi awal mendeteksi satu ekspektasi teks manual lama. Pesan tersebut dipertahankan bersama petunjuk fallback baru; Phase 6C dijalankan ulang dan lulus. Setelah penanganan readable=true tanpa field, tes terfokus dan Receipt/Assistant dijalankan ulang dan lulus. Tes navigasi lama disesuaikan ke satu AI Assistant tanpa menghapus pemeriksaan akses engine langsung.

Cakupan: selector dan persistence, CSS shrink/stack, JSON/fence validation, review terisi, pesan gagal/kuota/konfigurasi/timeout/upstream aman, tanpa retry, konfirmasi sekali, tenant, expired, routing receipt/bank dan Analyst/Operator. Tes CSS adalah pemeriksaan aturan responsive, bukan verifikasi visual browser nyata. Anthropic nyata, dokumen nyata, browser mobile/desktop visual dan PostgreSQL nyata belum diuji.

## Isi dan penggunaan ZIP

ZIP berisi hanya file berubah pada commit patch, laporan ini, dan metadata/ringkasan tes/checksum. Tidak berisi seluruh aplikasi. Sebelum menerapkan manual, cocokkan dengan checkout main production aktual dan cadangkan file terkait; jangan menimpa perubahan yang lebih baru. Pertahankan jalur `client-hub/`. Tidak ada secret, file .env nyata, database, upload pelanggan, cache atau ZIP lama. Integritas CRC dan kesamaan byte dengan commit diperiksa saat pengemasan.

Tidak dilakukan push, deploy, atau migrasi production.
