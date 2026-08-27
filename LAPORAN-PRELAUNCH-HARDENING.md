# Laporan Final Pre-Launch Update — Kilas Works AI Admin

Checkpoint git lokal sebelum cycle ini: `checkpoint-before-prelaunch-hardening`.
Commit hasil cycle ini: `ef53516` (lokal saja, **belum di-push/deploy**).

## 1. File yang diubah
- `app.py` — PRICING_CONFIG restructure, ATURAN HARGA rewrite, honesty/demo prompt, purpose=demo, `meeting_mode_label()` helper.
- `generate_katalog_pdf.py` — section AI Admin jadi Basic/Pro, loop bundle diupdate.
- `katalog.pdf` — regenerated (4 halaman, sudah divisualkan, tidak ada cutoff/overflow).
- `landing-page-kilasworks.html` — tambah perbandingan AI Admin Basic/Pro (tanpa harga) + CTA "Coba Demo AI Admin".
- `test_language_layer.py`, `test_sales_engine.py` — guard assertion diupdate ke struktur baru yang disahkan.
- `test_prelaunch_hardening.py` — file baru, 19 test.

## 2. Final pricing config
Semua harga di PRICING_CONFIG sekarang persis sama dengan daftar FINAL yang kamu kirim (AI Admin Basic Rp499rb, Pro Rp999rb, seluruh bundle Content+AI, AI+Ads, Content+AI+Ads, Website, Domain, Event). Tidak ada harga yang di-hardcode dobel di luar PRICING_CONFIG — katalog PDF dan pricing text block ke bot sama-sama baca dari sumber ini.

## 3. Katalog PDF
Berhasil dibangun ulang (4 halaman). Sudah dicek visual per halaman (render ke PNG) — tidak ada teks kepotong/overflow, tabel bundle Content+AI Admin dan Ads Bundle sudah menampilkan baris baru (Basic tier), Domain & Hosting dan Event Photo & Video di halaman terakhir rapi.

## 4. Landing page
Ditambahkan: perbandingan singkat AI Admin Basic vs Pro di kartu layanan (tanpa angka harga, sesuai instruksi), dan CTA "Coba Demo AI Admin" yang mengarah ke `/demo` (di hero dan di kartu layanan). Tidak ada testimoni/logo/portofolio palsu — sudah dicek ulang, masih bersih. Mobile responsive dipertahankan (grid tier baru otomatis stack di layar kecil).

## 5. Sinkronisasi AI Basic vs Pro
Katalog, landing page, dan system prompt bot customer semuanya konsisten: Basic = respons otomatis dasar (FAQ, info produk/harga/jam, katalog); Pro = semua itu + appointment, owner command, payment conversation, vision, dsb. Tidak ada fitur yang belum production-ready (reminder otomatis, follow-up otomatis tanpa syarat) yang diklaim sebagai fitur aktif tanpa catatan.

## 6. Perilaku harga di customer bot
Aturan lama ("tahan harga, jangan langsung jawab") sudah diganti total. Sekarang: belum ditanya harga → jangan buru-buru dump; ditanya harga satu paket → jawab langsung angka pastinya; ditanya satu paket → jangan sekalian dump semua; minta full price list → baru kasih semua/katalog. Diverifikasi lewat test end-to-end ("Growth berapa?" → jawaban mengandung "2.750.000").

## 7. Test multibahasa
Instruksi auto-detect bahasa (ID/EN, termasuk switch di tengah chat) untuk customer bot sudah ada dari cycle sebelumnya dan tidak disentuh (masih pass di test_language_layer.py, 12 test). Untuk demo, instruksi auto-detect serupa ditambahkan ke DEMO_SYSTEM_PROMPT — dikonfirmasi ada teks-nya, tapi verifikasi end-to-end aktual (butuh panggilan API sungguhan) belum dilakukan karena demo memanggil Claude API langsung, bukan lewat fungsi yang gampang di-mock untuk assert isi balasan bahasa Inggris — instruksi ada, tapi actual model behavior sebaiknya dicoba manual sebelum launch.

## 8. Test demo
Diverifikasi: onboarding tetap 3 pertanyaan, isolasi total dari data production (appointments/customers/conversations tetap kosong setelah demo dipakai), reset demo, quota harian/sesi — semua dari test_demo_ux.py (existing) tetap pass, ditambah 1 test baru khusus isolasi.

## 9. Test live demo appointment
Diverifikasi end-to-end: `[MEETING_PREFERENCE: ...|purpose=demo]` → tersimpan sebagai purpose="demo" → owner dapat notifikasi dengan wording "ingin live demo AI Admin hari [hari]" (bukan "online meeting"). Tanpa purpose= (perilaku lama) tetap default "sales" dan wording "online meeting" — no regresi. Nilai purpose yang tidak dikenal fallback aman ke "sales".

## 10. Test appointment availability
Alur owner-availability existing (dari cycle sebelumnya) tetap pass semua — termasuk RULE 1-6 di test_appointment_flow_fix.py (exact time match, single new time = offer bukan confirm, multiple slot, dst).

## 11. Test date lock
Dikonfirmasi ulang khusus untuk purpose=demo: tanggal (Selasa) yang di-lock di awal tidak berubah setelah owner cuma jawab "available" secara generik — dan tidak pernah berubah jadi hari lain (mis. Minggu).

## 12. Test owner access
Semua kapabilitas owner dari cycle-cycle sebelumnya (history, kirim pesan/katalog/media, partial name matching, active context, konfirmasi pembayaran, update meeting status) tidak disentuh di cycle ini dan seluruh test file terkait (test_owner_catalog.py, test_owner_nlu.py, test_appointments.py) tetap 100% pass.

## 13. Test notifikasi customer→owner
Wording notifikasi untuk live demo sudah benar (lihat poin 9). Alur notifikasi existing (hot lead, appointment, payment, dsb — dari cycle-cycle sebelumnya) tidak diubah dan tetap pass.

## 14. Test pembayaran
PAYMENT_CONFIG tidak disentuh (dikunci lewat regression guard test), alur DP/full/PENDING_VERIFICATION dari cycle sebelumnya tetap pass tanpa perubahan.

## 15. Status cron follow-up
**BELUM TERKONFIRMASI aktif.** Kode `/cron/followups` sudah lengkap dan gated `CRON_SECRET`, tapi tidak ada bukti ada cron eksternal (cron-job.org / Render Cron Job) yang benar-benar memanggilnya secara rutin. Karena itu, wording "follow-up otomatis" di feature list AI Admin Pro sengaja diperhalus jadi "Follow-up dasar ke customer yang sempat diam (aktif setelah scheduler follow-up disetup owner)" — supaya tidak overclaim.

## 16. Status reminder meeting
Kode reminder (H-1 dan opsional hari-H) sudah ada dan sudah ditest dari cycle sebelumnya (test_appointment_reminders.py, tetap pass), tapi **sengaja tidak dicantumkan** sebagai fitur aktif di katalog/landing page/prompt — karena aktivasinya bergantung pada cron eksternal yang sama, yang belum terkonfirmasi jalan.

## 17. Model Claude yang dipakai
`MODEL_FAST = claude-haiku-4-5-20251001` (default balasan teks customer & owner), `MODEL_PRIMARY = MODEL_FALLBACK = claude-sonnet-4-6` (vision & fallback). Semua lewat env var dengan default, terpusat.

## 18. Model deprecated yang ditemukan
Tidak ada. `claude-3-5-haiku-20241022` (retired 19 Feb 2026) sudah dibersihkan di cycle sebelumnya — hanya tersisa sebagai catatan komentar historis di kode, bukan referensi aktif.

## 19. Jumlah test lama yang PASS
Semua 10 file test lama: 100% PASS (tidak ada regresi). Ada 2 assertion regression-guard yang sengaja diupdate (bukan revert) karena memang mengunci struktur PRICING_CONFIG lama yang sudah diotorisasi berubah di cycle ini.

## 20. Jumlah test baru yang PASS
19 test baru di `test_prelaunch_hardening.py` — semua PASS.

## 21. Aksi manual yang perlu kamu lakukan
- **Cron follow-up/reminder**: setup cron eksternal (cron-job.org atau Render Cron Job) yang memanggil `/cron/followups?key=<CRON_SECRET>` secara rutin (misal tiap 15-30 menit), kalau mau follow-up otomatis dan reminder meeting benar-benar jalan. Sebelum itu disetup, JANGAN cantumkan sebagai fitur aktif ke calon klien.
- **Deploy manual**: karena repo lokal sesi ini tidak terhubung ke repo GitHub yang sebenarnya, kamu perlu update file-file yang berubah (app.py, generate_katalog_pdf.py, landing-page-kilasworks.html) secara manual ke repo GitHub asli (lewat web editor atau cara biasanya), baru Render akan auto-redeploy.
- **Landing page**: pastikan sudah live di kilasworks.id dengan versi terbaru ini setelah kamu review.
- **WhatsApp Business API**: pastikan sudah keluar dari mode test kalau mau dipakai untuk outreach ke klien beneran (temuan dari cycle sebelumnya, belum dikonfirmasi ulang di cycle ini).
- **Cek manual demo multibahasa**: coba langsung `/demo` dengan pesan berbahasa Inggris untuk memastikan model benar-benar switch bahasa sesuai instruksi baru (instruksi sudah ada di prompt, tapi belum dites end-to-end lewat panggilan API sungguhan).

## 22. Risiko yang tersisa
- Follow-up & reminder meeting masih bergantung pada setup cron eksternal yang belum dikonfirmasi — kalau belum disetup, fitur ini benar-benar tidak akan jalan meski kodenya lengkap.
- Perilaku bahasa demo belum divalidasi lewat panggilan API sungguhan (hanya divalidasi lewat isi instruksi prompt).
- Karena arsitektur berbasis prompt (LLM memutuskan tag mana yang dikirim), ada risiko residual kecil model tidak selalu 100% konsisten mengikuti instruksi baru (misal lupa sertakan `purpose=demo`) — sudah dimitigasi dengan default fallback yang aman ("sales"), jadi kalaupun terlewat, perilaku tetap seperti online meeting biasa, bukan error.
- Belum ada uji beban/QA manual langsung dengan WhatsApp asli (test yang dilakukan semuanya lewat webhook simulasi otomatis) — disarankan tetap coba manual beberapa skenario dari daftar QA di bagian awal permintaan sebelum benar-benar mulai jualan ke klien asing.

**Belum di-deploy/push** sesuai instruksi — silakan review dulu file yang sudah dikirim.
