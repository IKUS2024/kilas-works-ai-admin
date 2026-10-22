"""Native Chromium click lifecycle + actual app routes, synthetic audio/providers."""
import json,unittest
from unittest.mock import patch
import test_kilas_live_translator_hold_browser as fixture
import test_kilas_live_translator_app_browser as browser
from kilas_ai import live_translator_realtime as realtime,live_translator_segments as segments

GESTURE='''
window.qaGesture=false;qa.micGestures=[];
for(const type of ['click','keydown','pointerdown'])document.addEventListener(type,()=>{qaGesture=true;setTimeout(()=>qaGesture=false,0);},true);
const getMicrophone=navigator.mediaDevices.getUserMedia;navigator.mediaDevices.getUserMedia=function(...args){qa.micGestures.push(qaGesture);return getMicrophone.apply(this,args);};
'''
class ToggleBrowserTests(unittest.TestCase):
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
 def test_continuous_silence_turns_stream_and_stop_during_audio_prevents_recapture(self):
  self.credit(300);sources=iter(['Saya mau dua tiket.','Please wait here.']);targets=['I want two tickets.','Tolong tunggu di sini.'];direction={'n':0}
  with self.context(realtime_on=True),patch.object(realtime,'connect',side_effect=lambda *a:browser.AutomaticSocket(next(sources))) as connect,patch.object(segments.transport,'request',side_effect=lambda *a,**k:self.output_transport()) as speech,self.actual_browser() as (page,requests,errors):
   def translate(*a,**k):
    n=direction['n'];direction['n']+=1
    yield {'type':'delta','text':json.dumps({'text':targets[n],'source_language':'id' if n==0 else 'en','target_language':'en' if n==0 else 'id'})};yield {'type':'usage','input_tokens':90,'output_tokens':30};yield {'type':'finish','reason':'stop'}
   self.translation_mock.side_effect=translate
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();fixture.record(page)
   button=page.locator('#live-hold')
   for n in range(2):
    page.evaluate('qa.rms=.2');page.wait_for_timeout(400);page.evaluate('qa.rms=0')
    page.wait_for_function('qa.plays==='+str(n+1),timeout=10000)
    self.assertEqual(page.evaluate('qa.mics'),0);self.assertEqual(button.inner_text(),'Stop');self.assertFalse(button.is_disabled())
    if n==1:button.click()
    page.evaluate('qaFinishAudio()')
    if n==0:page.wait_for_function("document.querySelector('.kilas-live-orb').dataset.state==='listening'")
   page.wait_for_function("document.querySelector('.kilas-live-orb').dataset.state==='ready'")
   self.assertEqual(page.evaluate('qa.starts'),2);self.assertEqual(page.evaluate('qa.mics'),0)
   self.assertEqual(connect.call_count,2);self.assertEqual(speech.call_count,2);self.batch_mock.assert_not_called()
   self.assertEqual([page.locator('.live-message-translated').nth(n).inner_text() for n in range(2)],targets)
   self.assertEqual(len([p for m,p in requests if p.endswith('/input/commit')]),2)
   page.locator('#live-end').click();self.assertFalse(errors,errors)
 def test_initial_start_records_and_double_clicks_cannot_duplicate_bidirectional_turns(self):
  self.credit(300);directions={'n':0};sources=iter(['Saya mau dua tiket.','Do not buy the red bag.']);targets=['I want two tickets.','Jangan beli tas merah itu.']
  with self.context(realtime_on=True),patch.object(browser,'MEDIA',browser.MEDIA+GESTURE),patch.object(realtime,'connect',side_effect=lambda *a:browser.AutomaticSocket(next(sources))) as connect,patch.object(segments.transport,'request',side_effect=lambda *a,**k:self.output_transport()) as speech,self.actual_browser() as (page,requests,errors):
   def translate(*a,**k):
    n=directions['n'];directions['n']+=1
    yield {'type':'delta','text':json.dumps({'text':targets[n],'source_language':'id' if n==0 else 'en','target_language':'en' if n==0 else 'id'})};yield {'type':'usage','input_tokens':90,'output_tokens':30};yield {'type':'finish','reason':'stop'}
   self.translation_mock.side_effect=translate
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();fixture.record(page)
   button=page.locator('#live-hold');self.assertEqual(button.inner_text(),'Stop');self.assertEqual(button.get_attribute('aria-pressed'),'true');self.assertEqual(page.evaluate('qa.starts'),1)
   page.evaluate('qa.rms=.2');page.wait_for_timeout(400);page.mouse.move(2,2);page.mouse.down();page.mouse.up();self.assertEqual(directions['n'],0);self.assertEqual(page.evaluate('qa.mics'),1)
   button.dblclick();page.evaluate('qa.rms=0');page.wait_for_function('qa.plays===1');self.assertEqual(page.evaluate('qa.mics'),0);self.assertTrue(button.is_disabled());self.assertEqual(button.inner_text(),'Start')
   page.evaluate('qaFinishAudio()');page.wait_for_function("!document.querySelector('#live-hold').disabled");self.assertEqual(button.inner_text(),'Start')
   page.wait_for_timeout(350);button.dblclick();page.wait_for_function("document.querySelector('.kilas-live-orb').dataset.state==='listening'");self.assertEqual(button.inner_text(),'Stop');self.assertEqual(page.evaluate('qa.starts'),2)
   page.evaluate('qa.rms=.2');page.wait_for_timeout(400);button.click();page.evaluate('qa.rms=0');page.wait_for_function('qa.plays===2');page.evaluate('qaFinishAudio()');page.wait_for_function("!document.querySelector('#live-hold').disabled")
   self.assertEqual([page.locator('.live-message-translated').nth(n).inner_text() for n in range(2)],targets);self.assertEqual(connect.call_count,2);self.assertEqual(speech.call_count,2)
   self.assertEqual(len([p for m,p in requests if p.endswith('/input/commit')]),2);self.assertEqual(page.evaluate('qa.micGestures'),[True,True]);self.assertEqual(page.locator('#live-end').inner_text(),'End');page.locator('#live-end').click();self.assertEqual(page.evaluate('qa.mics'),0);self.assertFalse(errors,errors)
 def silent(self,realtime_on):
  self.credit(300)
  with self.context(realtime_on=realtime_on),patch.object(realtime,'connect') as connect,self.actual_browser() as (page,requests,errors):
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();fixture.record(page);self.assertEqual(page.locator('#live-hold').inner_text(),'Stop');fixture.stop_recording(page)
   page.wait_for_function("!document.querySelector('#live-hold').disabled&&document.querySelector('#live-hold').getAttribute('aria-pressed')==='false'")
   self.assertEqual(page.evaluate('qa.mics'),0);self.assertEqual(page.locator('#live-hold').inner_text(),'Start');self.assertFalse(any('/turns/' in p for m,p in requests));connect.assert_not_called();self.batch_mock.assert_not_called();page.locator('#live-end').click();self.assertFalse(errors,errors)
 def test_silent_realtime_start_stop_cleans_stream_without_provider_dispatch(self):self.silent(True)
 def test_silent_batch_start_stop_cleans_stream_without_provider_dispatch(self):self.silent(False)
if __name__=='__main__':unittest.main()
