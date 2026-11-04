"""Execute retained import accounting invariants without reviving archived AI routes.

Methods are reused from the legacy suite so its original service assertions run.
Only the obsolete provider/login setup is replaced. HTTP/provider extraction
scenarios remain archived and are not represented as passing by this suite.
"""
import unittest
from finance_manual_test_support import set_up_manual_finance
from test_finance_phase6b import BankTests


class BankManualAuditTests(unittest.TestCase):
    def setUp(self):
        set_up_manual_finance(self)
        self.base=self.url+'/bank-imports'
        self.row=dict(transaction_date='2026-09-17',description='Bank purchase',direction='EXPENSE',amount_minor=10000000,reference='R-1')
        self.csv=b'date,description,debit,credit,reference\n2026-09-17,Bank purchase,100000,0,R-1\n'
        self.serial=0

    def test_archived_import_routes_remain_unavailable_without_writes(self):
        before=self.snapshot()
        for suffix in ('','/new','/analyze'):
            self.assertEqual(self.client.get(self.base+suffix).status_code,404 if suffix!='/analyze' else 405)
        self.assertEqual(self.client.post(self.base+'/analyze').status_code,404)
        self.assertEqual(before,self.snapshot())
        self.http.assert_not_called()


for name in ('create','rows','imp','ledger','fields','post','tx','snapshot','race','assert_upload_bad'):
    setattr(BankManualAuditTests,name,getattr(BankTests,name))

SERVICE_CASES = (
    'review_correction_and_invalid_correction', 'review_account_cannot_change_and_stale_revision',
    'identical_rows_distinct_and_overlap_flag', 'candidate_account_direction_amount_requirements',
    'candidate_dates_order_limit_and_explanation', 'no_auto_match_and_bounded_query',
    'explicit_match_no_money', 'match_target_revalidated_void_wrong_fields',
    'one_transaction_cannot_link_two_rows', 'cross_tenant_candidate_rejected',
    'expense_post_row_authority_and_origin', 'income_post', 'post_category_active_direction_tenant',
    'post_account_deactivated', 'post_cannot_override_row_money_or_account', 'post_reviewable_fields',
    'repeated_post_and_conflict', 'concurrent_same_post', 'concurrent_match_vs_post',
    'atomic_rollback_on_reconciliation_audit', 'atomic_rollback_on_row_write',
    'void_keeps_link_and_cannot_recreate', 'managed_origin_spoofing_immutable',
    'prior_managed_origins_preserved', 'ignore_idempotent_no_money', 'decided_rows_cannot_switch_action',
    'cancel_and_decision_history', 'safe_audit_ids_only', 'sqlite_migration_idempotency_constraints',
    'row_link_constraint_cross_tenant', 'no_ai_in_confirmation', 'concurrent_import_dedup',
    'review_after_open_and_wrong_row_import', 'posted_transaction_excluded_from_matching',
    'service_requires_authenticated_actor', 'database_unique_link_across_post_and_match',
    'concurrent_two_rows_match_same_transaction', 'concurrent_open_vs_review',
    'completion_audit_failure_rolls_back_ledger_and_decision', 'matched_ledger_later_changed_needs_attention',
    'exact_post_replay_after_account_category_archived',
)
for name in SERVICE_CASES:
    setattr(BankManualAuditTests,'test_'+name,getattr(BankTests,'test_'+name))
