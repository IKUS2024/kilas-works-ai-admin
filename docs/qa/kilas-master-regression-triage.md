# Historical regression triage — master release

The full historical repository run is **not** reported green. The baseline comparison below was run against remote main4344748 once, with separate pytest processes and the Client Hub cwd. Master release CI Phase2–10 plus focused Assist/native-PG checks are the applicable release gates. Failures were not deleted or skipped to make those gates green.

Completed corrections retain ownership, CSRF, historical financial amounts, rollback/idempotency and tenant isolation. The old public-channel and Coexistence tests now explicitly verify the retired endpoints fail closed; positive flows are covered by the assisted workflow tests. Remaining unchanged historical failures include old multi-product service/catalog/admin dashboards and incomplete legacy onboarding fixtures. Their baseline result is recorded, not waived as passing. Final supported Assist + separate Finance journeys are exercised by Phase10 and master QA.

| Suite | Main baseline comparison | Earlier master comparison | Latest targeted result |
|---|---|---|---|
| test_absolute_final_production_patch | 19 passed in 2.02s | 1 failed, 18 passed in 2.00s | 19 PASS |
| test_ai_admin_single_purchase_path | 4 failed, 8 passed in 2.39s | 6 failed, 6 passed in 2.37s | 12 PASS |
| test_ai_onboarding_features_enabled_fix | Not collected; script-only module | no tests ran in 0.02s | Historical failure remains documented; see baseline and scope above |
| test_ai_setup_reliability_and_persistence | 8 failed, 22 passed in 5.31s | 8 failed, 22 passed in 5.29s | 30 PASS |
| test_app_service_briefs | 18 failed, 15 passed, 4 subtests passed in 5.19s | 18 failed, 15 passed, 4 subtests passed in 5.51s | Historical failure remains documented; see baseline and scope above |
| test_brain_ui_cleanup_light | 4 failed, 4 passed in 2.37s | 4 failed, 4 passed in 2.74s | Historical failure remains documented; see baseline and scope above |
| test_business_hub_v2_ecosystem_sync | 2 failed, 13 passed in 3.12s | 2 failed, 13 passed in 3.40s | Historical failure remains documented; see baseline and scope above |
| test_business_hub_v2_final_ops_polish | 5 failed, 30 passed in 7.45s | 5 failed, 30 passed in 8.31s | Historical failure remains documented; see baseline and scope above |
| test_business_hub_v2_phase_a | 1 failed, 19 passed in 3.79s | 1 failed, 19 passed in 4.18s | 20 PASS |
| test_business_hub_v2_phase_bcd | 9 failed, 23 passed in 5.97s | 10 failed, 22 passed in 6.79s | Historical failure remains documented; see baseline and scope above |
| test_business_hub_v2_phase_e | 5 failed in 1.79s | 5 failed in 1.87s | Historical failure remains documented; see baseline and scope above |
| test_catalog_editor_removed | 10 passed in 2.33s | 2 failed, 8 passed in 2.43s | 10 PASS |
| test_checkout_payment_pending_fix | 1 failed, 21 passed in 3.80s | 1 failed, 21 passed in 3.90s | 22 PASS |
| test_client_hub_batch1 | 5 failed, 11 passed in 4.62s | 5 failed, 11 passed in 4.88s | Historical failure remains documented; see baseline and scope above |
| test_client_hub_batch2_3 | 1 failed, 13 passed in 3.32s | 1 failed, 13 passed in 3.43s | Historical failure remains documented; see baseline and scope above |
| test_client_hub_ux_batch | 6 failed, 16 passed in 4.48s | 6 failed, 16 passed in 4.87s | Historical failure remains documented; see baseline and scope above |
| test_client_hub_v1 | 4 failed, 18 passed in 5.13s | 5 failed, 17 passed in 5.17s | 22 PASS |
| test_customer_dashboard_cleanup | 3 failed, 15 passed, 8 subtests passed in 4.83s | 3 failed, 15 passed, 8 subtests passed in 5.05s | 18 PASS |
| test_dashboard_finance_integration | 8 failed, 5 passed in 1.58s | 11 failed, 2 passed in 1.55s | Historical failure remains documented; see baseline and scope above |
| test_final_product_flow | 13 failed, 84 passed in 8.18s | 14 failed, 83 passed in 8.08s | Historical failure remains documented; see baseline and scope above |
| test_inbox_unification | 25 passed in 7.80s | 1 failed, 24 passed in 7.69s | 25 PASS |
| test_k7_kopi_legacy_payment_and_ui_cleanup | 3 failed, 10 passed in 3.09s | 3 failed, 10 passed in 3.11s | Historical failure remains documented; see baseline and scope above |
| test_onboarding_auto_normalize | 4 failed, 1 passed in 1.27s | 4 failed, 1 passed in 1.34s | 5 PASS |
| test_paid_ai_lifecycle | 8 passed in 0.97s | 1 failed, 7 passed in 1.04s | 8 PASS |
| test_payment_checkout_reliability | 1 failed, 24 passed in 5.07s | 4 failed, 21 passed in 4.89s | 25 PASS |
| test_production_foundation | 7 failed, 19 passed in 4.55s | 2 failed, 24 passed in 4.72s | 26 PASS |
| test_service_facts_polish | 2 failed, 8 passed in 2.93s | 2 failed, 8 passed in 2.94s | Historical failure remains documented; see baseline and scope above |
| test_service_selection_purchase_flow | 10 failed, 16 passed in 6.33s | 11 failed, 15 passed in 6.33s | Historical failure remains documented; see baseline and scope above |
| test_subscription_lifecycle | 31 passed in 6.83s | 1 failed, 30 passed in 6.52s | 31 PASS |
| test_ux_catalog_final | 4 failed, 19 passed in 6.91s | 4 failed, 19 passed in 6.94s | Historical failure remains documented; see baseline and scope above |
| test_wa_checkout | 2 failed, 25 passed, 9 subtests passed in 6.93s | 2 failed, 25 passed, 9 subtests passed in 6.82s | Historical failure remains documented; see baseline and scope above |
| test_whatsapp_self_service | 41 passed in 10.54s | 33 failed, 8 passed in 10.18s | 41 PASS |
| test_white_screen_payment_bug | 3 failed, 12 passed in 2.45s | 3 failed, 12 passed in 2.43s | Historical failure remains documented; see baseline and scope above |

Original detailed diagnostics: `/tmp/kilas-baseline-comparison`, `/tmp/kilas-remaining-regression`, `/tmp/kilas-final-*`. This report is a failure inventory, not a replacement for the durable completion checkpoint or CI results.
