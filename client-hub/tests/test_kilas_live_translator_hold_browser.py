"""Real local Chromium -> Flask -> accounting/media, synthetic providers only."""
import json,time,unittest
from pathlib import Path
from unittest.mock import patch
from threading import Event
import test_kilas_live_translator_app_browser as fixture
from kilas_ai import live_translator_realtime as realtime,live_translator_segments as segments
import test_kilas_audio as audio

class HoldBrowserTests(unittest.TestCase):
 setUp=fixture.BrowserApplicationFlowTests.setUp
 setUpClass=fixture.BrowserApplicationFlowTests.__dict__['setUpClass']
 def funded(self,*args):return fixture.BrowserApplicationFlowTests.funded(self,2000000,2000000)
 on=fixture.BrowserApplicationFlowTests.on
 credit=fixture.BrowserApplicationFlowTests.credit
 signal=fixture.BrowserApplicationFlowTests.signal
 transcribe=fixture.BrowserApplicationFlowTests.transcribe
 context=fixture.BrowserApplicationFlowTests.context
 output_transport=fixture.BrowserApplicationFlowTests.output_transport
 wait=fixture.BrowserApplicationFlowTests.wait
 actual_browser=fixture.BrowserApplicationFlowTests.actual_browser
 def test_actual_hold_release_four_directions_replay_and_stop_without_auto_capture(self):
  self.credit(300);sources=['Saya tidak pesan 20 tiket.','Did Rina order 12 tickets?','Nama saya Budi.','Do not buy the red bag.'];targets=['I did not order 20 tickets.','Apakah Rina memesan 12 tiket?','My name is Budi.','Jangan beli tas merah itu.'];directions=[('id','en'),('en','id'),('id','en'),('en','id')]
  sockets=iter([fixture.AutomaticSocket(v) for v in sources]);count=0
  def translate(*args,**kwargs):
   nonlocal count
   self.assertEqual(json.loads(args[2][0]['content']),{'source_text':sources[count]});self.assertIn('never answer',kwargs['system']);self.assertEqual(kwargs['response_format']['type'],'json_schema')
   a,b=directions[count];text=targets[count];count+=1
   yield {'type':'delta','text':json.dumps({'text':text,'source_language':a,'target_language':b})};yield {'type':'usage','input_tokens':90,'output_tokens':50};yield {'type':'finish','reason':'stop'}
  with self.context(realtime_on=True),patch.object(realtime,'connect',side_effect=lambda *a:next(sockets)) as connect,patch.object(segments.transport,'request',side_effect=lambda *a,**k:self.output_transport()) as speech,self.actual_browser() as (page,requests,errors):
   self.translation_mock.side_effect=translate
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("document.querySelector('#live-hold')?.disabled===false")
   self.assertEqual(page.evaluate('qa.starts'),0);self.assertFalse(any('/input/start' in path for _,path in requests))
   for n,width in enumerate((320,390,768,1440)):
    page.set_viewport_size({'width':width,'height':900});button=page.locator('#live-hold');button.hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate('qa.rms=.2');page.wait_for_timeout(200)
    if n==0:
     page.evaluate('qa.rms=0');page.wait_for_timeout(2200);self.assertEqual(count,0);self.assertEqual(speech.call_count,0);page.evaluate('qa.rms=.2');page.wait_for_timeout(100)
    page.mouse.move(width-2,20);page.mouse.up();page.evaluate('qa.rms=0');page.wait_for_function('qa.plays==='+str(n+1),timeout=8000)
    self.assertEqual(page.evaluate('qa.mics'),0);self.assertEqual(page.locator('.live-message').count(),n+1);self.assertEqual(page.locator('.live-message-translated').nth(n).text_content(),targets[n]);self.assertEqual(page.locator('.live-message-original').nth(n).text_content(),sources[n]);self.assertIn('first' if n%2==0 else 'second',page.locator('.live-message').nth(n).get_attribute('class'))
    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'));self.assertLess(button.bounding_box()['x'],page.locator('#live-end').bounding_box()['x'])
    page.evaluate('qaFinishAudio()');page.wait_for_function("document.querySelector('#live-hold').disabled===false");self.assertEqual(page.evaluate('qa.starts'),n+1)
    out=Path('/tmp/kilas-translator-hold-browser');out.mkdir(exist_ok=True);page.screenshot(path=str(out/f'hold-{width}.png'))
   # Technical expiry renewal retains the same session, text and local audio.
   ident=audio.f.db.query_one('SELECT id FROM kilas_live_translator_sessions WHERE user_id=?',(self.user,))['id']
   audio.f.db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',ident))
   page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
   page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
   page.wait_for_function("document.querySelector('#live-hold').disabled===false");self.assertEqual(page.locator('.live-message').count(),4)
   self.assertEqual(audio.f.db.query_one('SELECT expires_at FROM kilas_live_translator_sessions WHERE id=?',(ident,))['expires_at'],'')
   before=(count,connect.call_count,speech.call_count,len([p for _,p in requests if p.endswith('/audio')]))
   page.locator('.live-replay').first.click();page.wait_for_function('qa.plays===5');self.assertEqual(page.evaluate('qa.mics'),0);page.evaluate('qaFinishAudio()');page.wait_for_function("document.querySelector('#live-hold').disabled===false")
   self.assertEqual(before,(count,connect.call_count,speech.call_count,len([p for _,p in requests if p.endswith('/audio')])));self.assertEqual(bytes(page.evaluate('qa.decoded[4]')),self.raw)
   # Intent cancellation discards fresh speech and cannot auto-rearm after blur.
   page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate("dispatchEvent(new Event('blur'))");page.mouse.up();page.wait_for_function('qa.mics===0');self.assertEqual(count,4)
   page.locator('#live-end').click();page.wait_for_function("document.querySelector('#live-active').hidden");self.assertEqual(page.locator('.live-message').count(),0);self.assertEqual(page.evaluate('qa.mics'),0);self.assertFalse(errors,errors)

 def test_permission_completion_after_release_or_stop_never_starts_worklet_or_supplier(self):
  self.credit(300)
  with self.context(realtime_on=True),patch.object(realtime,'connect') as connect,self.actual_browser() as (page,requests,errors):
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("document.querySelector('#live-hold').disabled===false")
   page.evaluate("() => {const original=navigator.mediaDevices.getUserMedia;navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{qa.resolveMic=async()=>resolve(await original());});}")
   for stop in (False,True):
    page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('typeof qa.resolveMic==="function"')
    if stop:page.locator('#live-end').dispatch_event('click')
    page.mouse.up();page.evaluate('void qa.resolveMic();delete qa.resolveMic');page.wait_for_function('qa.mics===0');page.wait_for_timeout(50)
    self.assertEqual(page.evaluate('qa.worklets.length'),0);connect.assert_not_called();self.assertFalse(any('/input/start' in path for _,path in requests))
   self.assertFalse(errors,errors)
