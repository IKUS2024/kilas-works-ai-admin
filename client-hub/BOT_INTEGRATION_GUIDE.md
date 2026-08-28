# Panduan Migrasi: Menyambungkan Bot Produksi ke Client Hub (Phase 5)

Dokumen ini menjelaskan LANGKAH KONKRET untuk membuat `../app.py` (bot WhatsApp produksi) menjadi
tenant-aware menggunakan `tenant_config_service.py`, **tanpa** rewrite besar dan **tanpa** regresi
terhadap fungsi yang sudah jalan.

**STATUS (Business Hub V2, Production Integration cycle): Patch 1-6 di bawah SUDAH DITERAPKAN ke
kode `../app.py` di branch `business-hub-v2`** (bukan lagi cuma dokumentasi rencana). Semuanya tetap
di belakang gerbang yang membuatnya no-op secara default:
- Patch 1 (resolusi tenant) & Patch 4 (human takeover) — SELALU aktif secara kode, tapi
  `tenant_id` cuma pernah resolve ke tenant Client Hub yang BENERAN `ACTIVE` dengan
  `whatsapp_phone_number_id` yang cocok persis dengan `phone_number_id` di payload webhook. Nomor
  WhatsApp Kilas Works sendiri belum pernah didaftarkan sebagai tenant, jadi `tenant_id` selalu
  `None` untuk traffic produksi saat ini — dua patch ini nol efek di produksi sampai ada tenant
  klien asli yang benar-benar di-ACTIVATE dengan `phone_number_id` produksi yang cocok.
- Patch 2/3/5/6 — TAMBAHAN membutuhkan `ENABLE_MULTI_TENANT=true` (default `false`/belum di-set di
  Render) DI ATAS syarat `tenant_id` ter-resolve di atas.
- 15 test integrasi baru ada di root repo: `test_business_hub_v2_whatsapp_integration.py` — meng-cover
  kedua kondisi flag (off/on), resolusi tenant, tenant context injection, feature gate, human
  takeover (termasuk scoping per tenant+customer & return-to-AI), owner bridge (action/query), dan
  memastikan nomor OWNER_WHATSAPP_NUMBER Kilas Works sendiri tetap diproses lewat jalur owner-AI
  yang lama, bukan jalur tenant bridge yang baru.
- **BELUM diaktifkan di production Render** — `ENABLE_MULTI_TENANT` belum di-set di environment
  Render manapun, dan belum ada satupun tenant Client Hub ber-status ACTIVE dengan
  `whatsapp_phone_number_id` produksi asli. Mengaktifkan salah satu dari dua hal ini di Render adalah
  keputusan deploy terpisah yang butuh review manusia — bukan bagian dari kode ini sendiri.

Bagian di bawah ini (kontrak fungsi, prinsip arsitektur, kode Patch 1-6) tetap dipertahankan APA
ADANYA sebagai referensi persis kode apa yang diterapkan dan kenapa — bukan lagi "rencana migrasi
masa depan" untuk Patch 1-6, tapi catatan implementasi dari kode yang sudah ada di `../app.py`
sekarang.

## Prinsip

SATU AI Admin engine (`../app.py`), BANYAK tenant config. Bukan: satu `app.py` per klien.

`tenant_config_service.py` adalah SATU-SATUNYA pintu masuk yang boleh dipakai bot untuk membaca
data tenant. Bot tidak pernah membaca tabel Client Hub secara langsung.

## Kontrak fungsi (Phase 5, sudah diimplementasikan & dites)

```python
from tenant_config_service import (
    get_tenant_by_phone_number_id,  # (phone_number_id) -> tenant_id atau None
    get_tenant_config,               # (tenant_id) -> dict config lengkap, atau None kalau belum ACTIVE
    get_tenant_features,             # (tenant_id) -> {feature_name: bool, ...}
    get_tenant_knowledge,            # (tenant_id) -> {faq, services, products, pricing_notes}
    get_trusted_owner_phone,         # (tenant_id) -> str atau None
)
```

Aturan yang SUDAH dijamin oleh implementasi ini (dites di `tests/test_production_foundation.py`):
- `get_tenant_by_phone_number_id` HANYA resolve tenant yang statusnya `ACTIVE`. Tenant yang masih
  draft/approved-belum-connect TIDAK PERNAH ter-resolve — mencegah config yang belum direview
  manusia dipakai bot secara tidak sengaja.
- Tidak ada fungsi apapun di modul ini yang menerima teks pesan customer atau nama bisnis sebagai
  input untuk menentukan tenant — resolusi HANYA lewat `whatsapp_phone_number_id` (identifier
  kanal yang otoritatif dari Meta).
- `get_tenant_features` dan `get_tenant_config` tidak pernah bocor data tenant lain — setiap
  fungsi discope oleh `tenant_id` tunggal.

## Patch 1-6 (SUDAH DITERAPKAN di `../app.py`, branch `business-hub-v2`)

Migrasi ini SENGAJA dipecah jadi patch kecil dan terpisah, masing-masing dengan regresi test penuh
sebelum lanjut ke patch berikutnya — bukan satu rewrite besar. Kode di bawah ini merefleksikan APA
YANG SEKARANG ADA di `../app.py` (bukan lagi rencana) — lihat fungsi-fungsi `_resolve_tenant_id`,
`_get_conversation_mode_safe`, `_build_tenant_context_block_safe`, `_get_open_projects_summary_safe`,
`_get_trusted_owner_phone_safe`, `_get_tenant_features_safe` di dekat bagian atas `../app.py`, dan
blok kode di `receive_webhook()`.

### Patch 1 — Tambahkan resolusi tenant di webhook (paling aman, paling kecil)

Di `../app.py`, di handler webhook (tempat payload Meta pertama kali diproses), setelah
`phone_number_id` dari payload sudah diketahui:

```python
# TAMBAHAN, bukan pengganti — kalau resolve gagal (None), semua perilaku existing tetap jalan
# persis seperti sekarang (Kilas Works sebagai tenant default, implisit).
import sys
sys.path.insert(0, "client-hub")  # atau import path yang sesuai struktur deploy final
from tenant_config_service import get_tenant_by_phone_number_id

tenant_id = get_tenant_by_phone_number_id(phone_number_id)
# tenant_id dipakai di Patch 2 — TIDAK mengubah perilaku apapun di Patch 1 ini sendiri.
```

Jalankan 14 test regresi bot setelah patch ini. Harus tetap 14/14 PASS — patch ini murni aditif,
tidak ada cabang perilaku baru yang aktif.

### Patch 2 — Suntikkan tenant knowledge ke system prompt SAAT ITU JUGA (bukan permanen)

Di belakang feature flag (misal `ENABLE_MULTI_TENANT = os.environ.get("ENABLE_MULTI_TENANT") ==
"true"`, default `false`):

```python
if ENABLE_MULTI_TENANT and tenant_id:
    from tenant_config_service import get_tenant_config
    tenant_config = get_tenant_config(tenant_id)
    if tenant_config:
        # Suntikkan sebagai tambahan ke system prompt UNTUK REQUEST INI SAJA — bukan menulis ulang
        # SYSTEM_PROMPT global, bukan menyimpan ke variabel modul-level. Setiap request membangun
        # prompt-nya sendiri dari tenant_config yang baru di-fetch.
        system_prompt = build_prompt_for_tenant(tenant_config)  # fungsi baru, kecil
    else:
        system_prompt = SYSTEM_PROMPT  # fallback ke prompt Kilas Works yang sudah ada
else:
    system_prompt = SYSTEM_PROMPT  # perilaku existing, tidak berubah
```

Ini menjawab section 12 dari request awal: "DO NOT inject client-specific knowledge permanently
into a global prompt." Selama `ENABLE_MULTI_TENANT` belum di-set `true` di Render, baris ini tidak
pernah tereksekusi — nol risiko ke bot yang sedang jalan.

### Patch 3 — Feature-gate perilaku Pro-only dengan `get_tenant_features`

Sebelum bot menjalankan fitur voice note/appointment/owner_commands/dll UNTUK TENANT SELAIN Kilas
Works sendiri, cek dulu:

```python
if tenant_id:
    features = get_tenant_features(tenant_id)
    if not features.get("voice_note"):
        # fallback sopan, sama persis pola yang sudah ada untuk BILLING_OR_QUOTA_ERROR
        return "Maaf, fitur voice note belum aktif untuk paket ini."
```

Kilas Works sendiri (tenant default, `tenant_id=None` di alur existing) TIDAK PERNAH melewati
pengecekan ini — perilakunya sama seperti sekarang, seratus persen.

### Patch 4 — Cek Human Takeover sebelum bot auto-reply (Business Hub V2, Phase H)

Di awal handler pesan customer masuk, SEBELUM AI menyusun balasan apapun:

```python
if tenant_id:
    from tenant_config_service import get_conversation_mode
    mode = get_conversation_mode(tenant_id, customer_phone)
    if mode == "HUMAN_TAKEOVER":
        # Manusia (owner/admin Kilas Works) sedang pegang percakapan ini secara manual.
        # Bot TIDAK mengirim balasan apapun — tidak fallback, tidak "AI sedang istirahat", diam saja
        # supaya tidak tabrakan dengan pesan yang sedang diketik manusia.
        return
```

`wa_takeover_service.py` (schema `wa_conversation_state`, unique per `(business_id,
customer_phone)`) sudah dites lengkap: default `AI_ACTIVE` kalau belum ada row, scoped per bisnis
DAN per nomor customer (Takeover untuk satu customer tidak pernah memengaruhi customer lain dari
bisnis yang sama, atau bisnis lain dengan nomor customer yang kebetulan sama). Toggle-nya sudah ada
di UI admin (`admin.wa_takeover_toggle`, kartu "Human Takeover" di halaman review business).
Tenant default (Kilas Works sendiri, `tenant_id=None` di alur existing) tidak pernah melewati
pengecekan ini — perilakunya tidak berubah sampai Patch 1 diterapkan lebih dulu.

### Patch 5 — Sambungkan owner-message bridge (Business Hub V2, Phase F)

Di belakang flag yang SAMA dengan `ENABLE_MULTI_TENANT` (Patch 2), di jalur pesan dari nomor owner
terpercaya (`trusted_owner_phone`, sudah ada di alur existing untuk owner-command Kilas Works
sendiri):

```python
if ENABLE_MULTI_TENANT and tenant_id and is_from_trusted_owner:
    from wa_project_bridge import classify_owner_message, parse_owner_offers, build_customer_facing_offer_message
    kind = classify_owner_message(incoming_text)
    if kind == "OWNER_ACTION":
        offers, notes = parse_owner_offers(incoming_text)
        customer_message = build_customer_facing_offer_message(offers, notes)
        if customer_message:
            send_whatsapp_message(target_customer_phone, customer_message)
            # SIMPAN offers sebagai quotation DRAFT lewat quotation_service.create_quotation() —
            # bukan langsung SENT — supaya owner tetap bisa review di app sebelum benar-benar
            # terkirim sebagai quotation resmi (lihat catatan "kapan TIDAK" di bawah).
    elif kind == "OWNER_QUERY":
        from tenant_config_service import get_open_projects_summary
        summary = get_open_projects_summary(tenant_id)
        # ...render jawaban dari summary, jangan biarkan LLM menebak status project.
    # OWNER_INTERNAL_NOTE: tidak melakukan apapun ke customer — owner sedang mencatat, bukan mengirim.
```

`wa_project_bridge.py` murni logic (tidak ada I/O/DB write), sudah dites lengkap termasuk kasus
multi-offer dari contoh spec sendiri ("3 juta bisa 3 video, kalau 5 video 4,2 juta, shooting satu
hari" → dua offer terpisah + satu note, tanpa kehilangan offer kedua ke pemisahan koma desimal
Indonesia "4,2"). Pesan yang dikirim ke customer TIDAK PERNAH memuat wording asli owner atau marker
internal apapun (ACTION/STATE/DEBUG/JSON/PESAN_UNTUK_CUSTOMER) — hanya kalimat profesional yang
sudah dirender ulang.

### Patch 6 — Jawab pertanyaan harga/pembayaran customer dari catalog, bukan dari LLM

```python
if ENABLE_MULTI_TENANT and tenant_id:
    from tenant_config_service import get_active_service_catalog
    from wa_project_bridge import customer_price_response, customer_payment_response
    catalog = get_active_service_catalog()  # SAMA dengan yang tampil di app — bukan daftar kedua
    # ...cocokkan pertanyaan customer ke satu item catalog (name/catalog_key), lalu:
    reply = customer_price_response(matched_item)
    # untuk pertanyaan pembayaran:
    reply = customer_payment_response(matched_item["pricing_mode"])
```

Ini menjawab section 24-26: harga FIXED_PRICE/STARTING_FROM dijawab dari angka asli catalog;
CUSTOM_QUOTE TIDAK PERNAH dijawab dengan angka karangan — selalu diarahkan untuk kirim detail
kebutuhan lalu menunggu penawaran. Pembayaran SELALU diarahkan ke app.kilasworks.id, tidak pernah
diproses atau "dikonfirmasi" lewat WhatsApp.

## Kapan TIDAK mengaktifkan gerbang di atas (kodenya sudah ada, ini soal KAPAN MENYALAKAN)

Patch 4 (human takeover) berdiri sendiri dan efeknya otomatis aktif untuk tenant manapun yang sudah
`ACTIVE` dengan `whatsapp_phone_number_id` yang cocok — TIDAK butuh `ENABLE_MULTI_TENANT`. Satu-
satunya prasyaratnya adalah `tenant_id` ter-resolve (Patch 1), yang berarti secara otomatis TIDAK
pernah aktif untuk nomor WhatsApp Kilas Works sendiri (belum pernah didaftarkan sebagai tenant).

Jangan set `ENABLE_MULTI_TENANT=true` di Render sampai:
1. Minimal satu tenant klien nyata sudah diaktivasi lewat Client Hub (APPROVE + ACTIVATE),
2. `whatsapp_phone_number_id` klien tersebut benar-benar terhubung ke Meta (bukan cuma diisi di
   form admin — divalidasi nyata lewat percobaan kirim/terima WhatsApp),
3. Regresi 14 test bot + `test_business_hub_v2_whatsapp_integration.py` + suite Client Hub tetap
   100% PASS (sudah diverifikasi di cycle ini, TAPI verifikasi ulang setiap kali kode ini disentuh
   lagi),
4. Seseorang (bukan Claude) sudah review kode Patch 1-6 di `../app.py` secara langsung — ini tetap
   perubahan ke bot produksi yang sedang jalan, review manusia tetap wajib sebelum deploy.

## Rollback

Setiap patch di atas dilindungi oleh flag/precondisi (`tenant_id is None` atau
`ENABLE_MULTI_TENANT=false`) yang membuatnya no-op secara default. Rollback = set env var balik ke
`false`/hapus flag di Render, tidak perlu revert kode. Kalau perlu rollback KODE-nya sendiri (bukan
cuma flag), semua perubahan Patch 1-6 ada di satu commit terpisah di branch `business-hub-v2` —
`git revert` commit itu saja tanpa menyentuh commit Phase A-I lainnya.
