"""Matched cloud Chromium timing experiment, real app endpoints, synthetic media/providers.

Baseline disables only early publication to reproduce previous completed-audio text gate.
No external connections or paid calls; browser audio-start is not hardware audibility.
"""
import json,time,unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from contextlib import nullcontext
import test_kilas_live_translator_hold_browser as fixture
from kilas_ai import live_translator_realtime as realtime,live_translator_segments as segments,live_translator_output as output,usage

class LatencyBrowserTests(fixture.HoldBrowserTests):
 def test_matched_three_turns_before_after_complete_text_publication(self):
  self.credit(1000);source=['Saya mau dua tiket.','Is my meeting at seven or eight?','Nama saya Rina. Jangan beli 12 tiket merah untuk besok. Saya hanya perlu dua tiket biru untuk perjalanan hari Senin.'];target=['I want two tickets.','Apakah rapat saya jam tujuh atau delapan?','My name is Rina. Do not buy 12 red tickets for tomorrow. I only need two blue tickets for the trip on Monday.'];directions=[('id','en'),('en','id'),('id','en')];measurements=[];n=0
  sockets=iter([fixture.fixture.AutomaticSocket(v) for v in source+source])
  def translation(*args,**kwargs):
   nonlocal n
   i=n%3;self.assertEqual(json.loads(args[2][0]['content']),{'source_text':source[i]});time.sleep(.2);a,b=directions[i];n+=1
   yield {'type':'delta','text':json.dumps({'text':target[i],'source_language':a,'target_language':b})};yield {'type':'usage','input_tokens':90,'output_tokens':50};yield {'type':'finish','reason':'stop'}
  def speech(*args,**kwargs):
   response=self.output_transport()
   def chunks():time.sleep(1);yield self.raw[:100];yield self.raw[100:]
   response.iter_content.side_effect=lambda _:chunks();return response
  with self.context(realtime_on=True),patch.object(realtime,'connect',side_effect=lambda *a:next(sockets)) as connect,patch.object(segments.transport,'request',side_effect=speech) as synth:
   self.translation_mock.side_effect=translation
   clock=usage._now
   for arm in ('before','after'):
    # Advance the synthetic rate window between arms; retain every ledger row/cap.
    with (patch.object(usage,'_now',side_effect=lambda:clock()+timedelta(seconds=61)) if arm=='after' else nullcontext()), (patch.object(output,'publish_translation',return_value=None) if arm=='before' else nullcontext()),self.actual_browser() as (page,requests,errors):
     page.evaluate('''()=>{window.qaFirstText=[];window.qaAudio=[];window.qaMetrics=[];new MutationObserver(()=>{const n=document.querySelectorAll('.live-message-translated').length;while(qaFirstText.length<n)qaFirstText.push(performance.now());}).observe(document,{subtree:true,childList:true});const create=AudioContext.prototype.createBufferSource;AudioContext.prototype.createBufferSource=function(){const node=create.call(this),start=node.start;node.start=function(...a){qaAudio.push(performance.now());return start.apply(this,a)};return node};const info=console.info;console.info=(...args)=>{if(String(args[0]).startsWith('KILAS_LIVE_CLIENT_LATENCY'))qaMetrics.push(String(args[0]));info.apply(console,args)};}''')
     page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("document.querySelector('#live-hold').disabled===false");self.assertEqual(page.evaluate('qa.starts'),1)
     for i,width in enumerate((390,768,1440)):
      page.set_viewport_size({'width':width,'height':950});fixture.record(page);page.evaluate('qa.rms=.2');page.wait_for_timeout(180 if i<2 else 600);released=page.evaluate('performance.now()');fixture.stop_recording(page);page.evaluate('qa.rms=0');page.wait_for_function('qaFirstText.length==='+str(i+1),timeout=6000)
      self.assertEqual(page.locator('.live-message-translated').last.text_content(),target[i]);self.assertEqual(page.locator('.live-message-original').last.text_content(),source[i]);self.assertEqual(page.evaluate('qa.mics'),0)
      if arm=='after':
       self.assertTrue(page.locator('#live-hold').is_disabled());self.assertEqual(page.locator('.live-replay').count(),i);page.evaluate('window.qaPendingRow=document.querySelectorAll(".live-message")[document.querySelectorAll(".live-message").length-1]')
      page.wait_for_function('qaAudio.length==='+str(i+1),timeout=6000);first_text=page.evaluate('qaFirstText['+str(i)+']');first_audio=page.evaluate('qaAudio['+str(i)+']');self.assertEqual(page.locator('.live-message').count(),i+1);self.assertEqual(page.locator('.live-replay').count(),i+1)
      if arm=='after':self.assertTrue(page.evaluate('qaPendingRow===document.querySelectorAll(".live-message")[document.querySelectorAll(".live-message").length-1]'))
      measurements.append(dict(arm=arm,fixture=i,width=width,release_to_first_text_ms=round(first_text-released,1),release_to_audio_start_proxy_ms=round(first_audio-released,1)));page.evaluate('qaFinishAudio()');page.wait_for_function("document.querySelector('#live-hold').disabled===false");self.assertEqual(page.evaluate('qa.starts'),i+1)
     before=(connect.call_count,synth.call_count,n);page.locator('.live-replay').first.click();page.wait_for_function('qaAudio.length===4');page.evaluate('qaFinishAudio()');page.wait_for_function("document.querySelector('#live-hold').disabled===false");self.assertEqual((connect.call_count,synth.call_count,n),before)
     if arm=='after':
      out=Path('/tmp/kilas-translator-early-text');out.mkdir(exist_ok=True);page.screenshot(path=str(out/'completed-1440.png'));(out/'client-metrics.json').write_text(json.dumps(page.evaluate('qaMetrics'),indent=2))
     page.locator('#live-end').click();page.wait_for_function("document.querySelector('#live-active').hidden");self.assertEqual(page.evaluate('qa.mics'),0);self.assertFalse(errors,errors)
   self.assertEqual(connect.call_count,6);self.assertEqual(synth.call_count,6);self.assertEqual(n,6)
  for i in range(3):
   before=next(v for v in measurements if v['arm']=='before' and v['fixture']==i);after=next(v for v in measurements if v['arm']=='after' and v['fixture']==i);self.assertGreater(before['release_to_first_text_ms']-after['release_to_first_text_ms'],500)
  out=Path('/tmp/kilas-translator-early-text');out.mkdir(exist_ok=True);(out/'benchmark.json').write_text(json.dumps({'method':'real local app/browser, matched200ms model +1000ms TTS mocks, no paid calls','measurements':measurements},indent=2));print('KILAS_CONTROLLED_BENCHMARK '+json.dumps(measurements))

if __name__=='__main__':unittest.main()
