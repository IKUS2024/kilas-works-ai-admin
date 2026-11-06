"""Provider count/generation contract, offline only; no receipt data is transmitted."""
import io
import json
import unittest
from unittest.mock import MagicMock,patch
from PIL import Image
import requests
from kilas_ai import credit_receipts as receipts, credit_policy, providers


class ReceiptTransportTests(unittest.TestCase):
    def setUp(self):
        output=io.BytesIO();Image.new('RGB',(16,16),'white').save(output,'PNG')
        self.serialized=receipts.payload(output.getvalue(),'image/png',[],'Synthetic instruction',{'json_schema':{'name':'test','strict':True,'schema':{'type':'object','properties':{},'additionalProperties':False}}})
        self.auth=patch.object(receipts,'headers',return_value={'Authorization':'synthetic'});self.auth.start();self.addCleanup(self.auth.stop)

    def response(self,value,status=200):
        result=MagicMock();result.__enter__.return_value=result;result.content=json.dumps(value).encode();result.status_code=status;result.json.return_value=value
        return result

    def test_exact_counted_payload_generation_no_history_tools_truncation_or_retry(self):
        count=self.response({'object':'response.input_tokens','input_tokens':32000})
        output=self.response({'status':'completed','usage':{'input_tokens':32000,'output_tokens':2048},'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{}'}]}]})
        with patch.object(requests,'post',side_effect=[count,output]) as post:
            verified=receipts.preflight(self.serialized)
            events=list(receipts.generate(self.serialized,verified))
        counted=post.call_args_list[0].kwargs['json'];generated=post.call_args_list[1].kwargs['json']
        self.assertEqual(counted,{k:v for k,v in generated.items() if k not in ('max_output_tokens','store','stream')})
        self.assertEqual(post.call_args_list[0].args[0],'https://api.openai.com/v1/responses/input_tokens')
        self.assertEqual(generated['max_output_tokens'],2048)
        self.assertFalse(generated['store']);self.assertNotIn('tools',generated)
        self.assertEqual(events[-1],{'type':'finish','reason':'stop'})

    def test_counter_failure_malformed_or_over_bound_never_generates(self):
        for result in ({'object':'response.input_tokens','input_tokens':32001},{'input_tokens':1},{'object':'response.input_tokens','input_tokens':True}):
            with patch.object(requests,'post',return_value=self.response(result)) as post:
                with self.assertRaises(providers.ProviderQuotaError):receipts.preflight(self.serialized)
                post.assert_called_once()
        with patch.object(requests,'post',side_effect=requests.Timeout) as post:
            with self.assertRaises(providers.ProviderQuotaError):receipts.preflight(self.serialized)
            post.assert_called_once()

    def test_changed_payload_denies_and_refused_incomplete_meter_breach_preserve_supplier_usage(self):
        verified={'payload_digest':credit_policy.fingerprint(json.loads(self.serialized)),'count':100}
        with patch.object(requests,'post') as post:
            with self.assertRaises(providers.ProviderQuotaError):list(receipts.generate(self.serialized+' ',{**verified,'payload_digest':'bad'}))
            post.assert_not_called()
        for value in (
            {'status':'completed','usage':{'input_tokens':100,'output_tokens':10},'output':[{'type':'message','role':'assistant','content':[{'type':'refusal'}]}]},
            {'status':'incomplete','usage':{'input_tokens':100,'output_tokens':2048}},
            {'status':'completed','usage':{'input_tokens':32001,'output_tokens':10}},
        ):
            with patch.object(requests,'post',return_value=self.response(value)) as post:events=list(receipts.generate(self.serialized,verified))
            self.assertEqual(events[0]['type'],'usage')
            self.assertNotEqual(events[-1],{'type':'finish','reason':'stop'})
            post.assert_called_once()


if __name__=='__main__':unittest.main()
