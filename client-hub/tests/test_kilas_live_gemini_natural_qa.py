"""Natural-rate QA arming and limits, never real provider IO."""
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from types import SimpleNamespace
from kilas_ai import live_gemini_natural_qa as qa, live_gemini_budget as budget, live_gemini_smoke as smoke
from kilas_ai import live_gemini as native, live_gemini_pair as pair


class NaturalTests(unittest.TestCase):
    def test_early_failure_records_safe_cause_and_waits_for_durable_cleanup(self):
        error=native.invalid_response('output_language')
        def rejected(*args):raise error
        relay=SimpleNamespace(finished=False,accept=rejected,error=error,streams={},diagnostics=lambda:{'first_error_code':error.code})
        relay.stop=lambda reason:setattr(relay,'finished',True)
        with patch.object(pair,'start',return_value=relay),redirect_stdout(io.StringIO()):
            result=qa.paired({'owner':9},{'id':bytes(32000)},[],'a'*48,'id',0)
        self.assertEqual(result['code'],'gemini_response_invalid')
        self.assertEqual(result['relay_code'],'gemini_response_invalid')
        self.assertTrue(result['settled_after_cleanup'])

    def test_default_off_and_expiry_bound(self):
        with patch.dict(os.environ,{},clear=True),patch.object(qa.subprocess,'Popen') as child:
            self.assertFalse(qa.launch());qa.run();child.assert_not_called()
        values={qa.ARM:qa.RUN,qa.EXPIRY:(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),
                'RENDER_SERVICE_ID':smoke.SERVICE,'KILAS_LIVE_GEMINI_QA_OWNER_ID':'9',
                'KILAS_LIVE_GEMINI_QA_OWNER_EMAIL':'synthetic@example.test'}
        with patch.dict(os.environ,values,clear=True):
            self.assertIsNotNone(qa.config())
            with patch.dict(os.environ,{qa.EXPIRY:(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}):self.assertIsNone(qa.config())
            with patch.dict(os.environ,{'RENDER_SERVICE_ID':'other'}):self.assertIsNone(qa.config())
        for language in ('id','en'):self.assertEqual(len(smoke.fixture(language)),480000)

    def test_insufficient_normal_allowance_never_claims_or_connects(self):
        with patch.object(qa,'config',return_value={'owner':9}),patch.object(budget,'status',return_value={'available':False}), \
             patch.object(smoke,'once') as once,redirect_stdout(io.StringIO()):
            qa.run();once.assert_not_called()

    def test_caption_acceptance_does_not_imply_terminal_billing_evidence(self):
        value={'setup_complete':True,'code':None,'input_ms':15000,'output_ms':18000,
               'source_tail_word_confirmed':True,'target_tail_word_confirmed':True,
               'all_accepted_pcm_read':True,'post_end_output_access':'blocked','tail_confirmed':False}
        self.assertTrue(qa.full_enough(value))
        self.assertFalse(qa.full_enough({**value,'target_tail_word_confirmed':False}))


if __name__=='__main__':unittest.main()
