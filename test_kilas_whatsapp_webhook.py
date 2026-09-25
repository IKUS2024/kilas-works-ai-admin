"""Exercise the real signed root ingress and batching without live business/network calls."""
import os
import json
import hmac
import hashlib
import unittest
from unittest.mock import patch
os.environ.pop('DATABASE_URL',None)
os.environ.setdefault('WHATSAPP_PHONE_NUMBER_ID','123')
os.environ.setdefault('WHATSAPP_ACCESS_TOKEN','synthetic-platform')
os.environ.setdefault('ANTHROPIC_API_KEY','synthetic')
import _test_bootstrap
import app as bot
from kilas_core import whatsapp_access
from kilas_core.adapters import whatsapp


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.client=bot.app.test_client()
        self.flags=patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'synthetic-signing'})
        self.flags.start();self.addCleanup(self.flags.stop)

    def post(self,data,valid=True):
        body=json.dumps(data).encode()
        signature='sha256='+hmac.new(b'synthetic-signing',body,hashlib.sha256).hexdigest()
        return self.client.post('/webhook',data=body,content_type='application/json',headers={'X-Hub-Signature-256':signature if valid else 'bad'})

    def data(self):
        return {'entry':[{'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'77777'},'messages':[{'id':'a'},{'id':'b'}]}}, {'field':'messages','value':{'metadata':{'phone_number_id':'88888'},'statuses':[{'id':'out','status':'read'}]}}]}]}

    def test_signature_invalid_and_valid_batched_channel_dispatch(self):
        with patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_resolve_tenant_or_unknown',side_effect=lambda pid:(7 if pid=='77777' else 8,False)),patch.object(whatsapp_access,'selected',return_value={'selected':True}),patch.object(whatsapp,'handle',return_value={'status':'ok'}) as handle,patch.object(bot,'call_claude') as legacy:
            self.assertEqual(self.post(self.data(),False).status_code,403);handle.assert_not_called()
            self.assertEqual(self.post(self.data()).status_code,200)
            self.assertEqual([r.args[:2] for r in handle.call_args_list],[(7,'77777'),(7,'77777'),(8,'88888')])
            legacy.assert_not_called()
            self.assertEqual(bot._active_whatsapp_phone_number_id(),bot.WHATSAPP_PHONE_NUMBER_ID)

    def test_unknown_and_adapter_failure_never_fall_back(self):
        with patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_resolve_tenant_or_unknown',return_value=(None,True)),patch.object(whatsapp,'handle') as handle:
            self.assertEqual(self.post(self.data()).status_code,200);handle.assert_not_called()
        with patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_resolve_tenant_or_unknown',return_value=(7,False)),patch.object(whatsapp_access,'selected',return_value={'selected':True}),patch.object(whatsapp,'handle',side_effect=RuntimeError('SECRET')),patch.object(bot,'call_claude') as legacy:
            response=self.post(self.data());self.assertEqual(response.status_code,503);self.assertNotIn(b'SECRET',response.data);legacy.assert_not_called()


if __name__=='__main__': unittest.main()
