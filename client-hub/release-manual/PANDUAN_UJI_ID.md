# Panduan uji — database disposable saja

## Suite otomatis offline

Dari `source/client-hub`, setelah memasang dependency Python:

```sh
python tests/run_finance_regressions.py --all-client-hub
python tests/run_finance_regressions.py --all-root
node --test tests/test_finance_assistant_ui.cjs
node tests/test_whatsapp_signup_ui.cjs
```

Runner Python membuat database sementara terpisah per modul, menyingkirkan konfigurasi production/provider dari proses anak, dan memblokir koneksi socket keluar termasuk subprocess. Semua provider pada pengujian terkait dimock. File root dibaca/dijalankan sebagai tes, tidak diubah.

Hasil dan jumlah persis tersedia di `review-metadata/test-results.json` serta `HASIL_UJI.md`. Jangan menjumlahkan rerun sebagai tes unik. Tiga skrip root menjalankan assertion saat import; dilaporkan sebagai **script checks**, bukan disamarkan menjadi jumlah test case terstruktur.

Finance UI menggunakan DOM harness offline, bukan Chrome. Skrip Knowledge UI existing membutuhkan `jsdom` dan HTML halaman Knowledge yang dirender; dependency itu tidak tersedia di lingkungan pengerjaan, sehingga skrip tersebut **belum lulus/dijalankan dengan prasyarat lengkap**. Kegagalan pemanggilan awal dicatat, bukan ditutupi.

## Akun uji pelanggan biasa, tanpa allowlist per bisnis

Gunakan database **baru** di lokasi yang bisa dibuang. Jangan salin database production. Dari `source/client-hub`:

```sh
unset DATABASE_URL APP_ENV RENDER
export CLIENT_HUB_ENV=test
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export DEMO_FIXTURE_PASSWORD='<PASSWORD_UJI_BARU_MINIMAL_12_KARAKTER>'
export CLIENT_HUB_DB_PATH=/tmp/kilas-demo-local.sqlite3
python scripts/create_finance_demo.py --db "$CLIENT_HUB_DB_PATH" --allow-disposable-fixtures
export KILAS_FINANCE_ACCESS_MODE=self_service
export KILAS_FINANCE_ANALYST_ENABLED=true
export KILAS_FINANCE_OPERATOR_ENABLED=true
export RUN_MIGRATIONS_ON_BOOT=false
export PORT=5050
gunicorn --workers 1 --threads 1 --bind 127.0.0.1:$PORT app:app
```

Ganti placeholder password dengan nilai uji Anda sendiri. Nama file harus diawali `kilas-demo-` dan file belum boleh ada. Script menolak PostgreSQL, production/Render, file existing, tanpa flag persetujuan eksplisit, atau password terlalu pendek. Script ini tidak dijalankan saat boot.

Buka `http://127.0.0.1:5050`. Login pelanggan `customer.finance@example.test` dengan password uji tadi. Tersedia tiga bisnis: **UJI LOKAL Finance Trial**, **Aktif**, dan **Kedaluwarsa**. Role pelanggan tetap `CLIENT_OWNER`. Akun admin terpisah: `admin.finance@example.test` dengan password uji yang sama. Akun dan status tersebut hanya fixture disposable, bukan bukti pembayaran nyata. Audit fixture menggunakan kategori khusus; tidak boleh dipindahkan ke production.

Jangan isi key provider nyata untuk uji offline. Bila ingin menguji layanan nyata di staging, lakukan tahap itu secara terpisah, dengan persetujuan pemilik dokumen dan konfigurasi staging yang benar. Panggilan nyata berbiaya; paket ini tidak mengklaimnya telah diuji.

## Langkah uji pengguna

1. Keluar lalu buka Produk. Harga/manfaat terlihat tanpa login. Pilih Finance, daftar akun baru, pastikan pilihan berlanjut dan belum ada trial/order/ledger.
2. Pilih bisnis existing; ulangi setup dan pastikan tidak menduplikasi. Buat bisnis berbeda secara eksplisit; nama sama tidak menggabungkan bisnis.
3. Simpan Kas/Bank/E-Wallet dan saldo awal; periksa belum ada transaksi. Mulai trial dengan checkbox. Ulangi POST yang sama: tanggal trial tetap.
4. Akun trial/aktif dapat mencatat manual dan memakai kemampuan AI yang dikonfigurasi. Expired tetap dapat membaca laporan/ekspor; POST langsung, AI, import review, invoice payment dan konfirmasi lama ditolak.
5. Jalankan import CSV contoh sendiri dengan format `date,description,debit,credit` atau `date,description,amount,direction`. Periksa REVIEW, perbaiki baris, buka pencocokan eksplisit, lalu MATCH/POST/IGNORE satu per satu. MATCH tidak mengubah totals; POST hanya sekali.
6. Buat dua biaya rutin. Preview tidak mengubah ledger. Pilih hanya satu; yang lain tetap pada tanggal semula. Ulangi pilihan sama dan periksa tidak ada duplikasi. VOID tidak menghasilkan posting pengganti.
7. Untuk menguji billing lokal, isi tiga variabel rekening Finance dengan label **UJI, BUKAN UNTUK TRANSFER** lalu restart server. Buat tagihan; upload gambar bukti sintetis. Login admin, periksa, verifikasi/tolak. **Jangan transfer uang nyata dalam uji fixture.** Ulangi verifikasi: periode tetap satu tambahan. Coba retry request tagihan sama setelah verifikasi: kembali ke tagihan asli.
8. Pilih bisnis Brain yang belum aktif; setup dan simulasi tidak mengklaim WhatsApp aktif. Membuka checkout tidak membuat pesanan; POST eksplisit baru membuat/reuse pesanan.
9. Layanan kreatif: lanjut brief yang sama; custom tidak bisa membayar sebelum penawaran; pesanan pribadi tetap tanpa bisnis; akses bisnis orang lain ditolak.
10. Periksa tampilan pada 360/390/430 px dan desktop nyata: label, tombol 44px, selected files, keyboard, status loading, tidak ada horizontal scroll yang wajib pada composer, dan kamera/galeri/PDF.

## Concurrency dan PostgreSQL

Tes baru mengirim operasi bersamaan melalui thread dan koneksi SQLite terpisah: trial, setup bisnis/akun, pembuatan tagihan, verify/verify, verify/reject, dan biaya rutin terpilih. Regresi Phase 6B menguji POST/POST dan POST/MATCH, idempotensi serta rollback; Phase 6A menjaga receipt duplicate. Hasil ini **tidak membuktikan PostgreSQL nyata**.

Sebelum rollout, buat database PostgreSQL disposable terpisah. Jalankan migration runner existing serta `scripts/postgres_smoke_test.py` / `postgres_smoke_test_v2.py` sesuai petunjuk dan guard script, dengan credential staging. Tambahkan eksekusi journey concurrency yang sama menggunakan koneksi PostgreSQL. Periksa FK, unique index, row locks, dan rollback dengan audit failure. Jangan jalankan skrip tersebut terhadap production untuk “sekadar mengetes”. Tidak ada server PostgreSQL lokal yang tersedia selama pengerjaan paket ini.

## Batas verifikasi

- Tidak ada transfer, activation provider, WhatsApp signup nyata, pesan pelanggan, push, deploy, maupun migrasi production.
- Tidak ada fixture struk/myBCA pelanggan nyata; gambar/PDF buatan digunakan untuk menguji parser, batas dan keamanan, bukan akurasi OCR dunia nyata.
- Browser cloud menolak localhost; pemeriksaan visual mobile/desktop dan screenshot baru tidak tersedia.
- Instalasi dependency bersih melalui internet belum diverifikasi. Gunakan versi yang memenuhi requirements, terutama Flask 3.1+.
- Provider model dan layanan email/Meta harus diperiksa di staging sesuai akun Anda sendiri.
