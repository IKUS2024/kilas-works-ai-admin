"""Cost attribution is internal; owner usage exposes business counters only."""
import os
import unittest
from unittest.mock import patch
import test_client_hub_v1 as fixture
import ai_usage
import assist_costs
import subscription_service

repo,db=fixture.repo,fixture.db

class CostTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        self.owner=repo.create_user('cost@test.invalid','hash')
        self.bid=repo.create_business(self.owner,'One','AI_ADMIN')
        self.other=repo.create_business(self.owner,'Two','AI_ADMIN_PRO')
        subscription_service.create_subscription(self.bid,'ai_admin')
        subscription_service.create_subscription(self.other,'ai_admin_pro')

    def test_provider_feature_scope_and_customer_projection(self):
        response={'content':[{'text':'Hi'}],'usage':{'input_tokens':100,'output_tokens':30}}
        with patch.dict(os.environ,{'AI_COST_USD_IDR':'16000'}):
            self.assertTrue(ai_usage.record('gpt-4.1-mini',response,tenant_id=self.bid,context='assist_demo',provider='openai'))
            self.assertTrue(ai_usage.record('claude-haiku-4-5-20251001',response,tenant_id=self.other,context='follow_up'))
        rows=db.query_all('SELECT tenant_id,context_type,provider FROM ai_usage_ledger ORDER BY id')
        self.assertEqual(rows,[{'tenant_id':self.bid,'context_type':'assist_demo','provider':'openai'},
                              {'tenant_id':self.other,'context_type':'follow_up','provider':'anthropic'}])
        owner=ai_usage.client_summary(self.bid)
        self.assertEqual(owner,{'replies':1,'media':0,'followups':0,'status':'NORMAL'})
        self.assertEqual(ai_usage.client_summary(self.other)['followups'],1)
        report=assist_costs.platform_report()
        self.assertEqual(len(report['businesses']),2)
        self.assertTrue(all(row['cost']>0 for row in report['businesses']))
        self.assertTrue(all(row['guardrail']=='NO_REVENUE' for row in report['businesses']))

    def test_unknown_cost_is_not_presented_as_zero_and_high_usage_does_not_block(self):
        response={'content':[{'text':'Hi'}],'usage':{'input_tokens':100,'output_tokens':30}}
        with patch.dict(os.environ,{'KILAS_AI_STARTER_CAPACITY':'1'}):
            self.assertTrue(ai_usage.record('unpriced',response,tenant_id=self.bid,context='tenant_customer'))
            self.assertEqual(ai_usage.client_summary(self.bid)['status'],'HIGH')
            self.assertTrue(ai_usage.record('unpriced',response,tenant_id=self.bid,context='tenant_customer'))
        report=assist_costs.platform_report()['businesses'][0]
        self.assertEqual(report['guardrail'],'UNKNOWN')
        self.assertIsNone(report['cost']);self.assertIsNone(report['ratio'])

if __name__=='__main__':unittest.main()
