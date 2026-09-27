"""Cost routing and safe output without live provider requests."""
import os
import unittest
from unittest.mock import Mock, patch
import test_client_hub_v1 as fixture
import ai_router
import assist_reply


class RouterTests(unittest.TestCase):
    def test_cheap_openai_path_records_returned_usage_once_and_no_escalation(self):
        response=Mock();response.json.return_value={'choices':[{'message':{'content':'Baik'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':40}}}
        claude=Mock()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only','KILAS_AI_FAST_PROVIDER':'openai','KILAS_AI_FAST_MODEL':'configured-small'}), \
                patch.object(ai_router.requests,'post',return_value=response) as post, \
                patch.object(ai_router.ai_usage,'record') as record:
            self.assertEqual(ai_router.complete('instructions',[{'role':'user','content':'halo'}],claude=claude),('Baik','end_turn',None))
            self.assertEqual(post.call_args.kwargs['json']['model'],'configured-small')
            self.assertFalse(post.call_args.kwargs['json']['store'])
            self.assertEqual(record.call_args.args[1]['usage']['input_tokens'],60)
            self.assertEqual(record.call_args.args[1]['usage']['cache_read_input_tokens'],40)
            claude.assert_not_called()

    def test_failed_cheap_call_escalates_once_with_sanitized_error(self):
        claude=Mock(return_value=('Bisa saya bantu.','end_turn',None))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only','KILAS_AI_FAST_PROVIDER':'openai','KILAS_AI_STRONG_PROVIDER':'anthropic','KILAS_AI_STRONG_MODEL':'configured-strong'}), \
                patch.object(ai_router.requests,'post',side_effect=ai_router.requests.Timeout('must-not-leak-key')):
            result=ai_router.complete('instructions',[],claude=claude)
            self.assertEqual(result[0],'Bisa saya bantu.')
            claude.assert_called_once()
            self.assertEqual(claude.call_args.kwargs['model'],'configured-strong')
            self.assertNotIn('must-not-leak',str(ai_router._openai('instructions',[],100,'small')))

    def test_structured_explanation_drops_hidden_fields_and_ungrounded_action(self):
        import json
        result={'reply':'Boleh ceritakan kebutuhan Anda?','intent':'QUESTION','confidence':.92,
            'knowledge_used':['profile','invented'], 'evidence':'invented evidence',
            'reasoning':'private reasoning must never be stored',
            'insight':{'summary':'Tanya harga','action':'Kirim invoice','job_status':'DIKERJAKAN'}}
        with patch.object(assist_reply,'relevant_knowledge',return_value={'profile':'Bisnis Foto'}), \
                patch.object(ai_router,'complete',return_value=(json.dumps(result),'end_turn',None)) as call:
            reply,insight,trace=assist_reply.generate(1,'Berapa harga?',[])
            call.assert_called_once()
            self.assertIsNone(insight['action']);self.assertIsNone(insight['job_status'])
            self.assertEqual(trace['confidence'],92)
            self.assertNotIn('private reasoning',str(trace))
            self.assertNotIn('invented',str(trace))


if __name__=='__main__':unittest.main()
