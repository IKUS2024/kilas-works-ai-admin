# Laporan Bug Fix — Voice Note Transcription Failure

Checkpoint sebelum bugfix: `checkpoint-before-voice-bugfix`. Commit hasil fix: `3d98b10`. Lingkup diff
**hanya** `app.py` (fungsi voice-note/media-download) dan `test_voice_note.py` — dikonfirmasi lewat `git
diff` line-by-line, tidak ada baris pricing/appointment/payment/demo/catalog/owner-NLU yang berubah.
**Belum di-push/deploy.**

## 1. Exact root cause

Saya tidak punya akses ke Render runtime/log kamu dari sandbox ini, jadi saya tidak bisa membaca log
production kamu secara langsung untuk membuktikan 100% pasti. Yang bisa saya buktikan dari audit kode:

**Bug konkret yang saya temukan dan perbaiki**: `transcribe_audio_whatsapp()` sebelumnya `return` di 5
dari 6 titik kegagalan (`no_media_id`, `download_failed`, `invalid_encoding`, `too_large`,
`not_configured`) **tanpa mencetak log APAPUN di dalam fungsi itu sendiri** — cuma dua titik pemanggil di
webhook yang print reason string mentah. Ini bukan cuma masalah "kurang informatif": kalau reason-nya
`not_configured`, itu MEMANG ter-print di log webhook ("Owner voice note gagal ditranskrip
(media_id=...): not_configured") — jadi kalau kamu cek log Render dan cari baris ini, jawabannya ADA di
sana. Kalau kamu belum sempat cek/cari baris itu, itu sebabnya masih terasa seperti "black box".

**Diagnosis paling mungkin berdasarkan pola gejala**: SEMUA voice note (4 detik, 3 detik, 2 detik) gagal
dengan pesan generik yang PERSIS SAMA. Kalau penyebabnya kualitas audio, biasanya tidak akan 100% gagal
identik di semua durasi — pola "gagal total, tanpa variasi" adalah tanda klasik sebuah **gate konfigurasi**
yang berhenti di titik yang sama setiap kali, bukan masalah kualitas audio nyata. Kandidat gate itu adalah:

```python
if not provider_configured:      # OPENAI_API_KEY kosong ATAU TRANSCRIPTION_PROVIDER bukan "openai"
    return None, VOICE_ERR_PROVIDER_NOT_CONFIGURED
```

`OPENAI_API_KEY` adalah environment variable **BARU** yang baru pertama kali diminta di laporan cycle
sebelumnya — sangat mungkin belum sempat ditambahkan ke Render sebelum kamu tes. Ini kesimpulan paling
mungkin, BUKAN kepastian mutlak tanpa melihat log kamu.

**Langkah untuk memastikan 100%**: setelah redeploy versi ini, kirim satu voice note lagi, lalu cari di
Render log baris yang diawali `VOICE_DEBUG: stage=provider_check`. Kalau `api_key_present=False`, itu
konfirmasi pasti akar masalahnya. Kirim baris log itu ke saya dan saya bisa konfirmasi 100% instan.

## 2. Apakah media download berhasil sebelumnya?

Tidak bisa dipastikan dari sandbox ini (tidak ada akses log production). Kode `download_whatsapp_media()`
sekarang dipecah jadi 2 tahap yang masing-masing di-log terpisah (`media_metadata_request` dan
`media_content_request`) — kalau kamu kirim VN lagi dan lihat baris `VOICE_DEBUG: stage=media_download
metadata_or_download=ok`, itu artinya download BERHASIL dan masalahnya pasti di tahap sesudahnya
(provider config/transcription). Kalau `metadata_or_download=failed`, gagalnya di WhatsApp Graph API side
(token/media_id/network).

## 3. MIME yang ditemukan

Tidak diketahui dari sandbox ini (belum ada log production). Setelah redeploy, baris `VOICE_DEBUG:
stage=media_download ... mime_type=...` akan menunjukkan MIME asli yang WhatsApp kirim untuk voice note
kamu — dugaan kuat `audio/ogg; codecs=opus` (format standar WhatsApp voice note), yang SUDAH ada di
whitelist (`SUPPORTED_AUDIO_MIME_TYPES`), jadi kemungkinan besar bukan sumber masalah.

## 4. Jumlah bytes audio yang didownload

Tidak diketahui dari sandbox ini. Baris `VOICE_DEBUG: stage=decode_base64 ... byte_length=...` akan
menunjukkan ini setelah redeploy. Guard 0-byte dan guard >16MB sekarang eksplisit dan ter-log terpisah
(sebelumnya guard >16MB ada, tapi guard 0-byte pada level download tidak eksplisit).

## 5. Transcription provider yang digunakan

`openai` (default, bisa dioverride via `TRANSCRIPTION_PROVIDER` env var — TIDAK diubah di fix ini).

## 6. Transcription model

`whisper-1` (default, bisa dioverride via `TRANSCRIPTION_MODEL` — TIDAK diubah di fix ini).

## 7. Environment variable yang dibutuhkan

`OPENAI_API_KEY` — **ini satu-satunya yang benar-benar wajib** supaya voice note aktif beneran. Tanpa
ini, sistem SENGAJA fallback jujur (tidak crash, tidak hallucinate), tapi voice note tidak akan pernah
berhasil ditranskrip — persis gejala yang kamu laporkan.

## 8. Apakah env tersebut tersedia/tidak

**Tidak bisa saya cek langsung** — sandbox ini terpisah total dari environment Render kamu, saya tidak
punya akses untuk melihat env var yang benar-benar terpasang di sana. Ini yang PALING PENTING untuk kamu
verifikasi sendiri: buka Render dashboard → Environment → cek apakah `OPENAI_API_KEY` ada, terisi (bukan
string kosong), dan tidak ada spasi/baris baru nyelip di awal/akhir value saat kamu paste.

## 9. Exact code bug yang diperbaiki

- `transcribe_audio_whatsapp()`: 5 dari 6 titik kegagalan tidak pernah mencetak log detail di dalam
  fungsi itu sendiri (hanya reason string mentah di level pemanggil) — sekarang SETIAP titik return
  mencetak baris `VOICE_DEBUG:` terstruktur (media_id ada/tidak, hasil download, panjang bytes, MIME
  dikenali/tidak, provider terkonfigurasi/tidak, hasil request transkripsi, exception class, panjang
  transcript) — TANPA pernah mencetak token/API key/audio mentah.
- `OPENAI_API_KEY`/`TRANSCRIPTION_PROVIDER`/`TRANSCRIPTION_MODEL` sekarang di-`.strip()` saat dibaca dari
  environment DAN sekali lagi tepat sebelum dipakai bikin header `Authorization` — ini nutup celah nyata:
  kalau value di-paste dengan trailing newline/spasi (kesalahan umum saat copy-paste ke form env var),
  sebelumnya bisa lolos truthy-check tapi menghasilkan header rusak yang ditolak library `requests`
  sendiri (`InvalidHeader`) — kategori errornya jadi salah (`transcription_failed` padahal akar
  masalahnya sama dengan `not_configured`). Ditemukan lewat test baru yang saya tulis sendiri saat
  membuat fix ini (bukan asumsi — reproducible).
- `download_whatsapp_media()`: dipecah jadi 2 tahap ter-log terpisah (metadata request vs isi media),
  dan diperbaiki default MIME yang sebelumnya diam-diam `"image/jpeg"` kalau field `mime_type` tidak ada
  di response — default ini masuk akal untuk gambar tapi salah untuk fungsi yang sekarang dipakai
  bersama audio, diganti jadi string kosong netral. Ditambah deteksi eksplisit untuk hasil download 0
  byte (sebelumnya tidak terdeteksi sebagai kasus khusus).
- Kategori error diberi nama eksplisit (`VOICE_ERR_NO_MEDIA_ID`, `VOICE_ERR_MEDIA_DOWNLOAD_FAILED`,
  `VOICE_ERR_INVALID_ENCODING`, `VOICE_ERR_EMPTY_AUDIO`, `VOICE_ERR_UNSUPPORTED_AUDIO`,
  `VOICE_ERR_PROVIDER_NOT_CONFIGURED`, `VOICE_ERR_API_ERROR`, `VOICE_ERR_PARSE_ERROR`,
  `VOICE_ERR_AUDIO_UNCLEAR`) menggantikan string bebas sebelumnya — pesan yang dilihat customer/owner
  TETAP SATU kalimat ramah yang sama, cuma kategorisasi internal yang diperjelas.

**Tidak ada perubahan pada**: cara transcript masuk ke pipeline owner/customer (`owner_text`/`user_text`
tetap sama persis), cara owner identity ditentukan (tetap murni dari `OWNER_WHATSAPP_NUMBER`), duplicate
webhook guard (tetap berlaku untuk semua `msg_type` termasuk audio, tidak disentuh).

## 10. Owner VN test result

Semua test owner voice note yang sudah ada (query-only, action-actually-sends, transcription-failure,
feature-flag-off, identity-never-from-transcript) tetap **PASS** setelah fix. Ditambah 1 test baru yang
menutup gap dari laporan sebelumnya: `test_owner_voice_note_catalog_command_actually_sends` — voice note
"kirim katalog ke Wilson" dikonfirmasi memanggil `send_catalog_pdf` persis ke nomor Wilson (bukan draft,
bukan customer lain). **22/22 test di `test_voice_note.py` PASS.**

## 11. Customer VN test result

Semua test customer voice note yang sudah ada (pricing question, demo appointment intent, payment
intent, transcription-failure ID & EN, feature-flag-off) tetap **PASS** setelah fix.

## 12. Real/representative audio format test

Ditambahkan `test_transcribe_audio_whatsapp_real_wav_bytes_reach_provider_request` — generate file WAV
valid asli (bukan fake bytes) pakai modul `wave` Python (0.1 detik audio silence, container WAV
sungguhan), lalu dibuktikan: (a) byte-nya sampai UTUH tanpa termodifikasi ke request multipart yang
dikirim ke provider transkripsi, (b) nama file berakhiran `.wav` yang benar, (c) content-type `audio/wav`
benar, (d) header `Authorization: Bearer sk-fake` terbentuk benar. Ini membuktikan jalur
encode-decode-multipart TIDAK merusak data audio — kalau production masih gagal setelah `OPENAI_API_KEY`
terverifikasi ada, kemungkinan besar bukan di titik ini.

**Catatan jujur**: ini BUKAN pengujian terhadap API OpenAI sungguhan (network call di-mock) — saya tidak
punya `OPENAI_API_KEY` sungguhan di sandbox ini untuk memanggil API asli. Baru dites end-to-end kalau
kamu kirim voice note lagi setelah `OPENAI_API_KEY` terkonfirmasi ada di Render.

## 13. Duplicate test

`test_voice_note_duplicate_webhook_no_double_send` tetap **PASS** — wamid yang sama dikirim 2x untuk
pesan audio, dipastikan cuma diproses sekali (transkripsi sekali, balasan sekali). Mekanisme dedup tidak
disentuh sama sekali di fix ini.

## 14. Existing regression PASS/FAIL

**Semua 11 file test yang sudah ada sebelum fix ini: 11/11 PASS, 0 FAIL, 0 test diubah/dihapus.** Tidak
ada regresi ke pricing/appointment/payment/demo/catalog/owner-NLU/customer-sales-prompt/contact-matching.

## 15. Apakah ada ENV baru yang harus dimasukkan di Render

**Tidak ada ENV BARU dari fix ini.** `OPENAI_API_KEY` sudah diminta di laporan MASTER update sebelumnya
(bukan baru dari fix ini) — kemungkinan besar itu yang belum sempat ditambahkan, itulah dugaan akar
masalah di poin 1. Cek ulang: apakah `OPENAI_API_KEY` sudah benar-benar ada di Render Environment, terisi
value yang valid, tanpa spasi/newline nyelip di ujung.

## 16. Apakah perlu restart/redeploy Render

Ya — setelah kamu update `app.py` ke repo GitHub (manual, sesuai constraint "jangan deploy otomatis"),
Render akan auto-redeploy dan restart service secara otomatis. Setelah redeploy itulah instrumentasi
`VOICE_DEBUG:` baru akan mulai muncul di log untuk voice note berikutnya.

## 17. Recommend deploy: **BELUM, dengan 1 syarat cepat**

Semua regression test PASS (11 lama + 22 baru di `test_voice_note.py`), tidak ada fitur lain yang
disentuh — dari sisi kode, fix ini **aman untuk di-deploy**. TAPI saya belum bisa memastikan 100% ini
benar-benar memperbaiki masalah kamu di production karena saya tidak bisa melihat log Render kamu.
**Rekomendasi konkret**:
1. Cek dulu di Render dashboard: apakah `OPENAI_API_KEY` sudah ada & terisi benar. Kalau BELUM, isi
   dulu — ini kemungkinan besar satu-satunya yang perlu dilakukan.
2. Deploy `app.py` versi ini (instrumentasi VOICE_DEBUG, tidak mengubah fitur lain).
3. Kirim SATU voice note test lagi.
4. Kirim ke saya baris log yang diawali `VOICE_DEBUG:` dari percobaan itu — dengan itu saya bisa
   konfirmasi 100% pasti apakah root cause-nya benar `OPENAI_API_KEY` atau ada penyebab lain (MIME tidak
   didukung provider, token WhatsApp bermasalah, dll), dan kalau masih gagal, saya tahu persis di tahap
   mana harus difokuskan berikutnya — tanpa perlu tebak-tebak lagi.
