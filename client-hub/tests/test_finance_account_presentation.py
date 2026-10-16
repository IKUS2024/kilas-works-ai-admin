"""Read-only grouped balances, native-currency fallbacks and explicit credit semantics."""
import re,unittest
from unittest.mock import patch
import test_finance_edit_package as prior
import finance_account_presentation as presentation
import finance_service as f,finance_branches as branches
import db


class AccountPresentationTests(unittest.TestCase):
    setUp=prior.FinanceEditPackageTests.setUp
    page=prior.FinanceEditPackageTests.page

    def seed(self,branch):
        with branches.scope(self.b,branch,self.uid):
            debit=f.create_account(self.b,'Synthetic debit one','BANK','IDR',10000,account_type_label='Debit',actor_user_id=self.uid)
            second=f.create_account(self.b,'Synthetic debit two','BANK','IDR',25000,account_type_label='Debit',actor_user_id=self.uid)
            usd=f.create_account(self.b,'Synthetic dollar debit','BANK','USD',1000,account_type_label='Debit',actor_user_id=self.uid)
            credit=f.create_account(self.b,'Synthetic credit','OTHER','IDR',-5000,account_type_label='Credit',actor_user_id=self.uid)
        return debit,second,usd,credit

    def test_collapsed_groups_show_current_totals_keep_details_and_signed_credit(self):
        for branch in (self.branch,self.personal):
            debit,second,usd,credit=self.seed(branch)
            before=db.query_all('SELECT * FROM finance_accounts')
            html,ctx=self.page(branch,view='accounts')
            group=ctx['account_group_summaries']['Debit']
            # The Business fixture also contains one existing Debit reserve account.
            expected=sum(r['balance_minor'] for r in ctx['account_balance_rows'] if r['account_type_label']=='Debit' and r['currency']=='IDR')+15000000
            self.assertEqual(group['total_minor'],expected)
            self.assertEqual(ctx['account_group_summaries']['Credit']['total_minor'],-5000)
            self.assertIn('Utang / kewajiban',html);self.assertIn('bukan saldo tersedia',html)
            self.assertNotIn('Saldo tersedia sekarang',html)
            self.assertIn('finance-account-overall-total',html)
            sections=re.findall(r'<details class="finance-account-hb-group">.*?</details>',html,re.S)
            self.assertTrue(sections)
            for section in sections:
                head=section.split('</summary>')[0]
                self.assertIn('finance-account-group-total',head)
                self.assertNotIn('<details class="finance-account-hb-group" open',section)
            self.assertIn('Synthetic debit one',html)
            self.assertEqual(before,db.query_all('SELECT * FROM finance_accounts'))
            detail,_=self.page(branch,view='accounts',account_id=credit)
            self.assertIn('Saldo kredit / kewajiban',detail)

    def test_missing_fx_keeps_separate_native_amounts_instead_of_numeric_sum(self):
        self.seed(self.branch)
        with patch('finance_fx.snapshot',return_value=dict(rates={'IDR':'1'},source='unavailable',date=None,stale=True)):
            html,ctx=self.page(view='accounts')
        group=ctx['account_group_summaries']['Debit']
        self.assertIsNone(group['total_minor'])
        self.assertEqual({r['currency'] for r in group['native_totals']},{'IDR','USD'})
        self.assertIn('Rp',group['display_total']);self.assertIn('US$',group['display_total'])
        self.assertIn('Kurs belum lengkap',ctx['balance_total_display'])

    def test_groups_exclude_inactive_and_other_personal_business_accounts(self):
        debit,second,usd,credit=self.seed(self.personal)
        f.update_account_opening_balance(self.b,self.dest,0,actor_user_id=self.uid)
        branches.update_record(self.b,'account',self.dest,deactivate=True,actor_user_id=self.uid)
        html,ctx=self.page(self.personal,view='accounts')
        ids={r['id'] for r in ctx['account_balance_rows']}
        self.assertNotIn(self.dest,ids);self.assertNotIn(self.a,ids)
        self.assertTrue({debit,second,usd,credit}.issubset(ids))
        self.assertEqual(ctx['account_group_summaries']['Debit']['total_minor'],15035000)

    def test_credit_label_does_not_classify_other_categories_as_liabilities(self):
        self.assertTrue(presentation.is_credit('Credit'));self.assertTrue(presentation.is_credit('Kredit'))
        for label in ('Piutang','Debit','Tabungan','Other',None):self.assertFalse(presentation.is_credit(label))
