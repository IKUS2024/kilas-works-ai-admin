"""Alternate takes use stored inputs and normal accounting; all provider IO mocked."""
import unittest
from unittest.mock import patch
import test_kilas_audio as base
from test_kilas_audio import f, provider, store, service


class AlternateTests(unittest.TestCase):
    setUpClass=classmethod(base.AudioTests.setUpClass.__func__)
    setUp=base.AudioTests.setUp
    credit=base.AudioTests.credit
    create=base.AudioTests.create

    def source(self, **kw):
        self.credit(300)
        response,_,_=self.create(**kw)
        self.assertEqual(response.status_code,201,response.text)
        return response.json['id']

    def alternate(self, ident, key='alternate-operation-123456', **extra):
        with patch.object(provider,'speech',return_value=(self.audio,'alternate-request')) as speech:
            r=self.client.post(f'/kilas-translator/jobs/{ident}/alternate',data={'operation_key':key,'csrf_token':'audio-csrf',**extra})
        return r,speech

    def test_exact_translated_snapshot_separate_output_and_billing(self):
        ident=self.source(script='  Naskah asli.\n',translate_script='yes',translated_script='Exact translated speech.',language='en',translation_source='id')
        before=store.balance(self.user)['seconds']
        r,speech=self.alternate(ident,script='stale edited draft',language='fr',voice='injected')
        self.assertEqual(r.status_code,201,r.text);new=r.json['id'];self.assertNotEqual(new,ident)
        speech.assert_called_once_with('Exact translated speech.','actualVoice123','en',alternate_stability=0.35)
        row=f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(new,))
        self.assertEqual(row['original_script'],'  Naskah asli.\n');self.assertEqual(row['spoken_script'],'Exact translated speech.')
        self.assertEqual(row['alternate_of'],ident);self.assertEqual(row['status'],'COMPLETED')
        self.assertLess(store.balance(self.user)['seconds'],before)
        for job in (ident,new):self.assertEqual(self.client.get(f'/kilas-translator/jobs/{job}/result?download=1').data,self.audio)
        self.assertIn('Buka versi sebelumnya',self.client.get(r.json['url']).text)
        again,tts=self.alternate(new,key='alternate-operation-654321')
        self.assertEqual(again.status_code,201);self.assertEqual(tts.call_args.kwargs['alternate_stability'],0.65)

    def test_duplicate_key_and_cross_source_conflict(self):
        ident=self.source();r,_=self.alternate(ident);balance=store.balance(self.user)
        again,speech=self.alternate(ident)
        self.assertEqual(again.json['id'],r.json['id']);speech.assert_not_called();self.assertEqual(balance,store.balance(self.user))
        conflict,tts=self.alternate(r.json['id']);self.assertEqual(conflict.status_code,409);tts.assert_not_called()

    def test_foreign_owner_csrf_and_legacy_rejected(self):
        ident=self.source()
        denied=self.client.post(f'/kilas-translator/jobs/{ident}/alternate',data={'operation_key':'alternate-operation-123456'})
        self.assertEqual(denied.status_code,400)
        f.db.execute('UPDATE kilas_audio_jobs SET user_id=? WHERE id=?',(self.other,ident))
        r,tts=self.alternate(ident);self.assertEqual(r.status_code,404);tts.assert_not_called()
        f.db.execute('UPDATE kilas_audio_jobs SET user_id=?,spoken_script=NULL WHERE id=?',(self.user,ident))
        r,tts=self.alternate(ident);self.assertEqual(r.status_code,409);tts.assert_not_called()
        self.assertNotIn('data-audio-alternate',self.client.get(f'/kilas-translator/jobs/{ident}').text)

    def test_failed_take_not_retried_by_same_key_or_poll(self):
        ident=self.source()
        with patch.object(provider,'speech',side_effect=provider.ProviderError('provider_transport')) as tts:
            r=self.client.post(f'/kilas-translator/jobs/{ident}/alternate',data={'operation_key':'alternate-operation-123456','csrf_token':'audio-csrf'})
            self.assertEqual(r.status_code,201);new=r.json['id'];self.assertEqual(store.get(self.user,new)['status'],'FAILED')
            self.client.get(f'/kilas-translator/jobs/{new}/status');self.alternate(ident)
            self.assertEqual(tts.call_count,1)
        self.assertEqual(store.get(self.user,ident)['status'],'COMPLETED')

    def test_zero_balance_no_provider_and_removed_voice(self):
        ident=self.source();f.db.execute('UPDATE kilas_audio_balances SET seconds=0 WHERE user_id=?',(self.user,))
        r,tts=self.alternate(ident);self.assertEqual(r.status_code,402);tts.assert_not_called()
        f.db.execute('UPDATE kilas_audio_balances SET seconds=300 WHERE user_id=?',(self.user,));f.db.execute('UPDATE kilas_audio_jobs SET voice_is_personal=1 WHERE id=?',(ident,))
        r,tts=self.alternate(ident);self.assertEqual(r.status_code,409);tts.assert_not_called()

    def test_provider_uses_v4_supported_settings_exact_text(self):
        with patch.object(provider,'request',return_value=(b'fake','id')) as call:
            provider.speech('Exact words.','sameVoice','id',alternate_stability=0.35)
        self.assertEqual(call.call_args.kwargs['json'],{'text':'Exact words.','model_id':'eleven_v4','language_code':'id','voice_settings':{'stability':0.35,'similarity_boost':0.75}})

    def test_concurrent_same_operation_dispatches_once(self):
        from concurrent.futures import ThreadPoolExecutor
        ident=self.source();cookie=self.client.get_cookie('session')
        def send(_):
            client=f.app.app.test_client();client.set_cookie(cookie.key,cookie.value)
            return client.post(f'/kilas-translator/jobs/{ident}/alternate',data={'operation_key':'concurrent-alternate-123456','csrf_token':'audio-csrf'})
        with patch.object(provider,'speech',return_value=(self.audio,'concurrent')) as speech,ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(send,range(2)))
        self.assertEqual(sorted(r.status_code for r in responses),[200,201])
        self.assertEqual(responses[0].json['id'],responses[1].json['id']);self.assertEqual(speech.call_count,1)
