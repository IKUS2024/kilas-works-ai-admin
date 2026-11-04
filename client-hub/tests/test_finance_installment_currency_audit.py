"""A scheduled installment must retain its purchase currency on account edits."""
import unittest
import test_finance_purchase_plans as fixture
import finance_service as f
import finance_branches as branches
import db


class InstallmentCurrencyTests(unittest.TestCase):
    setUp=fixture.PurchasePlanTests.setUp
    create=fixture.PurchasePlanTests.create
    categories=fixture.PurchasePlanTests.categories
    splits=fixture.PurchasePlanTests.splits
    items=fixture.PurchasePlanTests.items

    def seed(self):
        ident=self.create(amount_minor=10000,splits=None,duration='2',unit='MONTHS')
        item=self.items(ident)[0]
        rule=f.get_recurring_expense(self.b,item['recurring_id'],self.uid)
        usd=f.create_account(self.b,'Dollar','BANK',currency='USD',actor_user_id=self.uid)
        params=dict(name=rule['name'],amount_minor=rule['amount_minor'],account_id=usd,
            category_id=rule['category_id'],cadence=rule['cadence'],next_due_on=rule['next_due_on'],
            end_on=rule['end_on'],actor_user_id=self.uid,expected_currency='USD')
        return ident,rule,usd,params

    def test_cross_currency_edit_rejected_without_mutating_plan_or_rule(self):
        with branches.scope(self.b,self.branch,self.uid):
            ident,rule,usd,params=self.seed()
            before=list(db.get_connection().iterdump())
            with self.assertRaisesRegex(f.FinanceError,'installment_payment_locked'):
                f.update_recurring_expense(self.b,rule['id'],**params)
            self.assertEqual(list(db.get_connection().iterdump()),before)

    def test_http_cross_currency_rejected_same_currency_reassignment_still_pays_idr(self):
        with branches.scope(self.b,self.branch,self.uid):
            ident,rule,usd,params=self.seed()
            category=next(c for c in f.list_categories(self.b,'EXPENSE',include_children=True,actor_user_id=self.uid) if c['id']==rule['category_id'])
        form=dict(branch_id=self.branch,name=rule['name'],amount='50',account_id=usd,
            category_id=category.get('parent_category_id') or category['id'],
            subcategory_id=category['id'] if category.get('parent_category_id') else '',
            cadence='ONCE',next_due_on=rule['next_due_on'],end_on=rule['end_on'])
        response=self.client.post(self.url+f'/recurring/{rule["id"]}/edit',data=form)
        self.assertEqual(response.status_code,303)
        with branches.scope(self.b,self.branch,self.uid):
            self.assertEqual(f.get_recurring_expense(self.b,rule['id'],self.uid),rule)
        form['account_id']=self.dest
        self.assertEqual(self.client.post(self.url+f'/recurring/{rule["id"]}/edit',data=form).status_code,303)
        with branches.scope(self.b,self.branch,self.uid):
            self.assertEqual(f.get_recurring_expense(self.b,rule['id'],self.uid)['account_id'],self.dest)
            payment=f.record_recurring_payment(self.b,rule['id'],rule['next_due_on'],rule['next_due_on'],actor_user_id=self.uid,account_id=self.dest)
            tx=f.get_transaction(self.b,payment['ledger_transaction_id'],actor_user_id=self.uid)
            self.assertEqual((tx['currency'],tx['amount_minor'],tx['account_id']),('IDR',5000,self.dest))
            self.assertEqual(db.query_one('SELECT currency FROM finance_installment_plans WHERE id=?',(ident,))['currency'],'IDR')
