# Panduan Migrasi: Menyambungkan Bot Produksi ke Client Hub (Phase 5)

Dokumen ini menjelaskan LANGKAH KONKRET untuk membuat `../app.py` (bot WhatsApp produksi) menjadi
tenant-aware menggunakan `tenant_config_service.py`, **tanpa** rewrite besar dan **tanpa** regresi
terhadap fungsi yang sudah jalan. Ini adalah dokumentasi untuk migrasi MASA DEPAN — belum
dikerjakan di cycle ini, sesuai instruksi eksplisit "do not tightly couple Client Hub UI directly
to app.py" dan "do not migrate everything at once if risky."

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

## Langkah migrasi yang disarankan (BELUM dikerjakan, untuk referensi)

Migrasi ini SENGAJA dipecah jadi 3 patch kecil dan terpisah, masing-masing dengan regresi test
penuh sebelum lanjut ke patch berikutnya — bukan satu rewrite besar.

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

## Kapan TIDAK melakukan migrasi ini

Jangan jalankan Patch 2/3 sampai:
1. Minimal satu tenant klien nyata sudah diaktivasi lewat Client Hub (APPROVE + ACTIVATE),
2. `whatsapp_phone_number_id` klien tersebut benar-benar terhubung ke Meta (bukan cuma diisi di
   form admin — divalidasi nyata lewat percobaan kirim/terima WhatsApp),
3. Regresi 14 test bot + suite Client Hub tetap 100% PASS setelah tiap patch.

## Rollback

Setiap patch di atas dilindungi oleh flag/precondisi (`tenant_id is None` atau
`ENABLE_MULTI_TENANT=false`) yang membuatnya no-op secara default. Rollback = set env var balik ke
`false`/hapus flag, tidak perlu revert kode.
