"""Measured short id/en path; no paid providers or transcript truncation."""
import json,unittest
from unittest.mock import patch
import test_kilas_live_translator as fixture
from kilas_ai import live_translator as live,providers,translator_latency_benchmark as bench

class MeasuredEffortTests(unittest.TestCase):
 setUp=fixture.LiveTranslatorTests.setUp
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 key=fixture.LiveTranslatorTests.key
 def test_measured_both_directions_use_none_with_identical_full_output_budget(self):
  for a,b,text in bench.SOURCES:
   baseline=live.translation_profile(text);profile=live.translation_profile(text,pair=(a,b))
   self.assertEqual(profile['effort'],'none');self.assertEqual({k:v for k,v in profile.items() if k!='effort'},{k:v for k,v in baseline.items() if k!='effort'})
 def test_other_languages_very_short_long_complex_and_reconciliation_keep_low(self):
  short=bench.SOURCES[0][2]
  for text,pair,whole in [(short,('id','ja'),True),('What does this mean?',('id','en'),True),('long spoken sentence '*15,('id','en'),True),('Analisis strategi bisnis dan risiko; jangan pakai modal besar, harus tanpa iklan, hanya sendiri.',('id','en'),True),(short,('id','en'),False),(short,None,True)]:
   self.assertEqual(live.translation_profile(text,pair=pair,whole=whole)['effort'],'low')
 def test_real_translation_boundary_keeps_complete_source_and_one_billed_request(self):
  text=bench.SOURCES[0][2];output="My name is Rina, not Budi. It's not Friday; it's scheduled for Monday, October 26, 2026. The total is Rp125,000. Does that include shipping?"
  def stream(*args,**kwargs):
   self.assertEqual(json.loads(args[2][0]['content']),{'source_text':text});self.assertEqual(kwargs['profile']['effort'],'none');self.assertEqual(kwargs['profile']['output_tokens'],3500)
   yield {'type':'delta','text':json.dumps({'text':output,'source_language':'id','target_language':'en'})};yield {'type':'usage','input_tokens':386,'output_tokens':65};yield {'type':'finish','reason':'stop'}
  with self.funded(),self.on(),patch.object(providers,'_openai',side_effect=stream) as request:
   result=live.translation(self.user,self.key(),text,'id','en',lambda:None)
  self.assertEqual(result['text'],output);request.assert_called_once()
 def test_unclear_translation_remains_explicit_error_and_does_not_retry(self):
  def stream(*args,**kwargs):
   yield {'type':'delta','text':json.dumps({'text':'','source_language':'unknown','target_language':'unknown'})};yield {'type':'usage','input_tokens':20,'output_tokens':15};yield {'type':'finish','reason':'stop'}
  with self.funded(),self.on(),patch.object(providers,'_openai',side_effect=stream) as request:
   with self.assertRaises(live.audio_store.AudioError) as error:live.translation(self.user,self.key(),'This phrase is unclear between languages.','id','en',lambda:None)
  self.assertEqual(error.exception.code,'translation_ambiguous');request.assert_called_once()

if __name__=='__main__':unittest.main()
