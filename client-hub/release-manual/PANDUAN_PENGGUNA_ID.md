# Panduan pengguna dan admin

## Masuk dari produk

Buka halaman utama Client Hub; pengguna yang belum login diarahkan ke **Produk**. Di sini manfaat, harga, syarat, dan tombol pilih produk ditampilkan sebelum pendaftaran. Pilih Brain, Finance, atau layanan kreatif/sistem. Sesudah login/daftar, pilihan diteruskan ke halaman bisnis/brief tanpa membuat order atau trial secara diam-diam.

Pilih bisnis yang sudah ada. Jika memang bisnis berbeda, buka **Buat bisnis baru** dan isi namanya. Dua bisnis dengan nama sama tetap dua bisnis berbeda; nama bukan identitas. Pengiriman ulang formulir setup yang sama memakai identitas yang sama. Untuk pesanan kreatif pribadi, pilihan **tanpa bisnis** tetap tersedia.

Beranda menampilkan bisnis yang dipilih. Gunakan pemilih bisnis untuk berpindah. Navigasi utama: **Beranda**, **Produk & Layanan**, **Pesanan**, **Tagihan & Akun**. Menu pemeriksaan admin hanya tersedia untuk admin.

## Mulai Finance

1. Pilih Finance dan bisnisnya. Tidak perlu membeli Brain atau menghubungkan WhatsApp.
2. Simpan nama pencatatan Kas/Bank/E-Wallet. Saldo awal boleh nol atau nominal rupiah bulat; saldo awal bukan transaksi pendapatan/pengeluaran. Ini bukan live bank connection.
3. Baca ketentuan lalu tekan **Mulai Trial 7 Hari** jika ingin mencoba. Trial tidak dimulai ketika membuka halaman, login, atau mengunggah apa pun. Satu bisnis hanya mendapat satu trial, dihitung tepat 7 × 24 jam menurut waktu server. Waktu berakhir ditampilkan dalam WIB.
4. Jika langsung berlangganan, pilih **Buat Tagihan Finance**. Harga dan mata uang berasal dari server, bukan isian browser.
5. Saat aktif, buka Finance. Gunakan **AI Assistant**, **Foto Struk / PDF**, **Upload File**, atau **Catat Manual**.

Ringkasan bulan menampilkan **Uang Masuk**, **Uang Keluar**, serta **Selisih Masuk–Keluar**. Selisih itu bukan laba akuntansi. Ringkasan tagihan terlambat berasal dari invoice nyata dan menuju daftar terfilter, bukan angka contoh.

## Assistant: tinjau dahulu, catat setelah konfirmasi

- Pertanyaan laporan → Analyst read-only; angka laporan dihitung server.
- Perintah seperti “catat bensin 300 ribu” → usulan Operator. Pilih tindakan, akun, kategori/invoice; siapkan draft; periksa; konfirmasi. Assistant tidak memilih referensi tenant untuk mengizinkan transaksi.
- **Foto Struk** membuka pemilih kamera yang ramah ponsel. **Upload File** tetap bisa memakai galeri/PDF/CSV tanpa dipaksa kamera. Dukungan kamera sesungguhnya bergantung browser/perangkat.
- File ambigu, misalnya PDF dengan pesan “tolong cek ini”, meminta pilihan **Struk/Pengeluaran** atau **Mutasi Bank**. Sebelum pilihan itu tidak ada ekstraksi berbayar/staging.
- Percakapan dan file di composer bersifat sementara di memori halaman. Refresh bisa menghapusnya. Jika file hilang, pilih ulang; aplikasi tidak mengklaim masih menyimpannya.

### Struk

Satu JPG/JPEG/PNG/WEBP atau PDF, maksimal 5 MiB; PDF maksimal 10 halaman. Validasi memakai byte nyata dan PDF diparse terisolasi. AI gagal/tidak terbaca mengarah ke review manual, bukan transaksi otomatis.

Periksa tanggal, nominal, deskripsi, pilih akun/kategori, lalu tekan **Catat Pengeluaran**. Token review terikat pengguna dan bisnis serta berlaku 10 menit. Struk identik dilindungi hash. Transaksi yang kemudian dibatalkan tidak diam-diam dibuat lagi dari sumber yang sama.

### Cocokkan Mutasi Bank

- CSV UTF-8/UTF-8 BOM maksimal 2 MiB: parsing deterministik, tanpa AI.
- PDF maksimal 10 MiB/20 halaman: teks aman bila cukup, jika tidak document vision Anthropic; satu permintaan ekstraksi terbatas.
- Maksimal 10 gambar JPG/JPEG/PNG/WEBP, masing-masing 5 MiB, total 25 MiB.

Pilih akun untuk seluruh import → upload → ekstraksi → **REVIEW**. Koreksi semua baris. Klik **Mulai Rekonsiliasi** secara eksplisit untuk membuka tahap pencocokan. Setiap baris diputuskan manusia: cocokkan transaksi existing, catat baru, abaikan, atau biarkan belum cocok.

Upload, review, membuka tahap pencocokan, MATCH, dan IGNORE tidak menambah uang ledger. POST menambah satu transaksi setelah pilihan kategori dan konfirmasi. Kandidat hanya satu bisnis/akun, arah dan nominal sama, jarak tanggal maksimal tiga hari, maksimal sepuluh kandidat per baris. Tidak ada skor AI atau auto-match. Dua transaksi identik tetap dua baris; overlap hanya ditandai untuk diperiksa.

File sumber mutasi tidak diarsipkan. Hanya staging normalisasi yang disimpan. `COMPLETED` berarti semua baris mendapat keputusan manusia, bukan jaminan laporan bank pasti benar.

### Jika koneksi gagal

Jika konfirmasi belum pasti, periksa riwayat/status lalu ulangi **konfirmasi yang sama**, jangan membuat draft atau upload pengganti dengan harapan “memperbaiki” hasil yang belum jelas. Identitas idempoten struk, Operator, mutasi, dan tagihan tetap dipakai. Token kedaluwarsa tidak dapat dipaksa diterima; periksa dulu riwayat sebelum mulai review baru.

## Biaya rutin dan Invoice Pelanggan

Aturan biaya rutin tidak otomatis mencatat pembayaran. Buka **Tinjau Biaya Rutin**, lihat tanggal, nominal, akun dan kategori; centang pengeluaran yang benar-benar dibayar; tekan **Catat Pengeluaran Terpilih**. Ditampilkan kejadian berikutnya per aturan, maksimal 100. Untuk tunggakan berurutan, tinjau kejadian berikutnya setelah kejadian sebelumnya selesai. Tidak dipilih berarti tetap menunggu; tidak dilompati. Transaksi VOID tidak dibuat ulang.

**Invoice Pelanggan** adalah tagihan usaha kepada pelanggannya. Pembayarannya baru masuk ledger usaha setelah pencatatan eksplisit. Ini berbeda dari **Tagihan Kilas Works**, yaitu pembayaran pelanggan aplikasi kepada Kilas Works. Membayar langganan Finance tidak otomatis menjadi pendapatan/pengeluaran ledger usaha.

## Membayar atau memperpanjang Finance

1. **Tagihan & Akun → Tagihan Finance → Buat Tagihan Finance**.
2. Periksa nominal dan rekening penerima yang ditampilkan. Jika belum ada rekening, minta pengelola mengisi konfigurasi; jangan transfer ke rekening yang ditebak.
3. Transfer sesuai tagihan menggunakan bank Anda sendiri. Aplikasi tidak memindahkan uang.
4. Unggah bukti gambar maksimal 5 MiB. Status menjadi menunggu pemeriksaan. Bukti tersimpan khusus sebagai bukti pembayaran langganan, berbeda dari struk/mutasi yang tidak diarsipkan.
5. Admin memverifikasi pembayaran nyata atau menolak bukti. Upload/rejection tidak mengaktifkan langganan.
6. Setelah verifikasi, periode 30 hari ditambahkan dari akhir periode berbayar yang masih aktif, atau dari saat verifikasi jika periode lama sudah habis. Trial yang tersisa tidak ditambahkan ke periode berbayar pertama.

Tidak ada penagihan otomatis. Tagihan menunggu pemeriksaan tidak mengurangi sisa masa aktif. Pembayaran yang sama tidak boleh dipakai lagi; file bukti identik dilindungi, dan admin tetap wajib memeriksa apakah transfer sungguhan sudah pernah digunakan meskipun screenshot berbeda.

Saat kedaluwarsa, data historis, laporan dan ekspor tetap tersedia. Semua pencatatan baru/perubahan/AI diblokir pada route dan service; bahkan draft yang dibuat sebelum habis tidak dapat diposting sesudah habis. Melakukan perpanjangan tidak mengubah status Brain.

## Brain

Brain tetap Rp499.000/bulan, tanpa trial. Pilih/gunakan bisnis → lengkapi fakta penting dan knowledge → simulasi → submit/review → konfirmasi pembuatan pesanan/pembayaran → verifikasi dan provisioning/koneksi sesuai alur existing.

“Data setup lengkap, sedang ditinjau” tidak berarti WhatsApp aktif. Approval setup juga tidak membuktikan pembayaran. Ikuti status dan langkah berikutnya pada review; jangan menganggap demo atau persentase setup sebagai aktivasi layanan. Paket Basic/Pro lama tidak ditawarkan kembali.

## Layanan kreatif dan sistem

Pilih kategori/paket → login → bisnis yang sesuai atau pesanan pribadi → brief → tinjau scope dan biaya transport yang berlaku. Harga fixed mengikuti server; layanan custom menunggu penawaran dan persetujuan sebelum checkout. Setelah pembayaran, progress mengikuti status pesanan nyata. **Pesanan** menyimpan jalur untuk melanjutkan brief, melihat penawaran, membayar, dan melihat progress; tidak perlu membuat order baru setiap kembali.

## Admin pemeriksa Finance

Login sebagai `KILAS_ADMIN` → **Verifikasi Finance**. Antrean menampilkan maksimal 200 bukti menunggu pemeriksaan. Buka tagihan dan unduh bukti. Periksa mutasi penerima, nominal, identitas dan duplikasi transfer secara nyata, lalu pilih **Verifikasi Pembayaran Finance** atau **Tolak Bukti**. AI tidak menyetujui pembayaran. Konfirmasi ulang/verifikasi bersamaan tidak menambahkan periode dua kali. Tidak ada perubahan ke Brain, project kreatif, atau ledger pelanggan dari tindakan ini.
