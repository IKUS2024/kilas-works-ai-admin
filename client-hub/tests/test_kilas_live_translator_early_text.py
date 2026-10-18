"""Complete text publication before unchanged fresh TTS gates; synthetic providers only."""
import unittest
from threading import Event,Thread
from unittest.mock import patch
import test_kilas_live_translator_whole as fixture
from kilas_ai import live_translator as live,live_translator_store as sessions,live_translator_output as output,live_translator_segments as segments,audio_transcription_budget as budget,audio_store

class EarlyTextTests(unittest.TestCase):
 setUp=fixture.WholeTests.setUp
 setUpClass=fixture.WholeTests.__dict__['setUpClass']
 funded=fixture.WholeTests.funded
 on=fixture.WholeTests.on
 credit=fixture.WholeTests.credit
 session=fixture.WholeTests.session
 key=fixture.WholeTests.key
 context=fixture.WholeTests.context
 path=fixture.WholeTests.path
 def test_full_text_before_fresh_credit_gate_failure_never_creates_audio_or_retries(self):
  entered,release=Event(),Event();errors=[]
  def fresh_credit():entered.set();release.wait(3);raise budget.BudgetError('provider_credit_exhausted',402)
  with self.context('Do not buy 12 tickets for Rina.'):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
   def worker():
    try:live.process(self.user,ident,key,None,info,committed_text='Jangan beli 12 tiket untuk Rina.',whole_output=True)
    except Exception as error:errors.append(error)
   with patch.object(live.stt,'require_subscription_credit',side_effect=fresh_credit) as credit,patch.object(segments.transport,'request') as speech:
    thread=Thread(target=worker);thread.start()
    try:
     self.assertTrue(entered.wait(2));progress=self.client.get(self.path(ident,key)).json
     self.assertEqual(progress['status'],'PROCESSING');self.assertTrue(progress['translation_ready']);self.assertEqual(progress['source_text'],'Jangan beli 12 tiket untuk Rina.');self.assertEqual(progress['translated_text'],'Do not buy 12 tickets for Rina.');self.assertNotIn('audio_url',progress)
     self.assertEqual(self.client.get(self.path(ident,key)+'/audio').status_code,404);self.assertIsNone(output.get(self.user,ident,key)['job']);speech.assert_not_called()
    finally:release.set();thread.join(3)
    self.assertFalse(thread.is_alive());credit.assert_called_once();speech.assert_not_called()
   self.assertEqual(errors[0].code,'provider_credit_exhausted');failed=self.client.get(self.path(ident,key)).json;self.assertEqual(failed['status'],'FAILED');self.assertNotIn('audio_url',failed)
 def test_complete_text_publication_is_owner_scoped_and_does_not_revive_discarded_output(self):
  result=dict(text='Complete translation.',source_text='Ucapan lengkap.',source_language='id',target_language='en')
  with self.context(result['text']):
   self.credit(300);ident=self.session();key=self.key();sessions.claim(self.user,ident,key);output.activate(self.user,ident,key)
   with self.assertRaises(audio_store.AudioError):output.publish_translation(self.user+100,ident,key,result)
   self.assertFalse(output.get(self.user,ident,key)['translation_ready']);output.publish_translation(self.user,ident,key,result)
   with self.assertRaises(audio_store.AudioError):output.publish_translation(self.user,ident,key,{**result,'text':'Changed'})
   self.assertEqual(output.get(self.user,ident,key)['text'],result['text']);output.discard(self.user,ident,key)
   with self.assertRaises(audio_store.AudioError):output.publish_translation(self.user,ident,key,result)
   self.assertIsNone(output.get(self.user,ident,key))

if __name__=='__main__':unittest.main()
