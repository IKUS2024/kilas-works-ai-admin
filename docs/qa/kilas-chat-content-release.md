# Kilas one-chat content release

## Hasil dan batas produk

Panel suara/proyek dipasang di percakapan Kilas AI yang sudah ada. Composer, endpoint chat umum, dan provider lama tetap dipakai seperti sebelumnya. Tidak ada menu listening baru. Panel menyediakan contoh rekaman sintetis tersimpan, pemilihan rekaman lama dengan ID tetap, revisi transkrip immutable, unduhan TXT versi tertentu, terjemahan/VoiceOver mock eksplisit, snapshot naskah proyek, riwayat dan pembatalan mock. Tombol rekam/unggah audio nyata disabled dengan penjelasan. Tidak ada audio palsu yang dapat diputar; STT, terjemahan nyata, TTS dan cloning tidak dijalankan oleh demo ini.

Content-project metadata menghubungkan chat/thread, Video Plan dan hasil Translator milik pemilik yang sama. Handoff hanya mengisi draft dari snapshot versi, tanpa memulai provider. Video tetap storyboard/prompt, bukan renderer MP4. Hasil Translator yang sudah ada tidak diubah.

## Aktivasi dan rollback

- `KILAS_CHAT_CONTENT_DEMO_ENABLED`: absent/false secara default; membutuhkan gate AI dan Automation yang sudah ada.
- `KILAS_CONTENT_PROJECTS_ENABLED`: absent/false secara default; metadata proyek dan draft handoff.
- `KILAS_LISTENING_DEMO_ENABLED`: absent/false secara default; juga mengontrol panel listening inline. Capture nyata terkunci di adapter dan UI.

Release kode ini tidak mengubah environment produksi dan tidak menyalakan flag. Karena itu deployment kode tidak berarti demo sudah terlihat oleh pelanggan. Aktivasi, cakupan preview dan pengujian audio/provider nyata merupakan pekerjaan terpisah. Tidak ada kredensial, akses persisten atau kebijakan autentikasi baru.

`content_schema.apply_release()` dipanggil hanya bila flag proyek/chat aktif. SQL SQLite dan PostgreSQL terpisah, additive, transactional, checksum-guarded; PostgreSQL menggunakan advisory transaction lock dan timeout. Tabel baru hanya berprefix `kilas_content_`, `kilas_chat_demo_` dan marker `kilas_content_releases`. Tidak ada DDL Finance/Trading atau perubahan tabel billing/provider. Rollback dengan mematikan flag menyembunyikan fitur, mempertahankan snapshot dan riwayat; jangan drop data saat rollback. Bila checksum berbeda, startup menolak migrasi, tanpa menulis perubahan parsial.

## Bukti QA lokal

Data sintetis dan database disposable. Chromium menguji shell chat nyata pada desktop 1440px dan mobile 390px; tidak ada overflow horizontal. Transport eksternal dan API capture nyata diblokir dalam test. Test fixture HTTP memasang hook CSRF asli, role gate dan route/template fitur; beberapa layanan sekitar chat distub agar tidak memanggil provider.

- 39 tes Python HTTP/browser/PostgreSQL gabungan lulus. Tes proyek/chat/listening HTTP dan browser: isolasi tenant/conversation, CSRF semua mutasi, consent penyimpanan sintetis, escaped input, versi yang dipilih, konflik CAS, operation key, tidak ada tindakan otomatis saat GET/reload, rollback/relogin, draft handoff, unduhan dan cancel.
- PostgreSQL 18 nyata, schema UUID lokal terisolasi: migrasi/retry/checksum, revisi/snapshot, BYTEA MP4 detection, ownership, mock translate/voice, snapshot proyek, cancel, empat request serentak yang menghasilkan satu record/action. URL QA harus loopback. Sentinel dan byte output lama tetap sama.
- Node: 10 lifecycle tests; consent, stop/end/completion/error cleanup, late picker resolution, tab/audio validation dan capture locked by default.
- Regresi lama: 13 suite / 295 tests lulus (foundation, chat, attachments, tools, agent, chat experience, Video/v2/parts/storyboard/recovery, audio, personal voice). Dijalankan per-process dengan `scripts/offline_tests` memblokir socket dan env provider dibersihkan.

Workflow `.github/workflows/kilas-content-chat-qa.yml` menjalankan regresi baru, Chromium, PostgreSQL 18 dan Node tanpa secret/provider.

Screenshots lokal: `/tmp/kilas-chat-qa/desktop.png`, `/tmp/kilas-chat-qa/mobile.png`. Workflow mengunggah screenshot sebagai artifact CI. Laporan prototype sebelumnya merekam tahap historis sebelum integrasi; catatan SQLite-only/no-startup-migration di sana telah digantikan release guarded ini.

## Review batas perubahan

Tidak ada perubahan global auth/session/CSRF, Finance, Trading, billing/pricing, provider credentials/configuration, shared base template atau shared stylesheet. CSS baru dibatasi komponen content/chat/listening. Semua operasi demo menyimpan teks sintetis/metadata; tidak meminta mikrofon/tab browser, merekam suara, mengirim pesan eksternal, membuat paid job atau memanggil broker.

Verifikasi CI remote, SHA deployment, health dan UI authenticated produksi harus dilaporkan terpisah dari QA lokal. Jangan mengklaim release live berdasarkan health 200 saja.
