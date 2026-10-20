"""Deterministic translation timing boundaries; synthetic providers and real ledger."""
import io,json,unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import test_kilas_live_translator as fixture
from kilas_ai import live_translator as live,providers,usage

class TranslationTimingTests(unittest.TestCase):
 setUp=fixture.LiveTranslatorTests.setUp
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 key=fixture.LiveTranslatorTests.key
 def test_arrival_precedes_authority_fence_and_reservation_is_separate_without_changed_request(self):
  clock=[0.0];timings={};checks=[];reserve=usage.reserve
  def reserved(*a,**k):clock[0]+=.3;return reserve(*a,**k)
  def check():clock[0]+=.02;checks.append(True)
  def stream(*a,**k):
   self.assertEqual(a[0],'gpt-6-luna');self.assertEqual(k['profile'],live.translation_profile('Nama saya Rina, bukan Budi.',pair=('id','en')));self.assertEqual(k['event_chunk_size'],1)
   clock[0]+=.7;yield {'type':'delta','text':json.dumps({'text':'My name is Rina, not Budi.','source_language':'id','target_language':'en'})}
   yield {'type':'usage','input_tokens':20,'output_tokens':18};yield {'type':'finish','reason':'stop'}
  with self.funded(),self.on(),patch.object(live,'monotonic',side_effect=lambda:clock[0]),patch.object(usage,'reserve',side_effect=reserved),patch.object(providers,'_openai',side_effect=stream) as provider:
   result=live.translation(self.user,self.key(),'Nama saya Rina, bukan Budi.','id','en',check,timings=timings)
  self.assertEqual(result['text'],'My name is Rina, not Budi.');self.assertEqual(len(checks),4);provider.assert_called_once()
  for name,value in [('translation_reserve_ms',300),('translation_first_event_ms',700),('translation_first_delta_arrival_ms',700),('translation_first_delta_ms',720),('translation_fences_ms',80)]:self.assertAlmostEqual(timings[name],value,places=5)
  output=io.StringIO()
  with patch.object(live,'monotonic',return_value=2),redirect_stdout(output):live._log_latency(timings,0,True)
  log=output.getvalue();self.assertIn('translation_first_delta_arrival_ms=700.0',log);self.assertIn('translation_reserve_ms=300.0',log)
  for private in ['Rina','Budi',self.key(),str(self.user),'synthetic-only','proj_synthetic']:
   if private==str(self.user):continue
   self.assertNotIn(private,log)
if __name__=='__main__':unittest.main()
