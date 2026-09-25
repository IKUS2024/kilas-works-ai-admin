# Phase 7 Finance recovery: original failure classification

Resumed checkpoint `8f33dd8de8bb14bb68dae2b64c3a12365ab166cb`. This inventory covers every original failing method (repeated subtest variants share the same diagnosis). Causes were verified against current services, templates and isolated reruns; these are not 186 independent product bugs. Final counts and unresolved blocker are in `KILAS_V2_PHASE7_STATUS.md`.

Classification: **S** stale fixture / old expected contract; **U** UI selector/label drift with valid invariant; **P** genuine production bug; **I** intentional current product behavior requiring updated coverage.

| Root cause | Class | Verified cause / disposition |
| --- | --- | --- |
| money | S | Historical major/minor fixture or supported decimal contract; scale 100 preserved. |
| catalog | S | Old category catalog/base-row fixture; current workspace settings and history retained. |
| ui | U | Current rendered labels, selectors or route location; data/action invariant retained. |
| scope | I | Default workspace resolution or explicit all-scope POST rejection; foreign/conflicting writes still denied. |
| grouped | S | Old flattened report adapter; read native-currency groups independently. |
| review | I | Current required review fields/order, ONCE default or conservative account clarification; no implicit write. |
| bankhold | I | Retired catch-all categories no longer auto-post unmatched bank rows; explicit review and FX holds retained. |
| longrange | I | Current 240-month/7305-day limits support all-time reports; over-limit rejection retained. |
| scheduled | I | Historical scheduled category identity retained; new manual inactive-category writes rejected. |
| cron | I | Read-only due-rule checker never posts cash; exact no-write snapshot and sanitized failure checked. |
| payment | I | Bill payment requires explicit payment account/date, then posts exactly once. |
| schema | S | Mock response/sequence must follow current typed model contract and actual pending field. |
| quota | S | Independent negative cases exhausted shared model quota before positive case; dedicated quota tests retained. |
| clock | S | All-time end is current business date; period cash flow differs from cumulative account balance. |
| firstget | P | Fixed category synchronization before first branch exists; GET/CSRF/auth regressions pass. |
| branchdelete | P | Fixed workspace metadata FK deletion; history archives and audit-failure rollback retained. |
| budget | P | Fixed obsolete category mutation route by using audited workspace category service. |
| bankinput | P | Fixed raw minor-unit review input; exact decimal HTTP round-trip covered for IDR/JPY/USD. |
| move | P | RESOLVED: audited monotonic correction command; raw branch/business guards retained, 12 new regressions and both original positive move tests pass. See workspace correction design/status. |

## test_finance_assistant_inline.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_exact_invoice_payment_reuses_service_once` | S | money |
| `test_bank_chat_confirmation_posts_safe_rows_without_redirect` | I | bankhold |
| `test_chat_is_finance_only_and_monthly_language_becomes_recurring` | I | review |
| `test_common_idr_shorthand_is_understood_without_amount_rewrite` | S | money |
| `test_expense_fills_draft_no_write_and_confirm_once` | S | money |

## test_finance_bank_sections.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_decimal_precision_preserved_and_held` | S | money |
| `test_idr_account_warning_and_confirmation_replay` | I | bankhold |
| `test_multi_currency_account_choice_and_signed_context_override` | I | bankhold |
| `test_review_html_shows_holds_and_original_precision` | P | bankinput |
| `test_fx_and_precision_holds_survive_edit_and_block_ledger_writes` | S | money |
| `test_reset_cancelled_import_can_be_confirmed_again_without_stale_review` | I | bankhold |
| `test_separate_accounts_same_file_and_idempotent_confirmation` | I | bankhold |
| `test_text_fallback_sends_only_selected_section_and_visual_keeps_currency` | S | money |
| `test_visual_mixed_rows_filtered_and_unknown_currency_rejected` | S | money |

## test_finance_branches.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_branch_account_category_rename_deactivate_preserves_history` | S | catalog |
| `test_branch_routes_and_last_active_guard` | P | branchdelete |
| `test_delete_empty_branch_removes_it_instead_of_leaving_nonactive_choice` | P | branchdelete |
| `test_reports_export_branch_labels_period_and_pdf` | S | money |
| `test_transaction_edit_revision_cancel_and_lainnya` | S | catalog |
| `test_legacy_history_default_and_repeat_migration` | S | money |
| `test_branch_period_filter_links_and_csrf` | U | ui |
| `test_dashboard_redirects_archived_branch_to_active_branch` | I | scope |
| `test_essential_settings_cannot_all_be_deleted` | S | catalog |
| `test_last_account_for_currency_with_balance_is_protected` | I | scope |
| `test_legacy_all_get_resolves_default_branch_but_all_writes_stay_rejected` | I | scope |
| `test_legacy_first_setup_does_not_make_all_mode_writable` | I | scope |
| `test_missing_fx_rate_never_returns_partial_combined_balance` | U | ui |
| `test_monthly_totals_and_current_balances_remain_branch_scoped` | U | ui |
| `test_new_finance_setup_has_working_defaults` | U | ui |
| `test_opening_foreign_balance_is_not_period_income_and_is_explained` | U | ui |
| `test_unscoped_multibranch_post_and_conflicting_selector_rejected` | I | scope |

## test_finance_conversation_agent.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_model_patch_accepts_raw_values_never_ids_or_action` | S | quota |
| `test_payment_partial_then_full_retry_no_duplicates` | S | money |
| `test_all_branch_dashboard_offers_readonly_assistant` | I | scope |
| `test_all_branches_reads_and_write_branch_choice` | I | scope |
| `test_all_time_report_and_readonly_followup_context` | S | money |
| `test_currency_document_context_filters_bank_accounts` | S | schema |
| `test_english_july_and_month_aliases_are_understood` | S | money |
| `test_finance_domain_refusal` | U | ui |
| `test_income_bca_confirm_replay_and_optional_fields_persist` | S | money |
| `test_invoice_create_review_exactly_once_no_issue_no_ledger` | S | money |
| `test_readonly_followup_can_change_metric_without_losing_period` | S | money |
| `test_recurring_inventory_question_is_not_generic_empty_report` | U | ui |
| `test_recurring_missing_fields_are_collected_in_order` | I | review |
| `test_recurring_without_frequency_does_not_assume_monthly` | I | review |
| `test_scoped_piutang_and_customer_search` | S | money |

## test_finance_conversational_boundaries.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_amount_account_category_then_confirm_once` | S | money |
| `test_capabilities_are_current_and_do_not_claim_money_transfers` | U | ui |
| `test_existing_list_phrases_and_english_plurals` | U | ui |
| `test_screenshot_customer_list_uses_semantic_scope` | U | ui |
| `test_semantic_list_scope_applies_across_entity_types` | U | ui |

## test_finance_dashboard_design.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_bill_payment_uses_same_projection_and_existing_payment_endpoint` | U | ui |
| `test_report_limit_shows_unavailable_not_fake_zero` | U | ui |

## test_finance_fx_precision.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_combined_total_rounds_once` | S | money |

## test_finance_home_dashboard.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_account_workspace_move_moves_opening_balance_transactions_and_recurring_rule` | P | move |
| `test_transaction_workspace_move_is_real_reversible_and_never_double_counts` | P | move |
| `test_accounts_view_lists_accounts_then_opens_dedicated_account_page` | U | ui |
| `test_bill_payment_uses_real_payment_date_subcategory_and_updates_actuals_once` | S | money |
| `test_bills_page_uses_homebudget_calendar_list_and_recurring_views` | U | ui |
| `test_bills_recurring_rules_have_edit_and_safe_delete` | S | money |
| `test_budget_page_adds_and_renames_expense_categories_in_place` | P | budget |
| `test_business_home_surfaces_invoice_status_without_mixing_with_personal` | U | ui |
| `test_business_income_catalog_is_clean_and_has_useful_top_level_choices` | S | catalog |
| `test_direction_category_rows_drill_into_parent_and_subcategory_transactions` | U | ui |
| `test_direction_views_are_category_first_with_inline_totals` | U | ui |
| `test_empty_dashboard_shows_real_zero_budget_and_omits_attention` | U | ui |
| `test_finance_global_navigation_has_dashboard_and_exit` | U | ui |
| `test_finance_pages_hide_client_hub_topbar_and_offer_dashboard_back` | U | ui |
| `test_home_uses_translated_homebudget_primary_sections` | U | ui |
| `test_reports_support_all_time_and_custom_date_ranges` | S | clock |
| `test_transaction_form_can_add_income_and_expense_categories_in_place` | U | ui |

## test_finance_invoice_editor.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_list_compact_search_status_archive_pagination` | U | ui |

## test_finance_live_conversation.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_changed_outstanding_requires_new_review_and_oke` | S | money |
| `test_concurrent_partial_confirmation_posts_once` | S | money |
| `test_inactive_recurring_and_changed_balances_are_live` | S | money |
| `test_lunas_can_be_corrected_to_partial_and_same_customer_read_after_payment` | S | money |
| `test_lunas_full_payment_review_oke_paid_and_single_ledger` | S | money |
| `test_multiple_open_invoices_require_choice_and_do_not_select_other_customer` | S | money |
| `test_new_customer_query_switches_pronoun_and_unknown_does_not_reuse_old_person` | S | money |
| `test_partial_over_current_outstanding_is_re_reviewed_without_adjusting_amount_silently` | S | money |
| `test_partial_payment_uses_canonical_status_and_cash_once` | S | money |
| `test_read_entity_survives_pronoun_rename_void_and_stale_note` | S | money |
| `test_refreshed_same_partial_review_keeps_payment_idempotency_key` | S | money |

## test_finance_multibusiness.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_admin_overview_still_uses_memberships_only` | S | grouped |
| `test_all_business_view_has_no_finance_writes_or_assistant` | S | grouped |
| `test_cash_totals_sum_only_posted_idr_in_selected_month` | S | grouped |
| `test_empty_business_zero_without_initialization_or_writes` | S | grouped |
| `test_expired_and_emergency_read_only_remain_viewable_writes_denied` | S | grouped |
| `test_forged_business_selection_cannot_expand_scope` | S | grouped |
| `test_membership_grant_and_revocation_change_report_scope` | S | grouped |
| `test_membership_selector_and_no_foreign_data` | S | grouped |
| `test_period_and_business_switching_preserve_month` | S | grouped |
| `test_receivables_and_overdue_use_existing_period_end_calculations` | S | grouped |

## test_finance_pending_intents.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_direct_draft_edits_still_work_without_provider` | S | catalog |
| `test_expected_short_account_typo_resolves_only_when_unambiguous` | I | review |
| `test_expense_report_then_amount_updates_same_nonce` | S | money |
| `test_independent_direction_fragment_uses_semantics_before_amount` | I | review |
| `test_invoice_income_query_then_original_due_date` | S | money |
| `test_query_followups_preserve_period_then_draft_can_resume` | S | money |
| `test_recurring_date_can_be_interrupted_by_balance` | I | review |
| `test_screenshot_balance_phrase_does_not_invent_an_account` | S | money |
| `test_unresolved_account_can_be_interrupted_by_a_new_complete_query` | S | money |
| `test_unresolved_account_still_accepts_a_genuine_entity_answer` | S | money |

## test_finance_phase1a.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_default_category_migration_hides_unused_legacy_defaults_without_rewriting_history` | S | catalog |
| `test_defaults_idempotent_and_tenant_scoped` | S | catalog |
| `test_direction_and_inactive_references` | S | catalog |

## test_finance_phase1b.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_all_posts_csrf_enforced` | P | firstget |
| `test_accounts_categories_and_duplicate_errors` | S | money |
| `test_beta_aliases_and_own_only` | P | firstget |
| `test_beta_off_and_admin_override` | P | firstget |
| `test_dashboard_button_gate` | U | ui |
| `test_direction_mismatch_and_posted_scope_forgery` | U | ui |
| `test_get_never_initializes_or_writes` | P | firstget |
| `test_income_expense_summary_and_list` | U | ui |
| `test_invalid_money_rejected` | S | money |
| `test_mobile_forms_and_no_external_assets` | U | ui |
| `test_start_idempotent_and_actor_audited` | S | catalog |

## test_finance_phase2b.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_cron_setup_failure_sanitized_and_attention_not_execution_failure` | I | cron |
| `test_invalid_account_category_stays_due_and_can_recover` | I | scheduled |
| `test_ui_create_process_deactivate_and_anchor_not_trusted` | I | payment |
| `test_ui_get_read_only_projects_scoped_and_beta` | U | ui |

## test_finance_phase3.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_invalid_filters_and_presets` | I | longrange |
| `test_monthly_trend_boundaries_partial_month_and_zero_months` | I | longrange |
| `test_print_report_empty_states_no_writes_and_scoped_files` | U | ui |
| `test_reports_default_to_summary_and_professional_toolbar_preserves_scope` | U | ui |
| `test_transaction_csv_bom_quoting_and_numeric_history` | S | money |

## test_finance_phase4a.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_allowed_page_and_dashboard_zero_ai` | U | ui |

## test_finance_phase4b.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_allowlisted_page_and_navigation_no_ai` | U | ui |
| `test_confirm_expense` | S | money |
| `test_money_exact_and_no_float` | S | money |
| `test_payment_draft_does_not_mutate` | S | money |
| `test_payment_revalidates_outstanding_at_confirmation` | S | money |
| `test_payment_uses_existing_atomic_service_and_replay` | S | money |

## test_finance_phase4c.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_concurrent_distinct_payment_drafts_cannot_overpay` | S | money |
| `test_concurrent_payment_same_draft_independent_connections` | S | money |
| `test_payment_invoice_cross_business_on_confirmation` | S | money |

## test_finance_phase5ab.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_share_generation_readonly_valid_url` | U | ui |

## test_finance_phase5c.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_queue_markup_navigation_and_filters` | S | money |
| `test_reminder_both_tones_exact_remaining` | S | money |

## test_finance_phase6a.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_category_suggestion_active_expense_membership` | S | catalog |
| `test_explicit_checkbox_currency_and_amount_required` | S | money |
| `test_explicit_confirm_uses_reviewed_fields_and_audit` | S | money |
| `test_stale_category_rejected` | S | catalog |

## test_finance_phase6b.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_csv_debit_credit` | S | money |
| `test_csv_escaped_quotes_and_quoted_separator` | S | money |
| `test_csv_integer_money_formats` | S | money |
| `test_post_category_active_direction_tenant` | S | catalog |
| `test_review_http_correction_all_fields` | S | money |

## test_finance_semantic_agent.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_actual_all_time_spans_years_and_excludes_void` | S | money |
| `test_aggregate_read_is_explicit_and_selected_branch_stays_isolated` | S | money |
| `test_aggregate_write_asks_branch_for_settings_too` | I | scope |
| `test_ambiguous_customer_followup_choices_preserve_query` | S | money |
| `test_context_never_answers_weather_as_finance` | U | ui |
| `test_context_replaces_month_then_metric_then_alltime` | S | money |
| `test_currency_followup_replaces_old_currency` | S | money |
| `test_draft_invoice_and_recurring_do_not_inflate_actuals` | S | money |
| `test_explicit_date_range_does_not_use_upload_or_creation_date` | S | money |
| `test_fx_review_once_and_void_restore_native_balances` | S | money |
| `test_multi_item_invoice_matches_manual_totals` | S | money |
| `test_native_category_rankings_do_not_add_income_to_expense` | S | money |
| `test_new_complete_question_does_not_inherit_previous_customer_filter` | S | money |
| `test_recurring_slots_frequency_then_date_without_invention` | I | review |
| `test_recurring_unknown_cadence_is_not_silently_monthly` | I | review |
| `test_saved_transaction_reference_and_reviewed_correction` | S | money |
| `test_typoed_month_names_still_select_the_requested_report_period` | S | money |

## test_finance_semantic_brain.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_capabilities_with_pending_draft` | U | ui |
| `test_customer_new_name_phone_save_then_pronoun_invoice` | U | ui |
| `test_customer_pronoun_survives_a_confirmed_customer_linked_transaction` | I | review |
| `test_exact_options_and_dates_do_not_call_provider` | S | schema |
| `test_first_turn_short_account_typo_is_resolved_only_when_clear` | I | review |
| `test_last_transaction_correction_and_void_use_signed_reference` | S | money |
| `test_list_typo_never_reaches_heuristic_entity_parser` | U | ui |
| `test_paid_followup_on_last_draft_invoice_chains_issue_then_payment_review` | S | schema |
| `test_single_transaction_query_does_not_list_unrelated_records` | S | money |

## test_finance_unified_assistant.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_bank_text_pdf_failed_structure_retries_original_as_vision` | S | money |
| `test_csv_unknown_layout_safe_text_fallback_and_no_writes` | S | money |
| `test_makan_text_routes_and_confirms_exactly_once` | S | money |
| `test_semicolon_tab_csv_and_ambiguous_direction` | S | money |

## test_finance_ux_ai_fix.py

| Original failing method | Class | Root cause |
| --- | --- | --- |
| `test_transaction_history_is_all_time_and_paginated_ten_per_page` | U | ui |
| `test_dashboard_currency_chart_and_recent_activity` | U | ui |
| `test_dashboard_one_ai_entry_and_secondary_tools` | U | ui |
| `test_operator_fenced_response_preserves_grounding` | S | money |
| `test_period_dropdown_canonical_query_and_persistence` | U | ui |
