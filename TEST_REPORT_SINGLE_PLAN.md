# Test report — offline release

Baseline `1424ac4620f46f789db70ccc79100181a4887937`; final commit `7d2e11933a100c9134ef31421e90cad74a1d9371`. Production code tidak diubah setelah verification final. No paid AI calls. Python runner memakai scripts/offline_tests/sitecustomize.py untuk menolak koneksi jaringan termasuk child process. External provider responses dimock. npm hanya menginstal jsdom test-only ke /tmp; tidak menambah dependency atau lockfile aplikasi. JS fetch sepenuhnya dimock.

## Hitungan yang benar

- Full runner repository: **89 file Python** dicakup. Run awal penuh: **60 PASS / 29 FAIL**. Bukan full-green awal.
- Dari 29 kegagalan awal, 21 direproduksi pada detached baseline tanpa perubahan, 8 lulus baseline sehingga ditangani sebagai ekspektasi/fixture terdampak rilis.
- Setelah perbaikan dan targeted reruns semua 29 file yang gagal: **89/89 file berstatus PASS**, 0 unresolved FAIL. Full suite tidak diulang berkali-kali.
- Regression ulang root setelah bootstrap/context berubah: **38/38 file PASS**. Empat regresi vision diulang setelah cap byte final, semuanya PASS.
- Tambahan file yang tidak didaftarkan runner: tests/test_customer_dashboard_cleanup.py **18 cases PASS** dan tests/test_inbox_responsive_parity.py **9 cases PASS**. Total cakupan Python **91 file runners**, bukan klaim 91 individual assertions.
- Kasus baru release: test_single_plan_context.py **9/9 PASS**, client-hub/tests/test_single_plan_release.py **23/23 PASS** = **32/32**. Ini bagian dari 89, tidak ditambahkan ulang ke total file.
- Browser JS existing: test_knowledge_assist_ui.cjs **8/8 PASS**, menggunakan HTML Knowledge page yang dirender dari fixture authorized. Dependency jsdom26 lokal diperlukan; percobaan pertama tanpa dependency/arg adalah setup error, resolved sebelum final.
- PostgreSQL nyata: **NOT RUN**. postgres/initdb/pg_ctl/psql/Docker/Podman tidak tersedia. Test kompatibilitas adapter/JSONB dan review SQL bukan pengganti real server test.
- git diff --check PASS; parent tepat baseline, satu commit; static official PDF, ai_brain_shared.py, knowledge_setup.py, wa_checkout.py tidak berubah.

## Cakupan kasus baru

Canonical plan499000, all existing Pro flags/currentplan; NONE; legacy historical prices/rows; Basic/Pro new catalog retirement; catalog edit/reseed; verified transition/current subscription guards; paid-only entitlement and expiry; safe cost totals/currency/cache 5m+1h; unknown model; malformed content cost vs response; business scope/admin gate; response fairuse75%/100% no shutdown; independent ledger transaction and fail-open failure; platform ledger separate; full history retention; lexical old-fact retrieval; deterministic order/dedupe; three runtime paths compact; one normal model call; EXIF/resize/no upscale/invalid input/large noise image <4.5MB.

## Fixture maintenance tanpa melemahkan safety

Perubahan test lama mempertahankan assertion tenant ownership, CSRF/gating, historical locks, file validation dan canonical price. Ekspektasi retired bundles/oldtier sales dan harga Content yang sudah stale diganti sesuai source-of-truth baseline/rilis. Test yang menggunakan URL pembelian lama sekarang melalui brief/review nyata sebelum invoice. Fake base64 vision diganti gambar JPEG valid; message table fixture mengikuti schema production yang sebelumnya tidak dibuat oleh Hub-only migrations. JSONB test memakai business row nyata agar shared lock tidak dibypass. Scope runtime tidak diubah agar tes lolos.

## Cara mengulang

```sh
python scripts/run_offline_tests.py
```

Tambahan root tests/ membutuhkan PYTHONPATH berisi scripts/offline_tests, client-hub/tests dan client-hub. JS menggunakan node + jsdom26 dengan arg HTML Knowledge page fixture yang dirender; tidak membutuhkan provider key. Normal npm test repo masih placeholder baseline, bukan suite aplikasi; runner Python dan JS di atas adalah executable suites yang tersedia.

## Hasil akhir per file runner utama

| File | Status terakhir |
|---|---|
| client-hub/tests/test_absolute_final_production_patch.py | PASS |
| client-hub/tests/test_ai_admin_single_purchase_path.py | PASS |
| client-hub/tests/test_ai_onboarding_features_enabled_fix.py | PASS |
| client-hub/tests/test_ai_setup_reliability_and_persistence.py | PASS |
| client-hub/tests/test_app_service_briefs.py | PASS |
| client-hub/tests/test_astra_ui_production.py | PASS |
| client-hub/tests/test_business_hub_v2_ecosystem_sync.py | PASS |
| client-hub/tests/test_business_hub_v2_final_ops_polish.py | PASS |
| client-hub/tests/test_business_hub_v2_phase_a.py | PASS |
| client-hub/tests/test_business_hub_v2_phase_bcd.py | PASS |
| client-hub/tests/test_business_hub_v2_phase_e.py | PASS |
| client-hub/tests/test_business_hub_v2_phase_fgh.py | PASS |
| client-hub/tests/test_business_hub_v2_phase_i.py | PASS |
| client-hub/tests/test_business_sales_upgrade.py | PASS |
| client-hub/tests/test_catalog_editor_removed.py | PASS |
| client-hub/tests/test_checkout_payment_pending_fix.py | PASS |
| client-hub/tests/test_client_hub_batch1.py | PASS |
| client-hub/tests/test_client_hub_batch2_3.py | PASS |
| client-hub/tests/test_client_hub_ux_batch.py | PASS |
| client-hub/tests/test_client_hub_v1.py | PASS |
| client-hub/tests/test_customer_dashboard_cleanup.py | PASS |
| client-hub/tests/test_inbox_media.py | PASS |
| client-hub/tests/test_inbox_responsive_parity.py | PASS |
| client-hub/tests/test_inbox_unification.py | PASS |
| client-hub/tests/test_k7_kopi_legacy_payment_and_ui_cleanup.py | PASS |
| client-hub/tests/test_knowledge_assist.py | PASS |
| client-hub/tests/test_knowledge_assist_parser.py | PASS |
| client-hub/tests/test_knowledge_blockers.py | PASS |
| client-hub/tests/test_knowledge_semantics.py | PASS |
| client-hub/tests/test_knowledge_setup_v2.py | PASS |
| client-hub/tests/test_onboarding_auto_normalize.py | PASS |
| client-hub/tests/test_payment_checkout_reliability.py | PASS |
| client-hub/tests/test_payment_verification_strengthening.py | PASS |
| client-hub/tests/test_payment_vision_extraction.py | PASS |
| client-hub/tests/test_postgres_sql_adapter_external_audit.py | PASS |
| client-hub/tests/test_production_foundation.py | PASS |
| client-hub/tests/test_repo_ai_settings_postgres_json_compat.py | PASS |
| client-hub/tests/test_resend_forgot_password.py | PASS |
| client-hub/tests/test_service_facts_polish.py | PASS |
| client-hub/tests/test_service_selection_purchase_flow.py | PASS |
| client-hub/tests/test_simulation_cost_limits.py | PASS |
| client-hub/tests/test_single_plan_release.py | PASS |
| client-hub/tests/test_smtp_security_source_checks.py | PASS |
| client-hub/tests/test_subscription_backfill.py | PASS |
| client-hub/tests/test_subscription_lifecycle.py | PASS |
| client-hub/tests/test_talent_photo_upload_ux.py | PASS |
| client-hub/tests/test_targeted_production_upgrade.py | PASS |
| client-hub/tests/test_tenant_persistence_repos.py | PASS |
| client-hub/tests/test_ux_catalog_final.py | PASS |
| client-hub/tests/test_wa_checkout.py | PASS |
| client-hub/tests/test_white_screen_payment_bug.py | PASS |
| top-level/test_absolute_final_production_patch.py | PASS |
| top-level/test_adversarial_audit.py | PASS |
| top-level/test_appointment_flow_fix.py | PASS |
| top-level/test_appointment_payment_update.py | PASS |
| top-level/test_appointment_reminders.py | PASS |
| top-level/test_appointments.py | PASS |
| top-level/test_astra_production_fix.py | PASS |
| top-level/test_brand_landing_catalog.py | PASS |
| top-level/test_business_hub_v2_whatsapp_integration.py | PASS |
| top-level/test_demo_cost_limits.py | PASS |
| top-level/test_demo_domain_integration.py | PASS |
| top-level/test_demo_ux.py | PASS |
| top-level/test_ecosystem_sync_bot.py | PASS |
| top-level/test_final_launch_qa.py | PASS |
| top-level/test_inbox_media_webhook.py | PASS |
| top-level/test_knowledge_architecture.py | PASS |
| top-level/test_landing_page_polish.py | PASS |
| top-level/test_language_layer.py | PASS |
| top-level/test_multi_tenant_runtime_safety.py | PASS |
| top-level/test_owner_catalog.py | PASS |
| top-level/test_owner_intent_target_resolution.py | PASS |
| top-level/test_owner_nlu.py | PASS |
| top-level/test_platform_reply_diagnostics.py | PASS |
| top-level/test_platform_takeover.py | PASS |
| top-level/test_prelaunch_hardening.py | PASS |
| top-level/test_price_transport_uncertainty_guardrails.py | PASS |
| top-level/test_pro_tenant_parity.py | PASS |
| top-level/test_production_hardening.py | PASS |
| top-level/test_sales_brain_v2.py | PASS |
| top-level/test_sales_engine.py | PASS |
| top-level/test_single_plan_context.py | PASS |
| top-level/test_targeted_owner_upgrade.py | PASS |
| top-level/test_tenant_followup.py | PASS |
| top-level/test_tenant_owner_media_and_isolation.py | PASS |
| top-level/test_tenant_persistence_and_payment_review.py | PASS |
| top-level/test_unified_ai_brain_v2.py | PASS |
| top-level/test_voice_note.py | PASS |
| top-level/test_voice_note_production_bugfix.py | PASS |

Tidak ada log raw customer, secret atau media disertakan dalam ZIP. Semua data test sintetis. Warnings persistence_failed di failure-injection cases adalah hasil yang diharapkan; backend normal harus tidak menunjukkan failure tersebut saat smoke test staging.
