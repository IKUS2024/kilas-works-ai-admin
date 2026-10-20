"""Native Chromium MP3/WebAudio plus explicit per-element gesture policy.
Microphone/provider boundaries synthetic; this is not iPad/WebKit certification.
"""
import json,time,unittest
from unittest.mock import patch
import test_kilas_live_translator_hold_browser as fixture
import test_kilas_live_translator_app_browser as browser
import test_kilas_live_translator_progressive_browser as progressive
import test_kilas_audio as audio
from kilas_ai import live_translator_realtime as realtime,live_translator_segments as segments

POLICY='''
window.qaGesture=false;window.qaPrimeDenied=false;window.qaOutputDenied=false;window.qaPlayCalls=[];window.qaDecoded=[];
const decode=AudioContext.prototype.decodeAudioData;AudioContext.prototype.decodeAudioData=function(raw,...args){qaDecoded.push(Array.from(new Uint8Array(raw)));return decode.call(this,raw,...args);};
for(const event of ['click','keydown','pointerdown'])document.addEventListener(event,()=>{qaGesture=true;setTimeout(()=>qaGesture=false,0);},true);
const nativePlay=HTMLMediaElement.prototype.play,authorized=new WeakSet();
HTMLMediaElement.prototype.play=function(){
 const prime=this.src.startsWith('data:audio/wav'),gesture=qaGesture;
 qaPlayCalls.push({prime,gesture,allowed:authorized.has(this)});
 if((prime&&qaPrimeDenied)||(!prime&&qaOutputDenied)||(!gesture&&!authorized.has(this))){qaOutputDenied=false;return Promise.reject(new DOMException('The request is not allowed by the user agent or the platform in the current context, possibly because the user denied permission.','NotAllowedError'));}
 if(gesture)authorized.add(this);
 if(qa.mics)throw Error('Audio overlapped microphone');return nativePlay.call(this);
};
'''
class SafariBrowserTests(unittest.TestCase):
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
 def speak(self,page,n):
  fixture.record(page);page.evaluate('qa.rms=.2');page.wait_for_timeout(220);fixture.stop_recording(page);page.evaluate('qa.rms=0');page.wait_for_function('qa.mics===0')
 def exercise(self,mode):
  self.credit(1000);self.raw=audio.mp3(1);measurements=[]
  # Keep PROCESSING long enough to exercise the progressive permission branch.
  def speech(*args,**kwargs):
   response=self.output_transport()
   def chunks():yield self.raw[:len(self.raw)//2];time.sleep(.65);yield self.raw[len(self.raw)//2:]
   response.iter_content.side_effect=lambda _:chunks();return response
  sources=iter(['Saya mau dua tiket.','Is my meeting at seven?'])
  media='window.qaNativeAudioContext=AudioContext;'+browser.MEDIA+progressive.MEDIA_OVERRIDE+POLICY
  with self.context(realtime_on=True),patch.object(browser,'MEDIA',media),patch.object(realtime,'connect',side_effect=lambda *a:browser.AutomaticSocket(next(sources))) as connect,patch.object(segments.transport,'request',side_effect=speech) as synth,self.actual_browser() as (page,requests,errors):
   direction={'n':0}
   def translation(*args,**kwargs):
    i=direction['n'];direction['n']+=1
    yield from [{'type':'delta','text':json.dumps(dict(text=['I want two tickets.','Apakah rapat saya jam tujuh?'][i],source_language='id' if i%2==0 else 'en',target_language='en' if i%2==0 else 'id'))},{'type':'usage','input_tokens':90,'output_tokens':40},{'type':'finish','reason':'stop'}]
   self.translation_mock.side_effect=translation
   page.evaluate('qaPrimeDenied='+str(mode=='prime_denied').lower())
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.wait_for_function("!document.querySelector('#live-hold').disabled")
   self.assertEqual(page.evaluate('qa.mics'),1);self.assertTrue(page.evaluate('qaPlayCalls[0].gesture'))
   if mode=='output_denied':page.evaluate('qaOutputDenied=true')
   self.speak(page,0)
   if mode=='output_denied':
    page.locator('#live-resume').wait_for(state='visible',timeout=10000)
    self.assertIn('Audio belum diizinkan',page.locator('#live-error').inner_text());self.assertNotIn('user agent',page.locator('#live-error').inner_text());self.assertEqual(page.locator('.live-message').count(),1);self.assertEqual(page.locator('.live-replay').count(),1);self.assertEqual(page.evaluate('qa.mics'),0)
    self.assertEqual(len([p for m,p in requests if p.endswith('/cancel')]),0)
    page.locator('#live-resume').click()
   page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=10000)
   self.assertEqual(page.locator('.live-message').count(),1)
   before=len([p for m,p in requests if '/audio' in p]);page.locator('.live-replay').first.click();page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=6000);self.assertEqual(len([p for m,p in requests if '/audio' in p]),before);self.assertEqual(bytes(page.evaluate('qaDecoded.at(-1)')),self.raw)
   self.speak(page,1);page.wait_for_function("!document.querySelector('#live-hold').disabled",timeout=10000)
   self.assertEqual(page.locator('.live-message').count(),2);self.assertEqual(page.evaluate('qa.starts'),2);self.assertEqual(page.evaluate('qa.mics'),0);self.assertEqual(synth.call_count,2);self.assertEqual(connect.call_count,2);self.assertEqual(page.evaluate('qaElements.length'),1)
   self.assertEqual(len([p for m,p in requests if p.endswith('/input/commit')]),2)
   if mode=='prime_denied':self.assertFalse(any('/audio/progress' in p for m,p in requests))
   if mode=='allowed':self.assertTrue(page.evaluate('qaPlayCalls.filter(v=>!v.prime).every(v=>v.allowed&&!v.gesture)'))
   measurements.append({'mode':mode,'timings':page.evaluate('qaMetrics'),'play_calls':page.evaluate('qaPlayCalls')})
   page.locator('#live-end').click();self.assertFalse(errors,errors)
  print('SAFARI_POLICY_BROWSER '+json.dumps(measurements))

 def test_same_element_repeated_turns_and_cached_replay(self):self.exercise('allowed')
 def test_output_denial_retains_paid_audio_until_explicit_resume(self):self.exercise('output_denied')
 def test_priming_denial_uses_complete_file_web_audio(self):self.exercise('prime_denied')

 def microphone_denial(self,realtime_on):
  self.credit(300)
  with self.context(realtime_on=realtime_on),self.actual_browser() as (page,requests,errors):
   page.evaluate("()=>{window.qaGetMic=navigator.mediaDevices.getUserMedia;navigator.mediaDevices.getUserMedia=()=>Promise.reject(new DOMException('denied','NotAllowedError'));}")
   page.locator('[name=consent]').check();page.get_by_role('button',name='Start',exact=True).click();page.locator('#live-resume').wait_for(state='visible')
   self.assertIn('Izin mikrofon ditolak',page.locator('#live-error').inner_text());self.assertEqual(page.evaluate('qa.mics'),0);self.assertFalse(any('/input/' in p for m,p in requests))
   page.evaluate('()=>{navigator.mediaDevices.getUserMedia=qaGetMic;}');page.locator('#live-resume').click();page.wait_for_function("!document.querySelector('#live-hold').disabled");fixture.record(page);fixture.stop_recording(page);page.wait_for_function('qa.mics===0');page.locator('#live-end').click();self.assertFalse(errors,errors)

 def test_realtime_microphone_denial_then_fresh_hold_and_stop(self):self.microphone_denial(True)
 def test_batch_microphone_denial_then_fresh_hold_and_stop(self):self.microphone_denial(False)

if __name__=='__main__':unittest.main()
