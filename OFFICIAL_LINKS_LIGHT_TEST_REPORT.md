# Focused offline test report

Baseline `6c39951e911089e6c561da218cb3246684d050d1`; final `e63536090f9688bcf14ad477aca01f4c2ced953a`.

Final: **16/16 test files PASS**, 0 unresolved failure. Test baru: **14/14 unit cases PASS**. Existing catalog UX: **23/23 cases PASS**. Count file bukan jumlah individual assertions; unit cases ini sudah termasuk file-count, tidak dijumlah dua kali.

Initial focused test12cases lulus; penambahan tes purchase menemukan fixture nomor non-telepon, diperbaiki menggunakan synthetic numeric phone dan catalog seed nyata. Existing UX test mengharapkan tenant None dan generic multi-link; ekspektasi diperbarui menjadi tenant-safe unavailable/satu link, dengan isolation assertion tetap. Regresi juga menemukan alias daftar layanan tertangkap purchase guard; alias catalog existing dipulihkan sebelum guard dan diperluas coverage. Tidak ada payment atau catalog production code diubah untuk membuat tes lolos.

Runner menjalankan setiap file Python dalam subprocess terisolasi dengan PYTHONPATH scripts/offline_tests (network denied). Targeted reruns menyelesaikan kegagalan tadi; tidak menjalankan seluruh repository suite karena task Light. Tidak ada paid AI atau WhatsApp call. Send/Claude dimock. Scope safety di-review melalui diff dan AST comparison untuk catalog transport.

| File | Hasil |
|---|---|
| test_official_links_light.py | PASS |
| test_owner_catalog.py | PASS |
| test_owner_nlu.py | PASS |
| test_owner_intent_target_resolution.py | PASS |
| test_targeted_owner_upgrade.py | PASS |
| test_tenant_owner_media_and_isolation.py | PASS |
| test_multi_tenant_runtime_safety.py | PASS |
| test_tenant_persistence_and_payment_review.py | PASS |
| test_astra_production_fix.py | PASS |
| test_unified_ai_brain_v2.py | PASS |
| test_single_plan_context.py | PASS |
| test_platform_reply_diagnostics.py | PASS |
| test_platform_takeover.py | PASS |
| client-hub/tests/test_ux_catalog_final.py | PASS |
| client-hub/tests/test_business_sales_upgrade.py | PASS |
| client-hub/tests/test_wa_checkout.py | PASS |

Cakupan: owner alias website/demo/Instagram/Client Hub; webhook routing sebelum target-send; customer direct website; bounded follow-up; demo relevan saja; satu exploratory CTA; purchase Setup Awal; owner/direct-send/catalog attachment; tenant owner/customer no platform fallback; cross-tenant runtime/persistence; Human Takeover; pricing/checkout unchanged; shared brain/context; safe missing URL/invalid URL; compact query-gated fallback. Tidak ada perubahan source setelah final tests. Live deployment tidak dilakukan.
