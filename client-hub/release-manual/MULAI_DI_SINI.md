# Paket akhir Kilas Works

Paket ini berisi **source aplikasi lengkap**, bukan hanya patch. Perubahan rilis ini berada di `source/client-hub/`. Source root tetap disertakan untuk dependensi bersama dan aplikasi Brain yang sudah ada. Website pemasaran eksternal tidak diubah.

## Urutan membaca

1. Baca dokumen ini dan `CONFIG_EXAMPLE.txt`.
2. Ikuti `PANDUAN_UJI_ID.md` pada database baru yang bisa dibuang.
3. Baca `PANDUAN_PENGGUNA_ID.md` untuk alur pelanggan dan admin.
4. Gunakan `DEPLOYMENT_ID.md` untuk menyiapkan staging dan rencana production; jangan melewati backup dan pengujian PostgreSQL.
5. Baca `HASIL_UJI.md` untuk jumlah per suite dan pemeriksaan tertahan, serta `ARSITEKTUR_DAN_AUDIT.md` untuk batas layanan.
6. Lihat daftar file, commit, dan checksum di `review-metadata/`; daftar tindakan Anda tersedia di `FINAL_REVIEW_METADATA/manual-configuration-required.txt`.

## Yang sudah tersedia

- Halaman publik Produk: Brain, Finance, serta layanan kreatif/sistem dengan harga dan cakupan yang bersumber dari konfigurasi/katalog server.
- Pilihan produk bertahan melewati login/daftar tanpa menerima URL redirect bebas. Bisnis yang sudah dimiliki bisa digunakan kembali; pesanan pribadi kreatif tidak wajib memiliki bisnis.
- Finance Rp149.000 per periode 30 hari, berdiri sendiri dari Brain. Trial opsional 7 × 24 jam, satu kali per bisnis, mulai setelah pengguna menyetujui ketentuan. Tidak ada penagihan otomatis.
- Setup Kas/Bank/E-Wallet dan saldo awal tanpa membuat transaksi pendapatan fiktif.
- Tagihan langganan Finance → transfer manual → bukti gambar → pemeriksaan admin → aktivasi/perpanjangan atomik. Ini berbeda dari Invoice Pelanggan di Finance.
- Setelah masa aktif habis: baca data/laporan dan ekspor; pencatatan, AI, perubahan staging, dan tautan berbagi baru diblokir oleh server. Tautan publik lama tetap tunduk pada TTL dan validasi sebelumnya.
- Assistant Phase 6C tetap mengoordinasikan Analyst, Operator, Struk, dan Mutasi. Tidak ada posting otomatis.
- Biaya rutin sekarang ditinjau dan dipilih berdasarkan kejadian yang benar-benar sudah dibayar. Jadwal yang tidak dipilih tetap menunggu.
- Dashboard menampilkan bisnis terpilih, status produk, dan pesanan yang benar-benar ada.

## Yang belum berarti siap diluncurkan tanpa pemeriksaan

Tidak ada push, deploy, pembayaran nyata, atau migrasi production selama pengerjaan. Nama ZIP `FINAL_READY_PACKAGE` berarti paket source siap ditinjau dan dipasang melalui proses terkendali; **bukan sertifikat bahwa production sudah diuji**.

Belum diverifikasi: koneksi Anthropic nyata, akurasi struk/myBCA nyata, transfer bank nyata, PostgreSQL/concurrency PostgreSQL nyata, pemasangan dependensi dari lingkungan kosong, dan tampilan visual browser mobile/desktop. Browser yang tersedia menolak localhost (`ERR_BLOCKED_BY_CLIENT`); tidak dibuat screenshot buatan. Pengujian DOM JavaScript bukan pengujian visual.

Mode default tetap `internal_beta`; rilis tidak otomatis membuka Finance kepada semua pelanggan. Aktifkan `KILAS_FINANCE_ACCESS_MODE=self_service` secara sengaja setelah staging dan migrasi siap. Isi konfigurasi pembayaran agar pelanggan benar-benar memperoleh petunjuk transfer yang benar.

## Isi paket

- `source/`: source versi final, dependensi, template/static, seluruh migrasi, test, dan source root yang tidak diubah.
- `manual/`: panduan bahasa Indonesia dan contoh konfigurasi tanpa kredensial nyata.
- `review-metadata/`: manifest, hasil pengujian, diff kumulatif dan diff rilis, checksum, serta daftar pengecualian.
- `FINAL_REVIEW_METADATA/`: ringkasan teks commit, log/status Git, file berubah, tes, migrasi, dan konfigurasi yang masih perlu diisi.

File `.env` nyata, database, cache, lingkungan virtual, `node_modules`, arsip lama, patch historis, screenshot historis dan dokumen hasil kerja yang bukan aset aplikasi tidak ikut. Aset katalog publik yang dipakai aplikasi tetap ikut. Rincian pengecualian tercatat.

**Mengunggah ZIP ke GitHub tidak otomatis menerapkan source di dalamnya.** Gunakan prosedur perbandingan dan penerapan aman pada panduan deployment.
