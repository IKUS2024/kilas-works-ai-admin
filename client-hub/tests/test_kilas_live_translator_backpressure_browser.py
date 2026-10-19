"""Actual Chromium/Flask transport; synthetic microphone and paid providers only."""
import json,time,unittest
from unittest.mock import patch
import test_kilas_live_translator_hold_browser as fixture
import test_kilas_live_translator_app_browser as browser
import test_kilas_audio as audio
from kilas_ai import live_translator_realtime as rt,live_translator_segments as segments

ROUTES='''
qa.routeChanges=[];qa.routeOverlaps=0;let audioType='auto';Object.defineProperty(navigator,'audioSession',{configurable:true,value:{get type(){return audioType;},set type(v){if(v==='playback'&&qa.mics)qa.routeOverlaps++;audioType=v;qa.routeChanges.push(v);}}});
'''
class BackpressureBrowserTests(unittest.TestCase):
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
 def begin(self,page):
  page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("!document.querySelector('#live-hold').disabled")
 def hold(self,page,ms):
  page.locator('#live-hold').hover();page.mouse.down();page.wait_for_function('qa.mics===1');page.evaluate('qa.rms=.2');page.wait_for_timeout(ms);page.mouse.up();page.evaluate('qa.rms=0')
 def finish(self,page,n):
  page.wait_for_function('qa.plays==='+str(n),timeout=15000);self.assertEqual(page.evaluate('qa.mics'),0);page.evaluate('qaFinishAudio()');page.wait_for_function("!document.querySelector('#live-hold').disabled")
 def test_slow_reverse_turn_after_replay_idle_resume_preserves_every_byte_and_audio_route(self):
  self.credit(1000);sources=['Saya mau dua tiket.','Do not buy the red bag.','Nama saya Rina.'];targets=['I want two tickets.','Jangan beli tas merah itu.','My name is Rina.'];sockets=[browser.AutomaticSocket(text) for text in sources];socket_iter=iter(sockets);direction={'n':0};accepted=[]
  def translate(*args,**kwargs):
   n=direction['n'];direction['n']+=1
   yield {'type':'delta','text':json.dumps({'text':targets[n],'source_language':'id' if n%2==0 else 'en','target_language':'en' if n%2==0 else 'id'})};yield {'type':'usage','input_tokens':90,'output_tokens':40};yield {'type':'finish','reason':'stop'}
  accept=rt.Relay.accept
  def checked_accept(relay,index,raw):
   result=accept(relay,index,raw);accepted.append((relay.key,raw));return result
  def slow():
   from flask import request
   if '/input/chunks/' in request.path:time.sleep(1.5)
  app=audio.f.app.app;app.before_request_funcs.setdefault(None,[]).insert(0,slow)
  try:
   with self.context(realtime_on=True),patch.object(browser,'MEDIA',browser.MEDIA+ROUTES),patch.object(rt.Relay,'accept',checked_accept),patch.object(rt,'connect',side_effect=lambda *a:next(socket_iter)) as connect,patch.object(segments.transport,'request',side_effect=lambda *a,**k:self.output_transport()) as speech,self.actual_browser() as (page,requests,errors):
    self.translation_mock.side_effect=translate;self.begin(page)
    self.hold(page,900);self.finish(page,1)
    previous=len(requests);page.locator('.live-replay').first.click();self.finish(page,2);self.assertEqual(len(requests),previous)
    page.wait_for_timeout(300)
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
    page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function("!document.querySelector('#live-hold').disabled")
    self.hold(page,18000);self.finish(page,3)
    self.assertEqual(page.locator('.live-message-translated').nth(1).text_content(),targets[1]);self.assertTrue(page.locator('#live-error').is_hidden())
    self.hold(page,700);self.finish(page,4)
    groups={}
    for key,raw in accepted:groups.setdefault(key,[]).append(raw)
    self.assertEqual(len(groups),3)
    for socket,parts in zip(sockets,groups.values()):self.assertEqual(b''.join(socket.sent),b''.join(parts))
    self.assertTrue(any(len(raw)>32000 for _,raw in accepted));self.assertTrue(all(len(raw)<=128000 for _,raw in accepted))
    self.assertEqual(connect.call_count,3);self.assertEqual(speech.call_count,3);self.assertEqual(direction['n'],3);self.assertEqual(page.locator('.live-message').count(),3)
    self.assertEqual(len([p for m,p in requests if p.endswith('/input/commit')]),3);self.assertFalse(any(p.endswith('/cancel') for m,p in requests))
    self.assertEqual(page.evaluate('qa.routeOverlaps'),0);self.assertEqual(page.evaluate('navigator.audioSession.type'),'playback');page.locator('#live-end').click();self.assertEqual(page.evaluate('navigator.audioSession.type'),'auto');self.assertEqual(page.evaluate("qa.routeChanges.filter(v=>v==='play-and-record').length"),3);self.assertFalse(errors,errors)
  finally:app.before_request_funcs[None].remove(slow)
 def test_missing_worklet_selects_batch_before_speech_and_keeps_transport_on_renewal(self):
  self.credit(300)
  media=browser.MEDIA+ROUTES+"window.AudioWorkletNode=undefined;"
  with self.context(realtime_on=True),patch.object(browser,'MEDIA',media),patch.object(rt,'connect') as connect,patch.object(segments.transport,'request',side_effect=lambda *a,**k:self.output_transport()) as speech,self.actual_browser() as (page,requests,errors):
   self.begin(page);self.hold(page,500);self.finish(page,1);self.assertFalse(any('/input/' in p for m,p in requests));self.assertEqual(self.batch_mock.call_count,1);connect.assert_not_called()
   ident=audio.f.db.query_one('SELECT id FROM kilas_live_translator_sessions WHERE user_id=?',(self.user,))['id'];audio.f.db.execute('UPDATE kilas_live_translator_sessions SET expires_at=? WHERE id=?',('2000-01-01T00:00:00+00:00',ident))
   page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
   page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
   page.wait_for_function("!document.querySelector('#live-hold').disabled");self.hold(page,500);self.finish(page,2)
   self.assertEqual(self.batch_mock.call_count,2);self.assertEqual(speech.call_count,2);connect.assert_not_called();self.assertFalse(any('/input/' in p for m,p in requests));self.assertEqual(page.locator('.live-message').count(),2)
   page.locator('#live-end').click();self.assertEqual(page.evaluate('navigator.audioSession.type'),'auto');self.assertFalse(errors,errors)
 def test_native_web_audio_preserves_measured_quiet_normal_loud_levels_without_clipping(self):
  self.credit(300)
  with self.context(),self.actual_browser() as (page,requests,errors):
   measured=page.evaluate("""async()=>{
    const {TranslatorPlayback}=await import('/static/kilas_live_translator_playback.mjs');const result=[];
    for(const amplitude of [.03,.25,.8]){
     const context=new OfflineAudioContext(1,4800,48000),buffer=context.createBuffer(1,4800,48000),input=buffer.getChannelData(0);
     for(let i=0;i<input.length;i++)input[i]=amplitude*Math.sin(2*Math.PI*400*i/48000);
     const controller=new AbortController(),player=new TranslatorPlayback({getContext:()=>context}),op={context,controller,isCurrent:()=>true};
     const played=player.playBuffer(op,buffer,()=>{}),rendered=await context.startRendering();await played;
     const output=rendered.getChannelData(0);let peak=0,difference=0,square=0;
     for(let i=0;i<output.length;i++){peak=Math.max(peak,Math.abs(output[i]));difference=Math.max(difference,Math.abs(output[i]-input[i]));square+=output[i]**2;}
     result.push({amplitude,peak,rms:Math.sqrt(square/output.length),difference});
    }return result;
   }""")
   for sample in measured:self.assertLess(sample['difference'],1e-6);self.assertLess(sample['peak'],1);self.assertAlmostEqual(sample['peak'],sample['amplitude'],places=5)
   self.assertFalse(any('/input/' in p for m,p in requests));self.assertFalse(errors,errors);print('TRANSLATOR_UNITY_LEVELS '+json.dumps(measured))

if __name__=='__main__':unittest.main()
