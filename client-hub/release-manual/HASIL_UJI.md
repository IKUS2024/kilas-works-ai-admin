# Hasil pengujian rilis self-service sebelumnya

Hasil berikut milik commit `69acf4d5281804b07faf091a7e76ceb726092923`. Tidak dijalankan ulang seluruhnya untuk patch integrasi dashboard. Hasil patch terbaru: `INTEGRASI_DASHBOARD_FINAL.md` dan `FINAL_REVIEW_METADATA/test-summary.txt`.

Client Hub: 71 file ditemukan; 70 modul berisi tes, 1470 tes Python, 0 failure, 0 error, 0 skip. Satu file historical test_ai_onboarding_features_enabled_fix.py kosong, tidak dihitung sebagai tes lulus.
Root aplikasi (source tidak diubah): 39 modul, 491 tes Python, 0 failure, 0 error, 0 skip; 3 pemeriksaan script saat import dilaporkan terpisah.
Finance 1A–6C: 496 tes (bagian dari Client Hub).
Final product/customer/trial/subscription: 86 tes (bagian dari Client Hub).
Finance Assistant Node DOM: 14 tes lulus.
WhatsApp signup Node fake SDK: 8 pemeriksaan script lulus.
TOTAL: 1975 test case terstruktur + 11 pemeriksaan script = 1986 kasus/pemeriksaan.
Tidak menjumlahkan rerun. Tidak menghitung pemeriksaan yang belum berhasil sebagai lulus.

Perintah (direktori client-hub):
python -B tests/run_finance_regressions.py --all-client-hub
python -B tests/run_finance_regressions.py --all-root
node --test tests/test_finance_assistant_ui.cjs
node tests/test_whatsapp_signup_ui.cjs

BELUM TERVERIFIKASI:
- PostgreSQL nyata: server, migrasi, FK/unique dan concurrency belum diuji; SQL/JSON adapter bukan PostgreSQL nyata.
- Anthropic nyata dan akurasi struk, myBCA PDF/screenshot nyata belum diuji; provider dimock.
- Browser visual mobile 360/390/430 px dan desktop: localhost ditolak ERR_BLOCKED_BY_CLIENT; tidak ada screenshot baru.
- Knowledge UI existing: pemanggilan awal gagal karena jsdom tidak tersedia; juga memerlukan HTML Knowledge yang dirender. Belum lulus.
- Instalasi dependency dari lingkungan kosong, production deployment, transfer bank, email dan Meta/WhatsApp nyata belum diuji.

Rincian per-suite: review-metadata/test-results.json dan manual/HASIL_UJI.md.

## Hasil per suite Python

| Suite | Tes | Gagal | Error | Skip | Pemeriksaan script |
|---|---:|---:|---:|---:|---:|
| test_absolute_final_production_patch | 19 | 0 | 0 | 0 | 0 |
| test_ai_admin_single_purchase_path | 12 | 0 | 0 | 0 | 0 |
| test_ai_onboarding_features_enabled_fix | 0 | 0 | 0 | 0 | 0 |
| test_ai_setup_reliability_and_persistence | 30 | 0 | 0 | 0 | 0 |
| test_ai_usage_diagnostics | 12 | 0 | 0 | 0 | 0 |
| test_ai_usage_fx | 11 | 0 | 0 | 0 | 0 |
| test_ai_usage_monthly_diagnostics | 8 | 0 | 0 | 0 | 0 |
| test_ai_usage_monthly_query | 3 | 0 | 0 | 0 | 0 |
| test_app_service_briefs | 18 | 0 | 0 | 0 | 0 |
| test_astra_ui_production | 5 | 0 | 0 | 0 | 0 |
| test_brain_ui_cleanup_light | 8 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_ecosystem_sync | 15 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_final_ops_polish | 35 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_phase_a | 19 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_phase_bcd | 32 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_phase_e | 5 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_phase_fgh | 13 | 0 | 0 | 0 | 0 |
| test_business_hub_v2_phase_i | 3 | 0 | 0 | 0 | 0 |
| test_business_sales_upgrade | 10 | 0 | 0 | 0 | 0 |
| test_catalog_editor_removed | 10 | 0 | 0 | 0 | 0 |
| test_checkout_payment_pending_fix | 22 | 0 | 0 | 0 | 0 |
| test_client_hub_batch1 | 16 | 0 | 0 | 0 | 0 |
| test_client_hub_batch2_3 | 14 | 0 | 0 | 0 | 0 |
| test_client_hub_ux_batch | 22 | 0 | 0 | 0 | 0 |
| test_client_hub_v1 | 22 | 0 | 0 | 0 | 0 |
| test_customer_dashboard_cleanup | 18 | 0 | 0 | 0 | 0 |
| test_final_product_flow | 86 | 0 | 0 | 0 | 0 |
| test_finance_phase1a | 15 | 0 | 0 | 0 | 0 |
| test_finance_phase1b | 16 | 0 | 0 | 0 | 0 |
| test_finance_phase2a | 25 | 0 | 0 | 0 | 0 |
| test_finance_phase2b | 22 | 0 | 0 | 0 | 0 |
| test_finance_phase3 | 19 | 0 | 0 | 0 | 0 |
| test_finance_phase4a | 15 | 0 | 0 | 0 | 0 |
| test_finance_phase4b | 35 | 0 | 0 | 0 | 0 |
| test_finance_phase4c | 25 | 0 | 0 | 0 | 0 |
| test_finance_phase5ab | 24 | 0 | 0 | 0 | 0 |
| test_finance_phase5c | 30 | 0 | 0 | 0 | 0 |
| test_finance_phase6a | 53 | 0 | 0 | 0 | 0 |
| test_finance_phase6b | 114 | 0 | 0 | 0 | 0 |
| test_finance_phase6c | 103 | 0 | 0 | 0 | 0 |
| test_inbox_media | 18 | 0 | 0 | 0 | 0 |
| test_inbox_responsive_parity | 9 | 0 | 0 | 0 | 0 |
| test_inbox_unification | 23 | 0 | 0 | 0 | 0 |
| test_k7_kopi_legacy_payment_and_ui_cleanup | 13 | 0 | 0 | 0 | 0 |
| test_knowledge_assist | 20 | 0 | 0 | 0 | 0 |
| test_knowledge_assist_parser | 12 | 0 | 0 | 0 | 0 |
| test_knowledge_blockers | 11 | 0 | 0 | 0 | 0 |
| test_knowledge_semantics | 15 | 0 | 0 | 0 | 0 |
| test_knowledge_setup_v2 | 13 | 0 | 0 | 0 | 0 |
| test_onboarding_auto_normalize | 5 | 0 | 0 | 0 | 0 |
| test_payment_checkout_reliability | 25 | 0 | 0 | 0 | 0 |
| test_payment_verification_strengthening | 16 | 0 | 0 | 0 | 0 |
| test_payment_vision_extraction | 16 | 0 | 0 | 0 | 0 |
| test_postgres_sql_adapter_external_audit | 2 | 0 | 0 | 0 | 0 |
| test_production_foundation | 26 | 0 | 0 | 0 | 0 |
| test_repo_ai_settings_postgres_json_compat | 16 | 0 | 0 | 0 | 0 |
| test_resend_forgot_password | 9 | 0 | 0 | 0 | 0 |
| test_service_facts_polish | 10 | 0 | 0 | 0 | 0 |
| test_service_selection_purchase_flow | 26 | 0 | 0 | 0 | 0 |
| test_simulation_cost_limits | 11 | 0 | 0 | 0 | 0 |
| test_single_plan_release | 23 | 0 | 0 | 0 | 0 |
| test_smtp_security_source_checks | 5 | 0 | 0 | 0 | 0 |
| test_subscription_backfill | 16 | 0 | 0 | 0 | 0 |
| test_subscription_lifecycle | 31 | 0 | 0 | 0 | 0 |
| test_talent_photo_upload_ux | 5 | 0 | 0 | 0 | 0 |
| test_targeted_production_upgrade | 19 | 0 | 0 | 0 | 0 |
| test_tenant_persistence_repos | 12 | 0 | 0 | 0 | 0 |
| test_ux_catalog_final | 23 | 0 | 0 | 0 | 0 |
| test_wa_checkout | 26 | 0 | 0 | 0 | 0 |
| test_whatsapp_self_service | 35 | 0 | 0 | 0 | 0 |
| test_white_screen_payment_bug | 15 | 0 | 0 | 0 | 0 |
| root:test_absolute_final_production_patch | 15 | 0 | 0 | 0 | 0 |
| root:test_adversarial_audit | 15 | 0 | 0 | 0 | 0 |
| root:test_appointment_flow_fix | 10 | 0 | 0 | 0 | 0 |
| root:test_appointment_payment_update | 14 | 0 | 0 | 0 | 0 |
| root:test_appointment_reminders | 0 | 0 | 0 | 0 | 1 |
| root:test_appointments | 6 | 0 | 0 | 0 | 0 |
| root:test_astra_production_fix | 24 | 0 | 0 | 0 | 0 |
| root:test_brand_landing_catalog | 16 | 0 | 0 | 0 | 0 |
| root:test_business_hub_v2_whatsapp_integration | 15 | 0 | 0 | 0 | 0 |
| root:test_demo_cost_limits | 7 | 0 | 0 | 0 | 0 |
| root:test_demo_domain_integration | 17 | 0 | 0 | 0 | 0 |
| root:test_demo_ux | 0 | 0 | 0 | 0 | 1 |
| root:test_ecosystem_sync_bot | 16 | 0 | 0 | 0 | 0 |
| root:test_final_launch_qa | 10 | 0 | 0 | 0 | 0 |
| root:test_inbox_media_webhook | 9 | 0 | 0 | 0 | 0 |
| root:test_knowledge_architecture | 8 | 0 | 0 | 0 | 0 |
| root:test_landing_page_polish | 7 | 0 | 0 | 0 | 0 |
| root:test_language_layer | 12 | 0 | 0 | 0 | 0 |
| root:test_multi_tenant_runtime_safety | 28 | 0 | 0 | 0 | 0 |
| root:test_official_links_light | 14 | 0 | 0 | 0 | 0 |
| root:test_owner_catalog | 13 | 0 | 0 | 0 | 0 |
| root:test_owner_intent_target_resolution | 9 | 0 | 0 | 0 | 0 |
| root:test_owner_nlu | 6 | 0 | 0 | 0 | 0 |
| root:test_platform_reply_diagnostics | 5 | 0 | 0 | 0 | 0 |
| root:test_platform_takeover | 5 | 0 | 0 | 0 | 0 |
| root:test_prelaunch_hardening | 20 | 0 | 0 | 0 | 0 |
| root:test_price_transport_uncertainty_guardrails | 12 | 0 | 0 | 0 | 0 |
| root:test_pro_tenant_parity | 26 | 0 | 0 | 0 | 0 |
| root:test_production_hardening | 0 | 0 | 0 | 0 | 1 |
| root:test_sales_brain_v2 | 27 | 0 | 0 | 0 | 0 |
| root:test_sales_engine | 17 | 0 | 0 | 0 | 0 |
| root:test_single_plan_context | 9 | 0 | 0 | 0 | 0 |
| root:test_targeted_owner_upgrade | 7 | 0 | 0 | 0 | 0 |
| root:test_tenant_followup | 21 | 0 | 0 | 0 | 0 |
| root:test_tenant_owner_media_and_isolation | 9 | 0 | 0 | 0 | 0 |
| root:test_tenant_persistence_and_payment_review | 9 | 0 | 0 | 0 | 0 |
| root:test_unified_ai_brain_v2 | 25 | 0 | 0 | 0 | 0 |
| root:test_voice_note | 23 | 0 | 0 | 0 | 0 |
| root:test_voice_note_production_bugfix | 5 | 0 | 0 | 0 | 0 |

File test_ai_onboarding_features_enabled_fix.py memiliki 0 tes karena file baseline kosong. Bukan suite yang dinyatakan lulus; runner mencatat empty_modules=1.

## Konkurensi dan idempotensi

SQLite menggunakan thread/koneksi terpisah: trial hanya satu, business/account setup hanya satu, tagihan pending hanya satu, verifikasi paralel hanya menambah satu periode, verify/reject hanya satu keputusan; audit failure rollback. Replay nonce tagihan setelah verified tetap mengembalikan tagihan asal. Recurring terpilih tidak menduplikasi/advance yang tidak dipilih; VOID tidak dibuat ulang. Full Phase 6B menjaga POST/POST dan POST/MATCH hanya satu keputusan, row/ledger atomik. Receipt/Operator duplicate dan signed confirmation tetap lulus regresi.

## Makna hasil dan pemeriksaan tertahan

Provider dimock dan outbound socket Python diblokir termasuk subprocess. Node memakai DOM/fake SDK, bukan browser visual. Uji end-to-end HTTP memakai Flask test client dengan DB disposable; ini tidak membuktikan kamera perangkat, layout mobile atau integrasi provider nyata. Pengujian awal menemukan ekspektasi lama terkait GET checkout dan label; diperbaiki dengan mempertahankan intent lalu rerun penuh. Hanya hasil penerimaan akhir di atas dihitung.

Knowledge UI pernah dicoba bersama wildcard `node --test tests/*.cjs`, gagal karena `jsdom` tidak tersedia; dibutuhkan juga HTML halaman yang dirender. Ini adalah satu suite UI tertahan, bukan skip yang termasuk angka runner Python. Browser cloud menolak localhost; tidak ada screenshot buatan. PostgreSQL lokal tidak tersedia. Tidak dilakukan push, deploy, production migration, transfer bank atau pengiriman pesan pelanggan.

## Perintah dan bukti

Log penerimaan dan ringkasan JSON berada di `review-metadata/`. Perintah dijalankan dari direktori `client-hub`. Perubahan setelah acceptance run hanya dokumentasi dan builder ZIP; source aplikasi yang diuji tidak berubah. ZIP diverifikasi CRC, manifest checksum dan perbandingan extracted committed source saat pengemasan.
