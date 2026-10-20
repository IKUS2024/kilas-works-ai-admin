# Kilas AI Chat/Search answer quality — local patch, 2026-10-20

Patch lokal selesai untuk bug yang direproduksi. **202 tes backend terarah lulus**, ditambah Chromium untuk URL sumber, streaming Markdown pada enam kombinasi permukaan/viewport, dan JSON/copy pada dua viewport. Saat diagnosis awal diselesaikan, belum ada commit/push/deploy. Setelah itu owner memberikan izin rilis eksplisit untuk AI Call dan Chat/Search; catatan integrasi pra-rilis ada di bawah. Tidak ada panggilan model/search berbayar. Ini bukti kontrak kode dan fixture, bukan sertifikasi kebenaran semua jawaban model di produksi.

Base: `ab6f8514e8da53da4f65a3da51faaf2f0eb00182` (`origin/main`, diverifikasi kembali sesudah patch). Checkout awal `0b51a39b` di-fast-forward sebelum mengedit sehingga dua perubahan Finance terbaru tetap utuh. Tidak ada perubahan implementasi Finance, Translator, billing, kuota, penyimpanan tenant, pemilihan model/provider, atau berkas AI Call.

## Bug terverifikasi dan patch

| Reproduksi sintetis / bukti kode | Akar masalah | Perubahan |
| --- | --- | --- |
| Pertanyaan paket Halo AI/Cekat AI → harga tahunan → tim 5 orang → yang termurah. Payload akhir kehilangan kriteria perantara. | `_chat_search_text` hanya menyertakan satu topik; `lookup_topic` tidak membawa refinements. | `lookup_context` menyertakan topik dan refinements pengguna berurutan, berhenti pada topik baru. Tetap maksimal enam pertanyaan terdahulu, baris/topik pertama saja; tidak mengekspor jawaban assistant, catatan sesudah baris pertama, atau teks lampiran. |
| Query >6.000 karakter dengan syarat wajib di bagian akhir. | Slicing `[:6000]` membuang akhir permintaan yang sudah diterima route (batas route tetap 12.000 karakter). | Query Chat mempertahankan seluruh permintaan terbaru; `request_text` tetap menghapus teks hasil ekstraksi lampiran dari query. |
| `600 RMB ke IDR` → `kalau 700?` → `kalau 800?`, lalu varian `jangan search`. | Detektor konversi hanya melihat satu pertanyaan sebelumnya. Gate rate/date/Decimal dan gate opt-out dapat hilang pada follow-up kedua. | Telusuri rantai numeric-only ke pasangan eksplisit; hentikan pada topik baru. Rate/date/source gate dan Decimal tetap dipakai, selected model tidak meregenerasi hasil terverifikasi. Opt-out bertingkat tidak memanggil Chat untuk menebak kurs. |
| Provider mengembalikan `/archive/;edition=2?q=a%20b&empty=&q=c#table-2`. | Normalisasi lama menghapus slash/parameter/fragment, blank query, dan mengubah encoding. | Pisahkan destination aktual dari key deduplikasi. Tautan Chat mempertahankan bagian fungsional dan signed query; key tidak mengubah encoding query fungsional. Normalizer `_source_url` lama dipertahankan untuk kompatibilitas Call/Work. |
| `[Sumber](https://example.test/wiki/Ekonomi_(Indonesia))`. | Regex validator/fallback berhenti di `)` pertama sehingga URL valid ditolak; regex renderer juga membuat href yang terpotong. | Parse parentheses seimbang di validator/recovery sumber dan renderer. Chromium membuktikan href penuh untuk nested parentheses, query bertanda tangan, blank query, path params, dan fragment. HTTP(S), larangan credentials, serta rendering HTML sebagai teks tetap berlaku. |
| Dua hasil riset disintesis menjadi jawaban; payload sintesis tidak memiliki pertanyaan asal. | `_synthesize_research` menerima findings dan sumber saja. | Sintesis menerima query asli beserta refinements, seluruh temuan yang selesai, dan daftar sumber lengkap. Jumlah panggilan, model, effort dan batas output provider tetap sama. |
| Jawaban selected model atau retrieval menulis `Temuan [99]` dengan hanya satu sumber. | Validasi URL menerima teks tanpa URL secara vacuous; nomor sumber tidak divalidasi di dua jalur ini. | Tolak indeks sumber di luar daftar aktual. JSON, fenced/inline code, dan label tautan numerik bukan dianggap referensi sumber. Tidak ada retry/fallback model baru. |
| Jawaban lengkap 35k+ karakter atau jawaban agent 14k+ karakter dengan sepuluh sumber. | Adapter memotong jawaban di 30k, agent di 12k, dan daftar sumber di delapan tanpa status partial. | Hilangkan pemotongan pascapenyelesaian ini. Sumber aktual lengkap dipertahankan; daftar sumber agent dinomori agar `[n]` bisa dipetakan. Batas panggilan/token provider yang sudah ada tetap berlaku. |
| `Cuaca Jakarta besok bagaimana?` / `Weather in Jakarta tomorrow?`. | Routing lama tidak mengenali prakiraan tanpa keyword tertentu; agent menganggap `besok/tomorrow` sebagai penjadwalan sebelum memeriksa kebutuhan informasi. | Prakiraan yang diminta sekarang memakai Search; reminder atau aksi terjadwal eksplisit tetap ke jalur lama. Transformasi teks yang mengandung waktu tidak menjadi Work. Konsep cuaca, penulisan kreatif umum, dan data yang disuplai memiliki negative fixtures. |
| `Sudah saya cek sumber terbaru`, `Saya telah melakukan pencarian web`, `I have searched the web`; juga kalimat conditional. | Guard klaim aksi terlalu sempit dan menandai sebagian kalimat conditional sebagai klaim aktual. | Perluas pola completed lookup yang terbukti lolos, bedakan prefix conditional/negated dari klaim aktual. `...tetapi tidak menemukan hasil` tetap merupakan klaim telah mencari. Mekanisme satu repair terukur yang sudah ada dipertahankan. |

Suite baru awal (sembilan metode) dijalankan sebelum patch: **15 assertion gagal dan dua error URL valid ditolak**. Tes Chromium URL sebelum patch gagal pada kedua URL bertanda kurung. Ini membuktikan mekanisme kegagalan; tidak membuktikan seberapa sering bug terjadi pada pengguna produksi.

## Verifikasi

Seluruh transport baru disubstitusi fixture/mock; suite baru secara eksplisit melarang `requests.sessions.Session.request`. Tidak mengakses isi percakapan pelanggan atau secrets. Dependensi dipasang di venv `/tmp/kilas-chat-search-venv`, sesuai `client-hub/requirements.txt`; tidak ada perubahan dependency repo.

Perintah suite utama (202 lulus):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests \
  /tmp/kilas-chat-search-venv/bin/python -m unittest \
  test_kilas_chat_auto_search test_kilas_search_model_recovery \
  test_kilas_ai_tools test_kilas_ai_evidence_reliability \
  test_kilas_chat_quality_v2 test_kilas_ai_routing test_kilas_ai_natural_style \
  test_kilas_chat_models test_kilas_ai_call_public_search \
  test_kilas_ai_call_search_contract test_kilas_chat_search_answers \
  test_kilas_chat_rate_evidence
```

Cakupan baru mencakup Indonesia/Inggris, beberapa follow-up, batas topik/privasi query, request panjang, konversi berantai, quote usang, source URL yang tidak dikembalikan, source utama dilaporkan tidak tersedia dengan alternatif yang benar-benar dikembalikan provider, empty response, timeout, rate limit, tidak ada guessed fallback/done pada kegagalan, penomoran citation, dan jawaban/sumber lengkap. Fixture sumber historis memastikan uncertainty/date dari hasil tidak ditimpa, bukan membuktikan freshness klaim secara semantik.

Browser dan pemeriksaan statis:

- `client-hub/tests/test_kilas_chat_search_links_browser.py`: satu tes Chromium, empat bentuk URL, streaming pecahan tujuh karakter, link credentials/javascript ditolak, HTML tidak dieksekusi.
- `client-hub/tests/test_kilas_chat_markdown_browser.py`: enam kombinasi legacy/agent × lebar 390/820/1440, progressive render/reset/final, math/code/table/safety/source preservation lulus; nol paid calls dan production mutations.
- `client-hub/tests/test_kilas_chat_json_browser.py`: dua viewport 390/1440, JSON literal, clipboard nyata, formatting/code dan safety lulus; nol paid calls.
- `node --check client-hub/static/kilas_ai_markdown.js` dan `git diff --check` lulus. Versi asset dinaikkan pada dua include Markdown yang sudah ada; layout/CSS tidak diubah.

Delapan kegagalan awal di `test_kilas_ai_tools` dan `test_kilas_chat_quality_v2` direproduksi juga pada arsip main bersih: fixture membuat session lama tanpa identitas revocable dan mendapat 401 sebelum menjalankan target. Dua fixture tersebut kini memakai `auth_test_helpers.authenticate` yang sudah ada; tools menetapkan locale Indonesia sesuai assertion Indonesianya. Tidak ada bypass middleware atau perubahan auth produksi. Suite utama kemudian hijau.

Pemeriksaan ekstra terhadap seluruh `test_kilas_ai_unified`, `test_kilas_chat_intents`, `test_kilas_work_v2`, dan `test_kilas_home` menemukan **empat kegagalan lama**, identik pada arsip main bersih. Targetnya `test_unified_navigation_and_legacy_history`, `test_available_live_access_is_preserved_without_enabling_it`, `test_home_profile_is_informational_and_account_hints_cannot_restore_ai_shell`, serta `test_new_chat_and_existing_thread_keep_separate_layout_state_and_full_content`: ekspektasi markup/lokalisasi Home lama tidak sesuai output terkini. Tidak diubah pada tugas jawaban ini. Ini belum merupakan whole-repository green build.

## Berkas bersama untuk koordinasi AI Call

**`client-hub/kilas_ai/tools.py` adalah adapter bersama yang wajib direview bersama thread AI Call `01a158c9-3855-76af-bf19-435ebfe1d01e`.** `_source_url` lama dan signature `web_search_steps` tetap kompatibel. Perubahan parsing URL/retensi sumber berada pada adapter yang sama; tes Call public-search dan cap-envelope ikut suite 202 yang lulus. Tidak ada berkas `ai_call*.py` yang diedit.

Berkas lain yang perlu koordinasi: `routing.py`, `chat_web.py`, `chat_model_tools.py`, `chat_quality.py`, `unified_runtime.py`, `routes.py`. Renderer `static/kilas_ai_markdown.js` dipakai bersama UI Chat/Work; perubahan hanya parser tautan dan cache version di `_home_workspace.html` / `_automation_head.html`.

## Batas verifikasi dan log produksi

- Tidak ada evaluasi kualitas dengan model/search live, benchmark semantic correctness, uji perangkat Android fisik, atau verifikasi bahwa sebuah situs eksternal benar-benar bisa dibuka saat ini. Keberadaan/provenance URL provider tidak membuktikan dukungan semantik setiap klaim atau ketersediaan halaman di masa depan.
- Freshness umum tetap kontrak prompt/source evidence, bukan detektor otomatis semua klaim usang. Quote FX punya validasi tanggal dan batas tujuh hari yang sudah ada. Bahasa alami/intent/fake-action guard tetap heuristik; jangan mengklaim seluruh pertanyaan terbaru atau seluruh klaim palsu terdeteksi.
- Retensi hasil/sumber lengkap dan findings sintesis yang sebelumnya dipotong dapat menambah ukuran respons/konteks sintesis. Batas token/call provider dan policy billing/quota tidak diubah; pencatatan penggunaan aktual yang sudah ada tetap berlaku. Tidak ada paid retry baru.
- Riwayat pencarian dibatasi enam pertanyaan dan topik baris pertama untuk privasi; referensi ambigu atau topik lebih tua masih bisa memerlukan klarifikasi. Jangan mengekspor seluruh history assistant untuk mengatasinya tanpa review privasi.
- Bukti repo read-only yang dibaca: `docs/KILAS_CHAT_QUALITY_V2_STATUS.md`, `docs/QA_CHAT_HISTORY_CONTEXT_20261017.md`, dan `docs/QA_CHAT_MODELS_20261017.md`. Ini catatan QA historis, bukan log insiden baru.
- Workspace kemudian dikonfirmasi parent: `tea-da34t2gu01pc73ft7uf0`, service `srv-da7ti2psrm7s73dh9i2g`. Metadata service cocok dengan repo IKUS2024/kilas-works-ai-admin, branch main, root client-hub dan nama kilas-works-client-hub; auto-deploy off. Deploy awal live `dep-dbbjdae7bikc738p10og` memakai `ab6f8514`. Query read-only app logs untuk `KILAS_(SEARCH_FAILURE|CHAT_VALIDATION)` dari 2026-10-17T00:00Z sampai 2026-10-20T10:32:56Z mengembalikan nol entri, `hasMore=false`; ini tidak membuktikan tidak ada bug atau penggunaan produksi. Tidak mengambil isi percakapan. GET public app/onrender dari lingkungan ini mendapat ProxyError (CONNECT 403); web fetch app juga tidak tersedia. Verifikasi HTTP produksi harus dilaporkan terpisah dari status deploy Render.

## Integrasi pra-rilis yang diizinkan

- Parent mengirim hash AI Call `0268b47f168e0f281e2e9bff10ed314966969c27`. Main di-fetch dan di-fast-forward ke hash itu; patch Chat/Search tetap utuh dan tidak ada konflik. Berkas AI Call pada tree integrasi identik dengan commit parent. Finance dan Translator tidak memiliki diff.
- Suite Chat/Search 202 tes lulus lagi setelah integrasi. Call/Translator Node **117/117 lulus**. `test_finance_legacy_seed_provenance.py` dan `test_kilas_translator_measured_effort.py` lulus melalui runner offline. Chromium Chat URL dan enam kasus Markdown lulus lagi.
- Koleksi Python Call dijalankan ulang dengan runner network-blocking: **11/12 berkas lulus**, satu kegagalan historis `test_kilas_ai_call_search_smoke.py` tetap dua failure/satu error `setup_changed` seperti baseline parent; pagar 8192 byte tidak diubah dan paid smoke tidak diaktifkan.
- Referensi deploy/health Render terkini dibaca lewat versi HTML resmi setelah fetch Markdown tidak didukung web reader dan shell mendapat CONNECT 403. Tidak ada konfigurasi resource, environment, database, atau provider yang diubah.
- Hash push final, ID/status deploy, waktu live dan log startup dicatat dalam bukti rilis terpisah sesudah tindakan rilis benar-benar selesai; bagian ini hanya menyatakan pemeriksaan pra-rilis.

## Rencana rilis minimum

1. Parent review diff dan koordinasikan adapter bersama dengan patch AI Call; pertahankan Finance/Translator di main terkini. Re-run suite 202 serta browser Markdown bila resolusi konflik menyentuh parser/routing.
2. Setelah identitas workspace dikonfirmasi, identifikasi service dari repo/domain dan baca hanya telemetry sanitasi `KILAS_SEARCH_FAILURE` / `KILAS_CHAT_VALIDATION` yang sudah ada. Jangan mengambil prompt, response body, secrets, atau percakapan pelanggan.
3. Persetujuan eksplisit owner untuk kedua perbaikan sudah diteruskan parent ("semua aku izinkan"). Parent meminta AI Call dipush lebih dulu, lalu Chat/Search di atas hash tersebut, push main tanpa force, dan satu deploy final. Tidak ada izin paid model/search call baru.
4. Rilis hanya patch ini dengan pipeline yang berlaku, lalu smoke read-only halaman Chat dan asset. Skenario provider live baru memerlukan izin budget tersendiri; tanpa itu laporkan bahwa keberhasilan end-to-end provider masih belum diuji.
5. Amati kode kegagalan sanitasi sesudah rilis. Rollback jika regresi terkonfirmasi dengan revert patch tersendiri melalui proses rilis yang disetujui; tidak ada migrasi atau tindakan data yang perlu dibalik.
