"""Actual Chromium/Flask/SQLite, synthetic mic and suppliers. No paid IO."""
import json,unittest
from itertools import chain,repeat
from unittest.mock import patch
import test_kilas_live_translator_toggle_browser as toggle
import test_kilas_live_translator_app_browser as browser
import test_kilas_live_translator_hold_browser as fixture
from test_kilas_live_translator_realtime import Socket
from kilas_ai import live_translator_realtime as realtime,live_translator_segments as segments

DUPLEX=browser.MEDIA.replace('echoCancellation:false','echoCancellation:true').replace('const track={addEventListener()', 'const track={getSettings(){return {echoCancellation:true};},addEventListener()').replace('return {getTracks:()=>[track]};','return {getTracks:()=>[track],getAudioTracks:()=>[track]};').replace("if(qa.mics)throw Error('Playback captured by synthetic microphone');",'if(qa.mics)qa.overlaps=(qa.overlaps||0)+1;')

class StreamingBrowserTests(unittest.TestCase):
 setUp=toggle.ToggleBrowserTests.setUp
 setUpClass=toggle.ToggleBrowserTests.__dict__['setUpClass']
 funded=toggle.ToggleBrowserTests.funded
 on=toggle.ToggleBrowserTests.on
 credit=toggle.ToggleBrowserTests.credit
 signal=toggle.ToggleBrowserTests.signal
 transcribe=toggle.ToggleBrowserTests.transcribe
 context=toggle.ToggleBrowserTests.context
 output_transport=toggle.ToggleBrowserTests.output_transport
 wait=toggle.ToggleBrowserTests.wait
 actual_browser=toggle.ToggleBrowserTests.actual_browser
 def test_two_directions_play_while_speech_continues_and_stop_prevents_third_output(self):
  self.credit(300);socket=Socket(chain(['Saya mau dua tiket.','Please wait here.'],repeat('')));count=0
  targets=['I want two tickets.','Tolong tunggu di sini.']
  def translate(*args,**kwargs):
   nonlocal count
   self.assertLess(count,2);a,b=('id','en') if count==0 else ('en','id');target=targets[count];count+=1
   yield {'type':'delta','text':json.dumps({'text':target,'source_language':a,'target_language':b})}
   yield {'type':'usage','input_tokens':90,'output_tokens':30};yield {'type':'finish','reason':'stop'}
  with self.context(realtime_on=True),patch.object(browser,'MEDIA',DUPLEX),patch.object(realtime,'connect',return_value=socket) as connect,patch.object(segments.transport,'request',side_effect=lambda *a,**k:self.output_transport()) as speech,self.actual_browser() as (page,requests,errors):
   self.translation_mock.side_effect=translate
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();fixture.record(page)
   page.evaluate('qa.rms=.2')
   for n in range(2):
    page.wait_for_function('qa.plays==='+str(n+1),timeout=15000)
    self.assertEqual(page.evaluate('qa.mics'),1);self.assertEqual(page.evaluate('qa.starts'),1)
    self.assertEqual(page.locator('#live-hold').inner_text(),'Stop')
    if n==1:page.locator('#live-hold').click();page.evaluate('qa.rms=0')
    page.evaluate('qaFinishAudio()')
   page.wait_for_function("document.querySelector('.kilas-live-orb').dataset.state==='ready'",timeout=15000)
   page.wait_for_timeout(400)
   self.assertEqual(count,2);self.assertEqual(speech.call_count,2);self.assertEqual(connect.call_count,1)
   self.assertEqual(page.evaluate('qa.overlaps'),2);self.assertEqual(page.evaluate('qa.mics'),0)
   self.assertEqual([page.locator('.live-message-translated').nth(i).inner_text() for i in range(2)],targets)
   page.locator('#live-end').click();self.assertTrue(socket.closed);self.assertFalse(errors,errors)

if __name__=='__main__':unittest.main()
