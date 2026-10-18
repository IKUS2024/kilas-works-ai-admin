"""Actual Chrome MSE MP3 decoder + local owned routes; no paid suppliers/mic."""
import json,time,unittest
from threading import Event
from pathlib import Path
from unittest.mock import patch
import test_kilas_live_translator_hold_browser as fixture
import test_kilas_live_translator_app_browser as browser_fixture
import test_kilas_audio as audio
from kilas_ai import live_translator_realtime as realtime,live_translator_segments as segments

MEDIA_OVERRIDE='''
window.AudioContext=class extends window.qaNativeAudioContext{
 constructor(){super();this.audioWorklet.addModule=async()=>{};}
 createMediaStreamSource(){return {connect(){},disconnect(){}};}
 createAnalyser(){return {fftSize:2048,disconnect(){},getFloatTimeDomainData(a){a.fill(qa.rms)}};}
 createBufferSource(){const n=super.createBufferSource(),start=n.start;n.start=function(...a){window.qaAudio.push(performance.now());window.qaOffsets.push(a[1]||0);return start.apply(this,a)};return n;}
};
window.qaAudio=[];window.qaMetrics=[];window.qaOffsets=[];window.qaElements=[];
const info=console.info;console.info=(...args)=>{if(String(args[0]).startsWith('KILAS_LIVE_CLIENT_LATENCY'))qaMetrics.push(String(args[0]));info.apply(console,args)};
const NativeAudio=window.Audio;window.Audio=function(...args){const a=new NativeAudio(...args);qaElements.push(a);a.addEventListener('playing',()=>qaAudio.push(performance.now()),{once:true});return a;};
'''
class ProgressiveBrowserTests(unittest.TestCase):
 setUp=fixture.HoldBrowserTests.setUp
 setUpClass=fixture.HoldBrowserTests.__dict__['setUpClass']
 funded=fixture.HoldBrowserTests.funded
 on=fixture.HoldBrowserTests.on
 credit=fixture.HoldBrowserTests.credit
 signal=fixture.HoldBrowserTests.signal
 transcribe=fixture.HoldBrowserTests.transcribe
 context=fixture.HoldBrowserTests.context
 output_transport=fixture.HoldBrowserTests.output_transport
 wait=fixture.HoldBrowserTests.wait
 actual_browser=fixture.HoldBrowserTests.actual_browser
 def test_matched_complete_vs_progressive_real_decoder_alternating_and_replay(self):
  self.credit(1000);self.raw=audio.mp3(3);sources=['Saya mau dua tiket.','Is my meeting at seven?'];targets=['I want two tickets.','Apakah rapat saya jam tujuh?'];n=0;measurements=[]
  sockets=iter([browser_fixture.AutomaticSocket(s) for s in sources+sources])
  def translation(*args,**kwargs):
   nonlocal n
   i=n%2;n+=1;self.assertEqual(json.loads(args[2][0]['content']),{'source_text':sources[i]});time.sleep(.2)
   yield {'type':'delta','text':json.dumps(dict(text=targets[i],source_language='id' if i==0 else 'en',target_language='en' if i==0 else 'id'))};yield {'type':'usage','input_tokens':90,'output_tokens':50};yield {'type':'finish','reason':'stop'}
  def speech(*args,**kwargs):
   response=self.output_transport()
   def chunks():
    time.sleep(.1);yield self.raw[:len(self.raw)//2];time.sleep(1.1);yield self.raw[len(self.raw)//2:]
   response.iter_content.side_effect=lambda _:chunks();return response
  original_media=browser_fixture.MEDIA
  with self.context(realtime_on=True),patch.object(realtime,'connect',side_effect=lambda *a:next(sockets)) as connect,patch.object(segments.transport,'request',side_effect=speech) as synth,patch.object(browser_fixture,'MEDIA','window.qaNativeAudioContext=AudioContext;'+original_media+MEDIA_OVERRIDE):
   self.translation_mock.side_effect=translation
   for arm in ('complete','progressive'):
    override=MEDIA_OVERRIDE+("AudioContext.prototype.createMediaElementSource=undefined;" if arm=='complete' else '')
    with patch.object(browser_fixture,'MEDIA','window.qaNativeAudioContext=AudioContext;'+original_media+override),self.actual_browser() as (page,requests,errors):
     page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("!document.querySelector('#live-hold').disabled")
     for i in range(2):
      page.set_viewport_size({'width':390 if i==0 else 1440,'height':950});page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate('qa.rms=.2');page.wait_for_timeout(200);released=page.evaluate('performance.now()');page.mouse.up();page.evaluate('qa.rms=0');page.wait_for_function('qaAudio.length==='+str(i+1),timeout=10000)
      onset=page.evaluate('qaAudio['+str(i)+']');self.assertEqual(page.evaluate('qa.mics'),0);self.assertTrue(page.locator('#live-hold').is_disabled());self.assertEqual(page.locator('.live-message-original').last.text_content(),sources[i]);self.assertEqual(page.locator('.live-message-translated').last.text_content(),targets[i]);
      if arm=='progressive':self.assertEqual(page.locator('.live-replay').count(),i)
      page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=12000);self.assertEqual(page.locator('.live-replay').count(),i+1)
      measurements.append(dict(arm=arm,direction='id-en' if i==0 else 'en-id',release_to_browser_onset_ms=round(onset-released,1)))
     before=(connect.call_count,synth.call_count,n);reads=len(requests);page.locator('.live-replay').first.click();page.wait_for_function('qaAudio.length===3');page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=8000);self.assertEqual((connect.call_count,synth.call_count,n),before);self.assertFalse(any('/audio' in p for _,p in requests[reads:]))
     page.locator('#live-end').click();page.wait_for_function("document.querySelector('#live-active').hidden");self.assertFalse(errors,errors)
     if arm=='complete':self.assertFalse(any('/audio/progress' in p for _,p in requests))
     else:self.assertTrue(any('/audio/progress' in p for _,p in requests))
   self.assertEqual(synth.call_count,4);self.assertEqual(connect.call_count,4)
  for direction in ('id-en','en-id'):
   old=next(v for v in measurements if v['arm']=='complete' and v['direction']==direction);new=next(v for v in measurements if v['arm']=='progressive' and v['direction']==direction);self.assertGreater(old['release_to_browser_onset_ms']-new['release_to_browser_onset_ms'],400)
  out=Path('/tmp/kilas-translator-progressive');out.mkdir(exist_ok=True);(out/'benchmark.json').write_text(json.dumps(measurements,indent=2));print('CONTROLLED_PROGRESSIVE '+json.dumps(measurements))

 def test_stop_during_real_progressive_playback_cleans_media_and_never_replays_or_recaptures(self):
  self.credit(300);self.raw=audio.mp3(3);release=Event()
  def speech(*args,**kwargs):
   response=self.output_transport()
   def chunks():yield self.raw[:len(self.raw)//2];release.wait(5);yield self.raw[len(self.raw)//2:]
   response.iter_content.side_effect=lambda _:chunks();return response
  media='window.qaNativeAudioContext=AudioContext;'+browser_fixture.MEDIA+MEDIA_OVERRIDE
  with self.context(realtime_on=True),patch.object(browser_fixture,'MEDIA',media),patch.object(realtime,'connect',return_value=browser_fixture.AutomaticSocket('Saya mau tiket.')) as connect,patch.object(segments.transport,'request',side_effect=speech) as synth,self.actual_browser() as (page,requests,errors):
   self.translation_mock.side_effect=lambda *a,**k:(v for v in [{'type':'delta','text':json.dumps(dict(text='I want a ticket.',source_language='id',target_language='en'))},{'type':'usage','input_tokens':90,'output_tokens':40},{'type':'finish','reason':'stop'}])
   try:
    page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("!document.querySelector('#live-hold').disabled");page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate('qa.rms=.2');page.wait_for_timeout(200);page.mouse.up();page.evaluate('qa.rms=0');page.wait_for_function('qaAudio.length===1',timeout=5000);self.assertEqual(page.locator('.live-replay').count(),0)
    page.locator('#live-end').click();page.wait_for_function("document.querySelector('#live-active').hidden");release.set();page.wait_for_timeout(500);self.assertEqual(page.evaluate('qa.mics'),0);self.assertEqual(page.evaluate('qa.starts'),1);self.assertEqual(page.evaluate('qaAudio.length'),1);self.assertEqual(page.locator('.live-message').count(),0);synth.assert_called_once();connect.assert_called_once();self.assertFalse(errors,errors)
   finally:release.set()

 def test_visibility_reconnect_resumes_validated_same_audio_near_playhead_without_provider_repeat(self):
  self.credit(300);self.raw=audio.mp3(3);release=Event()
  def speech(*args,**kwargs):
   response=self.output_transport()
   def chunks():yield self.raw[:len(self.raw)//2];release.wait(5);yield self.raw[len(self.raw)//2:]
   response.iter_content.side_effect=lambda _:chunks();return response
  media='window.qaNativeAudioContext=AudioContext;'+browser_fixture.MEDIA+MEDIA_OVERRIDE
  with self.context(realtime_on=True),patch.object(browser_fixture,'MEDIA',media),patch.object(realtime,'connect',return_value=browser_fixture.AutomaticSocket('Saya mau tiket.')) as connect,patch.object(segments.transport,'request',side_effect=speech) as synth,self.actual_browser() as (page,requests,errors):
   self.translation_mock.side_effect=lambda *a,**k:(v for v in [{'type':'delta','text':json.dumps(dict(text='I want a ticket.',source_language='id',target_language='en'))},{'type':'usage','input_tokens':90,'output_tokens':40},{'type':'finish','reason':'stop'}])
   try:
    page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("!document.querySelector('#live-hold').disabled");page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate('qa.rms=.2');page.wait_for_timeout(200);page.mouse.up();page.evaluate('qa.rms=0');page.wait_for_function('qaAudio.length===1',timeout=5000);page.wait_for_timeout(300);position=page.evaluate('qaElements[0].currentTime');self.assertGreater(position,.2)
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))");release.set();page.wait_for_timeout(100);self.assertTrue(page.evaluate('qaElements[0].paused'));self.assertEqual(page.evaluate('qa.mics'),0)
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))");page.wait_for_function('qaOffsets.length===1',timeout=6000);offset=page.evaluate('qaOffsets[0]');self.assertGreater(offset,0);self.assertLess(abs(offset-max(0,position-.1)),.15);page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=8000);self.assertEqual(page.locator('.live-message').count(),1);self.assertEqual(page.locator('.live-replay').count(),1);self.assertEqual(page.evaluate('qa.starts'),1);connect.assert_called_once();synth.assert_called_once();self.assertEqual(len([p for m,p in requests if p.endswith('/input/commit')]),1);page.locator('#live-end').click();self.assertFalse(errors,errors)
   finally:release.set()

 def test_slow_tail_starvation_continues_to_real_media_end_without_cut_or_second_request(self):
  self.credit(300);self.raw=audio.mp3(3)
  def speech(*args,**kwargs):
   response=self.output_transport()
   def chunks():yield self.raw[:2000];time.sleep(1.3);yield self.raw[2000:]
   response.iter_content.side_effect=lambda _:chunks();return response
  media='window.qaNativeAudioContext=AudioContext;'+browser_fixture.MEDIA+MEDIA_OVERRIDE
  with self.context(realtime_on=True),patch.object(browser_fixture,'MEDIA',media),patch.object(realtime,'connect',return_value=browser_fixture.AutomaticSocket('Saya mau tiket.')) as connect,patch.object(segments.transport,'request',side_effect=speech) as synth,self.actual_browser() as (page,requests,errors):
   self.translation_mock.side_effect=lambda *a,**k:(v for v in [{'type':'delta','text':json.dumps(dict(text='I want a ticket.',source_language='id',target_language='en'))},{'type':'usage','input_tokens':90,'output_tokens':40},{'type':'finish','reason':'stop'}])
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("!document.querySelector('#live-hold').disabled");page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate('qa.rms=.2');page.wait_for_timeout(200);page.mouse.up();page.evaluate('qa.rms=0');page.wait_for_function('qaAudio.length===1',timeout=5000);page.evaluate("window.qaWaiting=0;qaElements[0].addEventListener('waiting',()=>qaWaiting++)");self.assertEqual(page.locator('.live-replay').count(),0);self.assertEqual(page.evaluate('qa.mics'),0)
   page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=10000);self.assertGreaterEqual(page.evaluate('qaWaiting'),1);self.assertEqual(page.evaluate('qaAudio.length'),1);self.assertEqual(page.locator('.live-replay').count(),1);self.assertEqual(page.evaluate('qa.starts'),1);synth.assert_called_once();connect.assert_called_once();self.assertFalse(errors,errors);page.locator('#live-end').click()

if __name__=='__main__':unittest.main()
