"""Real owner/visitor routes, separate owners and synthetic database only."""
import os
import unittest
from unittest.mock import patch
import test_kilas_playbook_routes as phase5


class OperationsRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase5.PlaybookRoutesTests.setUpClass.__func__(cls)
        global jobs, store, attention, auto
        from kilas_core import jobs, attention, automations as auto, operation_schema
        from public_chat import store
        operation_schema.apply_schema()

    tearDown=phase5.PlaybookRoutesTests.tearDown
    start=phase5.PlaybookRoutesTests.start
    send=phase5.PlaybookRoutesTests.send
    deliver=phase5.PlaybookRoutesTests.deliver

    def setUp(self):
        with jobs.transaction() as tx:
            for table in ('kw_core_automation_runs','kw_core_attention','kw_core_automation_config'):
                tx.execute('DELETE FROM '+table)
        phase5.PlaybookRoutesTests.setUp(self)
        flag=patch.dict(os.environ,{'KILAS_OPERATIONS_V2_ENABLED':'true'})
        flag.start();self.addCleanup(flag.stop)

    def test_human_request_duplicate_fences_ai_then_owner_reply_return(self):
        text='Saya mau bicara dengan manusia'
        raw=phase5.output(text,intent='HUMAN')
        result,model=self.deliver(text=text,raw=raw)
        self.assertEqual(result.status_code,200)
        self.assertEqual(model.call_count,1)
        self.assertEqual(store.conversation(7,self.cid)['mode'],'HUMAN_TAKEOVER')
        self.assertEqual(attention.listing(7)['total'],1)
        result,model=self.deliver(text=text,raw=raw)
        model.assert_not_called()
        result,model=self.deliver(event='after-human-00001')
        model.assert_not_called()
        self.assertEqual(jobs.list_jobs(7)[1],0)
        self.assertFalse(any(r['role']=='assistant' for r in store.thread(7,self.cid)))
        headers={'X-CSRF-Token':'csrf-test'}
        self.assertEqual(self.client.post(f'/business/7/web-inbox/{self.cid}/reply',json={'event_id':'owner-human-00001','message':'Tim membantu'},headers=headers).status_code,200)
        self.assertEqual(store.thread(7,self.cid)[-1]['role'],'human')
        self.assertEqual(self.client.post(f'/business/7/web-inbox/{self.cid}/mode',json={'mode':'AI_ACTIVE'},headers=headers).status_code,200)
        self.assertEqual(attention.listing(7)['total'],0)
        self.assertEqual(self.deliver(event='after-return-0001')[0].status_code,200)
        self.assertEqual(jobs.list_jobs(7)[1],1)

    def test_ready_attention_immediate_and_uncertainty(self):
        fields={'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang','volume_cbm':'0.2 m3'}
        self.assertEqual(self.deliver(fields=fields)[0].status_code,200)
        self.assertEqual(attention.listing(7)['total'],1)
        self.assertEqual(attention.listing(7)['rows'][0]['reason'],'READY_FOR_QUOTE')
        self.assertEqual(self.deliver(text='dari Shanghai',fields={'origin':'Shanghai'},event='conflict-origin-01')[0].status_code,200)
        self.assertEqual({r['reason'] for r in attention.listing(7)['rows']},{'READY_FOR_QUOTE','NEEDS_INFORMATION_STUCK'})

    def test_existing_inflight_fence_still_suppresses_actions(self):
        phase5.PlaybookRoutesTests.test_human_takeover_during_inference_and_after(self)
        self.assertEqual(attention.listing(7)['total'],0)


if __name__=='__main__': unittest.main()
