"""Progressive relay ownership/offset/tail/cancellation with synthetic providers."""
import hashlib,unittest
from threading import Event,Thread
from unittest.mock import patch
import test_kilas_live_translator_whole as fixture
import test_kilas_audio as audio
from auth_test_helpers import authenticate
from kilas_ai import live_translator as live,live_translator_store as sessions,live_translator_output as output,live_translator_segments as segments,audio_store

class ProgressiveTests(unittest.TestCase):
 setUp=fixture.WholeTests.setUp
 setUpClass=fixture.WholeTests.__dict__['setUpClass']
 funded=fixture.WholeTests.funded
 on=fixture.WholeTests.on
 credit=fixture.WholeTests.credit
 session=fixture.WholeTests.session
 key=fixture.WholeTests.key
 context=fixture.WholeTests.context
 path=fixture.WholeTests.path
 response=fixture.WholeTests.response
 def test_reserved_prefix_repeat_offsets_final_hash_and_owner_guards(self):
  entered,release=Event(),Event();errors=[]
  def chunks():yield self.raw[:2000];entered.set();release.wait(3);yield self.raw[2000:]
  with self.context('A complete translation.'),patch.object(segments.transport,'request',return_value=self.response(chunks)) as request:
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
   def worker():
    try:live.process(self.user,ident,key,None,info,committed_text='Ucapan lengkap.',whole_output=True)
    except Exception as e:errors.append(e)
   thread=Thread(target=worker);thread.start()
   try:
    self.assertTrue(entered.wait(2));state=self.client.get(self.path(ident,key)).json;self.assertEqual(state['status'],'PROCESSING');url=state['audio_progress_url'];r=self.client.get(url+'?offset=0');self.assertEqual(r.status_code,200);self.assertEqual(r.data,self.raw[:2000]);self.assertEqual(r.headers['X-Audio-Complete'],'0');self.assertEqual(self.client.get(url+'?offset=0').data,r.data);self.assertEqual(self.client.get(url+'?offset=2000').status_code,204);self.assertEqual(self.client.get(url+'?offset=2001').status_code,410);self.assertEqual(self.client.get(url+'?offset=-1').status_code,400)
    foreign=self.client.application.test_client()
    authenticate(foreign,audio.f.repo.get_user_by_id(self.other),_csrf_token='audio-csrf')
    self.assertIn(foreign.get(url+'?offset=0').status_code,(303,404))
    self.assertEqual(self.client.get(url.replace(key,'live-'+'f'*32)+'?offset=0').status_code,404)
   finally:release.set();thread.join(4)
   self.assertFalse(errors,errors);self.assertEqual(request.call_count,1);state=self.client.get(self.path(ident,key)).json;self.assertEqual(state['status'],'COMPLETED');r=self.client.get(url+'?offset=2000');self.assertEqual(r.data,self.raw[2000:]);self.assertEqual(r.headers['X-Audio-Complete'],'1');self.assertEqual(r.headers['X-Audio-SHA256'],hashlib.sha256(self.raw).hexdigest());self.assertEqual(state['audio_sha256'],r.headers['X-Audio-SHA256']);self.assertEqual(self.client.get(state['audio_url']).data,self.raw);self.assertIsNone(output.get(self.user,ident,key)['progress'])
   sessions.end(self.user,ident);self.assertEqual(self.client.get(url+'?offset=0').status_code,404)
 def test_end_after_published_prefix_keeps_dispatched_exposure_and_closes_without_retry(self):
  entered,release=Event(),Event();errors=[]
  def chunks():yield self.raw[:2000];entered.set();release.wait(3);yield self.raw[2000:]
  with self.context('Complete translation.'):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);response=self.response(chunks)
   def worker():
    try:live.process(self.user,ident,key,None,info,committed_text='Ucapan lengkap.',whole_output=True)
    except Exception as e:errors.append(e)
   with patch.object(segments.transport,'request',return_value=response) as request:
    thread=Thread(target=worker);thread.start();self.assertTrue(entered.wait(2));state=self.client.get(self.path(ident,key)).json;url=state['audio_progress_url'];self.assertEqual(self.client.get(url+'?offset=0').data,self.raw[:2000]);before=audio.f.db.query_one('SELECT id,initial_reserved_seconds FROM kilas_audio_jobs WHERE user_id=?',(self.user,));self.assertGreater(before['initial_reserved_seconds'],0)
    sessions.end(self.user,ident);release.set();thread.join(4);self.assertFalse(thread.is_alive());self.assertEqual(len(errors),1);request.assert_called_once();response.__exit__.assert_called_once()
   after=audio.f.db.query_one('SELECT status,initial_reserved_seconds FROM kilas_audio_jobs WHERE id=?',(before['id'],));self.assertEqual(after['status'],'FAILED');self.assertEqual(after['initial_reserved_seconds'],before['initial_reserved_seconds']);self.assertIsNone(output.get(self.user,ident,key));self.assertEqual(self.client.get(url+'?offset=0').status_code,404)
 def test_progress_bounds_and_discard_cannot_reappear(self):
  with self.context('Complete.'):
   self.credit(300);ident=self.session();key=self.key();sessions.claim(self.user,ident,key);output.activate(self.user,ident,key);output.bind(self.user,ident,key,123,dict(text='Complete.',source_text='Lengkap.',source_language='id',target_language='en'));output.progress_begin(self.user,123)
   with patch.object(output,'MAX_ENTRY_BYTES',40*1024*1024):
    output.progress_append(self.user,123,b'x'*(20*1024*1024))
    with self.assertRaises(audio_store.AudioError):output.progress_append(self.user,123,b'x')
   self.assertEqual(len(output.progress_read(self.user,ident,key,0)[0]),65536);output.discard(self.user,ident,key)
   with self.assertRaises(audio_store.AudioError):output.progress_append(self.user,123,b'x')
   self.assertIsNone(output.progress_read(self.user,ident,key,0))

if __name__=='__main__':unittest.main()
