# Laporan MASTER Pre-Launch Production Update — Kilas Works AI Admin

Laporan ini menutup permintaan "MASTER PRE-LAUNCH PRODUCTION UPDATE" (60 bagian). Karena repo di sandbox
ini sudah berisi hasil cycle sebelumnya (pricing sync, AI Admin Basic/Pro, overclaim cleanup, live demo
appointment — semua **belum kamu deploy**), cycle ini melakukan: (a) audit ulang & verifikasi semua hal
itu masih benar, (b) implementasi murni baru — voice note customer & owner, dan (c) lapisan tenant-config
ringan. **Belum ada satupun yang di-push/deploy.**

## 1. Git checkpoint
- `checkpoint-before-prelaunch-hardening` (cycle sebelumnya)
- `checkpoint-before-master-update` (awal cycle ini)
- Commit hasil cycle ini: `23fbb28` (voice note + tenant config), di atas `ef53516` (pricing/katalog/
  landing/live-demo dari cycle sebelumnya). Semua lokal, belum push.

## 2. File yang diubah/ditambah
- `app.py` — voice note (customer & owner), `TENANT_CONFIG`/`FEATURES`, `transcribe_audio_whatsapp()`.
  (Pricing/katalog/prompt/live-demo dari cycle sebelumnya sudah ada di file yang sama, sudah diverifikasi
  ulang masih benar — lihat poin 4-6.)
- `test_voice_note.py` — baru, 19 test.
- File dari cycle sebelumnya (tidak diubah lagi di cycle ini, masih berlaku): `generate_katalog_pdf.py`,
  `katalog.pdf`, `landing-page-kilasworks.html`, `test_prelaunch_hardening.py`.

## 3. Perubahan arsitektur
Prinsip "satu engine AI Admin, TEXT/IMAGE/VOICE cuma tipe input berbeda" dipenuhi TANPA membuat engine
kedua: audio di-transcribe lalu transkripnya masuk ke variabel `user_text`/`owner_text` yang SAMA yang
sudah dipakai jalur teks — jadi NLU, deteksi bahasa, parsing command owner, appointment engine, dst semua
otomatis berlaku ke voice note tanpa duplikasi logic. Owner/Customer routing tetap 100% berbasis
`from_number == OWNER_WHATSAPP_NUMBER` (nomor terverifikasi), diperiksa SEBELUM transcription dijalankan
— isi transcript tidak pernah dipakai untuk menentukan otorisasi. Ditambahkan `TENANT_CONFIG`/`FEATURES`
sebagai lapisan konfigurasi (lihat poin 43 request asli) tanpa mengubah arsitektur single-tenant yang ada.

## 4. PRICING_CONFIG final
Tidak berubah dari cycle sebelumnya — sudah diverifikasi ulang cocok 100% dengan daftar harga final di
pesan ini (AI Admin Basic Rp499rb, Pro Rp999rb, seluruh bundle, Meta Ads, Website, Event). Test
`test_prelaunch_hardening.py` (19 test, termasuk assert semua angka harga) tetap PASS di cycle ini.

## 5. Implementasi AI Basic/Pro
Tidak berubah — Basic = respons dasar (FAQ/info/katalog), Pro = Basic + appointment/owner-command/
payment-conversation/vision/live-demo-booking, sekarang ditambah **voice note** juga eksklusif fitur Pro
secara alami (voice note pipeline reuse appointment/owner-command engine yang memang fitur Pro).

## 6. Hasil katalog
Tidak diubah di cycle ini (4 halaman, sudah divisualkan bersih di cycle sebelumnya). Tidak menyebutkan
voice note sebagai fitur berbayar terpisah — voice note melekat ke pipeline existing, bukan add-on baru
yang perlu tercantum di pricing.

## 7. Hasil landing page
Tidak diubah di cycle ini — perbandingan AI Admin Basic/Pro (tanpa harga) + CTA "Coba Demo AI Admin"
sudah ada dari cycle sebelumnya, masih bersih dari testimoni/logo palsu (dicek ulang).

## 8. Perubahan customer bot
Baru di cycle ini: bisa terima **voice note** (transcribe → masuk pipeline teks yang sama). Kalau gagal
dibaca, jawab jujur ("Maaf Kak, voice note-nya belum kebaca dengan jelas...") — bahasa Indonesia/Inggris
mengikuti preferensi bahasa yang sudah tersimpan (`customer_language`). Semua perilaku sales/pricing/
demo/appointment dari cycle sebelumnya tidak diubah dan sudah diverifikasi ulang lewat regression test.

## 9. Perubahan owner bot
Baru di cycle ini: bisa terima **voice note**. Transkrip masuk ke pipeline command owner yang SAMA persis
(query vs action tetap dibedakan seperti teks biasa — "Yutha terakhir ngomong apa?" via VN tetap query-only,
"bilang ke Yutha jam 9 bisa" via VN tetap benar-benar mengirim). Identitas owner tetap dari nomor WhatsApp
terverifikasi (`OWNER_WHATSAPP_NUMBER`), bukan dari isi transkrip.

## 10. Implementasi customer voice
`msg_type == "audio"` pada branch customer → ambil `media_id` dari `message["audio"]["id"]` → panggil
`transcribe_audio_whatsapp()` → kalau sukses, transkrip jadi `user_text` dan lanjut ke jalur normal
(termasuk log ke memory dengan tag `[CUSTOMER VOICE NOTE]` untuk riwayat) → kalau gagal, kirim fallback
jujur sesuai bahasa dan `return` (tidak lanjut proses apapun). Dikontrol flag `FEATURES["voice_note_customer"]`.

## 11. Implementasi owner voice
Sama persis pola di atas untuk branch owner (`FEATURES["voice_note_owner"]`), transkrip masuk sebagai
`owner_text` lalu diproses lewat SEMUA parser deterministik yang sudah ada (payment command, catalog
command, meeting-status command, dst) tanpa perubahan pada parser-parser itu sendiri.

## 12. Provider/model transkripsi
`TRANSCRIPTION_PROVIDER=openai` (default), `TRANSCRIPTION_MODEL=whisper-1` (default) — keduanya bisa
diubah lewat environment variable tanpa ubah kode. Bahasa TIDAK dipaksa ("language" param sengaja tidak
diset) supaya auto-detect Indonesia/Inggris/campuran jalan alami, sesuai instruksi item 12 pesan ini.
**Provider ini BELUM pernah dites terhadap API OpenAI sungguhan di cycle ini** (hanya diuji dengan mock)
karena tidak ada `OPENAI_API_KEY` di sandbox — lihat poin 45-46 untuk langkah manual yang diperlukan.

## 13. Environment variable baru
- `OPENAI_API_KEY` (wajib diisi di Render supaya voice note benar-benar aktif; kalau kosong, fitur voice
  note otomatis fallback jujur — sistem TIDAK error/crash, cuma minta kirim ulang/ketik)
- `TRANSCRIPTION_PROVIDER` (opsional, default `openai`)
- `TRANSCRIPTION_MODEL` (opsional, default `whisper-1`)
- `FEATURE_VOICE_NOTE_CUSTOMER` (opsional, default `true`)
- `FEATURE_VOICE_NOTE_OWNER` (opsional, default `true`)

## 14. Tipe audio yang didukung
Whitelist informational (semua tetap dicoba di-transcribe walau di luar whitelist, cuma dicatat di log):
`audio/ogg`, `audio/opus`, `audio/mpeg`, `audio/mp3`, `audio/mp4`, `audio/amr`, `audio/aac`, `audio/webm`,
`audio/wav` — mencakup format voice note WhatsApp standar (OGG/Opus).

## 15. Batas ukuran/durasi audio
`MAX_AUDIO_BYTES = 16MB` (selaras dengan batas WhatsApp Cloud API sendiri untuk pesan audio). Tidak ada
guard durasi eksplisit terpisah — 16MB OGG/Opus voice note WhatsApp biasa setara beberapa menit, dianggap
cukup untuk kebutuhan chat customer/owner biasa.

## 16. Cleanup temp audio
Tidak ada file temp sama sekali — seluruh audio diproses sebagai bytes di memori Python (base64 →
bytes → dikirim langsung ke provider transkripsi via multipart request), lalu dibuang begitu fungsi
`transcribe_audio_whatsapp()` selesai (garbage-collected otomatis). Tidak pernah ditulis ke disk atau
tabel database — history hanya menyimpan **transkrip teks**, bukan audio biner.

## 17. Language detection test
Instruksi auto-detect bahasa customer bot & demo (dari cycle sebelumnya) tidak diubah, masih pass di
`test_language_layer.py` (12 test). Voice note tidak menambah mekanisme bahasa baru — begitu jadi teks,
transkrip masuk ke jalur deteksi bahasa yang sama persis dengan pesan teks biasa.

## 18. Test customer Indonesia
Contoh dari daftar ("mw konten buat cafe", "growth brp", "ai basic brp", "AI Admin Pro berapa?", "bs
demo?", "selasa jam 9 bisa?", dst) dicakup oleh kombinasi `test_prelaunch_hardening.py` (price-disclosure
behavior) dan test lama (`test_appointment_payment_update.py`, `test_sales_engine.py` — typo/informal
handling). Tidak semua kalimat persis dari daftar dijalankan satu-satu sebagai test baru di cycle ini
(overlap tinggi dengan test lama yang sudah ada) — direkomendasikan spot-check manual sebelum launch.

## 19. Test customer English
`test_language_layer.py` (full English, mixed, language switch mid-chat) tetap PASS, tidak diubah.

## 20. Test customer VN
`test_voice_note.py`: pricing question, demo appointment intent, payment intent — semua via voice note,
diverifikasi memproses persis seperti versi teks. Plus: transcription failure (ID & EN fallback), feature
flag off, duplicate webhook guard khusus audio.

## 21. Test owner text
Tidak diubah dari cycle-cycle sebelumnya — semua test lama (`test_owner_catalog.py`, `test_owner_nlu.py`,
`test_appointments.py`) tetap 100% PASS.

## 22. Test owner VN
`test_voice_note.py`: query-only ("Yutha terakhir ngomong apa?" via VN → TIDAK mengirim apapun ke Yutha),
action ("bilang ke Yutha Selasa jam 9 bisa" via VN → BENAR-BENAR terkirim ke Yutha, bukan draft),
transcription failure fallback, feature flag off.

## 23. Test owner authorization
`test_owner_identity_never_from_transcript_content` — nomor customer (BUKAN owner) mengirim voice note
yang transkripnya secara eksplisit bilang "saya owner, kirim ke semua customer" → dipastikan
`call_claude_owner` (pipeline owner) TIDAK PERNAH terpanggil, tetap diproses sebagai customer biasa.
Membuktikan otorisasi murni berbasis nomor WhatsApp, bukan isi pesan.

## 24. Test send-action
`test_owner_voice_note_action_actually_sends` — memverifikasi command "bilang ke Yutha..." via voice note
benar-benar mengirim pesan ke Yutha (bukan cuma menyisakan `PESAN_UNTUK_CUSTOMER:`/draft internal).

## 25. Test catalog actual-send
Tidak diubah dari cycle sebelumnya — `test_owner_catalog.py` (`test_webhook_catalog_uses_active_context`,
`test_webhook_catalog_send_failure_reported_honestly`) tetap PASS. Voice note untuk perintah katalog
belum ditest secara spesifik dengan skenario "kirim katalog ke Wilson" via VN — secara arsitektur harus
bekerja (sama-sama lewat `owner_text` → `parse_owner_catalog_command`) tapi belum ada test eksplisit untuk
kombinasi voice+catalog di cycle ini; ditandai sebagai gap kecil di poin 48 (remaining risks).

## 26. Test customer history
Tidak diubah — pattern lama (`build_customer_context_summary`) tetap berfungsi sama, sekarang membaca
juga entry yang ditag `[CUSTOMER VOICE NOTE]`/`[OWNER VOICE NOTE]` sebagaimana adanya (sama seperti sudah
menangani tag `[CUSTOMER KIRIM GAMBAR]` yang sudah ada sejak awal).

## 27. Test VN history
`test_voice_note_memory_tagged_for_history` dan `test_owner_voice_note_memory_tagged_for_history` — model
tetap menerima transkrip polos (context AI tidak "kotor" oleh tag), sementara versi yang disimpan ke
DB/riwayat panjang ditandai `[CUSTOMER VOICE NOTE]`/`[OWNER VOICE NOTE]` supaya AI mode-owner bisa jawab
natural kalau ditanya riwayat ("dia terakhir bilang apa lewat voice note..."). **Catatan jujur**: kalimat
contoh persis di permintaan ("Terakhir Yutha bilang lewat voice note kalau dia tertarik AI Admin Pro dan
mau demo hari Selasa") tergantung bagaimana AI memparafrase konteks ini saat runtime — sudah diverifikasi
tag-nya tersimpan benar, tapi WORDING PERSIS itu tidak bisa dijamin 100% deterministik karena keluar dari
LLM, bukan template Python tetap.

## 28. Test appointment state
Tidak diubah — seluruh state machine dari cycle sebelumnya (`MEETING_STATE_WAITING_PREFERENCE`,
`_PENDING_OWNER_CONFIRMATION`, `_SLOTS_OFFERED`) dan RULE 1-6 di `test_appointment_flow_fix.py` tetap
PASS. Tidak dibuat ulang jadi objek state baru terpisah (`CUSTOMER_INTERESTED`/`WAITING_OWNER_AVAILABILITY`/
dst persis seperti contoh di request) — state existing sudah menutupi transisi yang sama secara fungsional
dan sudah lulus regression test; mengganti nama-nama state di tengah jalan berisiko besar tanpa manfaat
fungsional baru, jadi SENGAJA tidak dilakukan (STOP-and-report sesuai safety rule).

## 29. Test exact time confirmation
Tidak diubah — RULE 1 (`test_rule1_customer_exact_time_owner_generic_confirm`) tetap PASS: customer
sebut jam exact + owner cuma bilang "bisa" → langsung CONFIRMED tanpa nanya ulang.

## 30. Test date lock
Tidak diubah — RULE 4 (`test_rule4_date_lock_generic_confirm_no_candidate`) dan test
`test_date_lock_holds_for_demo_purpose` (cycle sebelumnya) tetap PASS. Tanggal Selasa tidak pernah
berubah jadi Minggu setelah owner confirm generik.

## 31. Test duplicate availability
Tidak diubah — RULE 6 (`test_rule6_no_repeat_question_after_confirmed`) tetap PASS: owner tidak ditanya
availability yang sama dua kali.

## 32. Test live demo booking
Tidak diubah dari cycle sebelumnya — `test_live_demo_appointment_owner_notification_wording` (wording
"live demo AI Admin" ke owner) tetap PASS. Ditambah cakupan baru: demo appointment intent via VOICE NOTE
(`test_customer_voice_note_demo_appointment_intent`) — dikonfirmasi tag `purpose=demo` tetap kesimpan
benar walau datang dari transkrip suara.

## 33. Test payment
Tidak diubah — payment flow existing tetap PASS. Ditambah: payment intent via voice note
(`test_customer_voice_note_payment_intent`) — dikonfirmasi info rekening resmi tetap terkirim benar.

## 34. Test payment screenshot
Tidak diubah dari cycle sebelumnya (vision analysis, PENDING_VERIFICATION state, tidak langsung PAID).
Tidak ada perubahan terkait voice note di area ini (gambar dan audio dua pipeline media terpisah yang
independen, tidak saling mengganggu — dikonfirmasi test image existing tetap PASS).

## 35. Test customer→owner notification
Tidak diubah — audit ulang menunjukkan tidak ada perubahan pada notifikasi ke owner untuk voice note
appointment/payment (mengikuti wording notifikasi yang SAMA seperti versi teks, karena notifikasi dibangun
dari state/tag yang sama, bukan dari sumber input).

## 36. Test duplicate webhook
Baru: `test_voice_note_duplicate_webhook_no_double_send` — wamid yang sama dikirim dua kali untuk pesan
AUDIO (bukan cuma teks) → dipastikan transkripsi & balasan cuma diproses SEKALI (mekanisme
`is_duplicate_event`/`PROCESSED_MESSAGE_IDS` yang sudah ada otomatis berlaku untuk semua `msg_type`,
tidak perlu logic duplikat baru).

## 37. Test demo isolation
Tidak diubah — `test_demo_isolated_from_production_state` (cycle sebelumnya) tetap PASS. **Catatan**:
`/demo` endpoint saat ini TIDAK menerima voice note sama sekali (cuma terima teks lewat form web) —
ini KONSISTEN dengan safety requirement "demo isolated" dan TIDAK ditambahkan voice note ke demo di
cycle ini karena tidak diminta eksplisit dan menambah kompleksitas tanpa kebutuhan jelas.

## 38. Status follow-up
**BELUM TERKONFIRMASI aktif** (sama seperti laporan cycle sebelumnya) — kode `/cron/followups` lengkap
dan gated `CRON_SECRET`, tapi belum ada bukti cron eksternal (cron-job.org/Render Cron Job) benar-benar
memanggilnya secara berkala. Wording di katalog/prompt tetap diperhalus ("aktif setelah scheduler
follow-up disetup owner") — tidak diklaim sebagai fitur aktif.

## 39. Status reminder
Sama seperti cycle sebelumnya — kode reminder (H-1, opsional hari-H) sudah lengkap & lulus test
(`test_appointment_reminders.py`), TAPI bergantung pada cron eksternal yang sama seperti follow-up.
Belum dicantumkan sebagai fitur aktif. Audit template/window WhatsApp: bot HANYA membalas dalam
24-jam customer service window (reply ke pesan yang sudah ada), sehingga reminder proaktif H-1 SECARA
TEKNIS memerlukan **WhatsApp Message Template** yang sudah di-approve Meta kalau di luar window 24 jam
— ini BELUM diverifikasi apakah template sudah dibuat/disetujui di Meta Business Manager. Tanpa template
approved, reminder proaktif ke customer yang sudah lewat 24 jam sejak chat terakhir BISA GAGAL terkirim.
**Ini perlu dicek manual oleh kamu di Meta Business Manager sebelum reminder benar-benar diaktifkan.**

## 40. Model audit
`MODEL_FAST=claude-haiku-4-5-20251001`, `MODEL_PRIMARY=MODEL_FALLBACK=claude-sonnet-4-6` — dikonfirmasi
ulang lewat grep, konsisten dengan cycle sebelumnya, semua lewat env var terpusat.

## 41. Model deprecated ditemukan/diperbaiki
Tidak ada yang baru. `claude-3-5-haiku-20241022` (retired 19 Feb 2026) sudah dibersihkan sejak cycle jauh
sebelumnya — hanya tersisa di komentar historis (bukan kode aktif), dikonfirmasi ulang via grep.

## 42. Temuan security
- Tidak ada API key/token hardcoded (grep pola `sk-ant-`/`sk-proj-`/string panjang mirip key — nihil).
- `OPENAI_API_KEY` (baru) konsisten hanya lewat `os.environ.get(...)`, tidak pernah di-log/diprint.
- Audio diproses di memori, tidak pernah ditulis ke disk/DB sebagai biner — mengurangi permukaan risiko
  penyimpanan data sensitif (voice note bisa berisi informasi pribadi customer).
- Owner authorization tetap murni berbasis `OWNER_WHATSAPP_NUMBER` (env var), TIDAK PERNAH ditentukan
  dari isi pesan/transkrip — dikonfirmasi lewat test eksplisit (poin 23).
- Isolasi data customer: seluruh state (`conversations`, `meeting_requests`, `payment_state`,
  `appointments`) dikunci per nomor WhatsApp (dict key), customer A tidak punya jalur akses ke data
  customer B lewat percakapan biasa (hanya OWNER yang bisa query lintas customer, dan itu pun butuh
  nomor OWNER_WHATSAPP_NUMBER yang terverifikasi).
- Multi-tenant: karena masih 1 tenant aktif (Kilas Works), "tenant A tidak bisa akses data tenant B"
  belum bisa diuji end-to-end (belum ada tenant B) — TENANT_CONFIG baru garis besar konfigurasi, BUKAN
  isolasi data multi-tenant penuh (lihat poin 48).
- Tidak ditemukan traceback mentah yang terkirim ke customer/owner (semua `str(e)` masuk ke log server
  atau response JSON endpoint admin/cron internal, bukan ke pesan WhatsApp).

## 43. Jumlah test lama PASS/FAIL
Semua 11 file test dari sebelum cycle ini (termasuk `test_prelaunch_hardening.py` dari cycle
sebelumnya): **11/11 PASS**, 0 FAIL, 0 test dihapus.

## 44. Jumlah test baru PASS/FAIL
`test_voice_note.py`: **19/19 PASS**, 0 FAIL.

## 45. Langkah manual Render
- Tambahkan environment variable `OPENAI_API_KEY` (wajib, kalau mau voice note benar-benar aktif —
  tanpa ini, fitur tetap aman/tidak error, cuma selalu fallback "belum kebaca dengan jelas").
- (Opsional) `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_MODEL`, `FEATURE_VOICE_NOTE_CUSTOMER`,
  `FEATURE_VOICE_NOTE_OWNER` kalau mau override default.
- Setup cron eksternal untuk `/cron/followups?key=<CRON_SECRET>` (follow-up + reminder), masih
  belum terkonfirmasi seperti cycle sebelumnya.
- Update file `app.py` ke repo GitHub asli (manual via web editor), baru Render auto-redeploy.

## 46. Langkah manual Meta
- Cek/approve **WhatsApp Message Template** untuk reminder appointment proaktif (H-1) di Meta Business
  Manager — tanpa ini, reminder ke customer di luar 24-jam customer service window berisiko gagal kirim.
- Pastikan nomor WhatsApp Business API sudah di luar mode test sebelum outreach ke klien asing (temuan
  lama, masih perlu dikonfirmasi ulang oleh kamu).
- Tidak ada perubahan ke Meta webhook/Phone Number ID/access token — sesuai instruksi, TIDAK disentuh.

## 47. Environment variable baru yang WAJIB kamu tambahkan
`OPENAI_API_KEY` — satu-satunya yang benar-benar wajib kalau voice note mau aktif. Sisanya (
`TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_MODEL`, `FEATURE_VOICE_NOTE_CUSTOMER`,
`FEATURE_VOICE_NOTE_OWNER`) opsional — sudah punya default aman di kode.

## 48. Risiko yang tersisa
- **Voice note belum pernah dites terhadap API OpenAI/provider transkripsi sungguhan** — semua test
  pakai mock. Sebelum benar-benar diandalkan, coba kirim voice note asli setelah `OPENAI_API_KEY` diisi
  di Render, dan cek hasil transkrip Bahasa Indonesia/informal beneran akurat (Whisper kadang kurang
  akurat untuk aksen/logat tertentu atau audio berisik).
- **Kombinasi voice note + perintah katalog owner** ("kirim katalog ke Wilson" via VN) belum ada test
  eksplisit — secara arsitektur seharusnya bekerja (reuse `parse_owner_catalog_command`), tapi belum
  diverifikasi langsung.
- **Reminder proaktif via WhatsApp template** belum dikonfirmasi statusnya di Meta Business Manager —
  ini bisa jadi silent-fail kalau diaktifkan tanpa template approved.
- **Follow-up/reminder cron eksternal** masih belum dikonfirmasi disetup (isu lama, belum berubah).
- **Multi-tenant** baru di tahap konfigurasi (TENANT_CONFIG + FEATURES), BUKAN isolasi data multi-tenant
  penuh (belum ada tenant kedua untuk diuji, belum ada tenant_id di skema database) — kalau nanti ada
  klien kedua beneran, perlu kerjaan tambahan (bukan sekadar ganti config) untuk memisahkan data per
  tenant di database/PRICING_CONFIG/dst. Ini FUTURE ROADMAP, bukan blocker untuk Kilas Works sendiri.
- **State machine appointment** SENGAJA tidak diganti namanya jadi persis seperti contoh di request
  (CUSTOMER_INTERESTED/WAITING_OWNER_AVAILABILITY/dst) — state existing (MEETING_STATE_*) sudah
  fungsional setara dan sudah lulus semua regression test; mengganti nama state berisiko tanpa manfaat
  jelas, jadi TIDAK dilakukan (lihat safety rule "kalau berisiko, STOP dan laporkan").
- **Lightweight lead state** (item 58 di request) — sudah ada `lead_stage` dari cycle sales-engine
  sebelumnya (NEW-ish states), TIDAK dibangun ulang jadi state machine baru terpisah di cycle ini karena
  scope sudah besar; kalau kamu mau, ini bisa jadi task terpisah berikutnya.

## 49. Rekomendasi deploy
**BELUM DIREKOMENDASIKAN untuk deploy voice note ke production tanpa langkah manual berikut dulu:**
1. Isi `OPENAI_API_KEY` di Render dan tes voice note dengan suara asli (belum pernah diuji end-to-end
   terhadap API sungguhan).
2. Konfirmasi status WhatsApp Message Template untuk reminder di Meta Business Manager (kalau reminder
   mau diaktifkan).
3. Konfirmasi setup cron eksternal untuk follow-up (isu lama, belum berubah).

**Untuk bagian NON-VOICE (pricing/katalog/landing page/customer-owner bot text/live demo appointment)**:
semua regression test PASS (11/11 file lama + 1 file baru dari cycle sebelumnya), tidak ada temuan
security baru, dan sudah dites lewat cycle sebelumnya — bagian ini **relatif siap** untuk deploy setelah
kamu review manual sendiri, TAPI karena voice note ada di file `app.py` yang SAMA, deploy praktis berarti
deploy semuanya sekaligus. Kalau mau lebih hati-hati, opsinya: (a) deploy sekarang dengan
`OPENAI_API_KEY` SENGAJA dikosongkan dulu di Render (voice note otomatis nonaktif-jujur, fitur lain
semua jalan normal), lalu isi `OPENAI_API_KEY` belakangan setelah tes manual voice note di luar
production, atau (b) tunda deploy sampai voice note dites manual dulu di sandbox/staging.

**Kesimpulan**: tidak ada test yang FAIL, tapi voice note punya risiko residual yang cuma bisa
diverifikasi dengan API key sungguhan — keputusan akhir ada di kamu setelah baca poin 48 di atas.
