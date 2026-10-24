"""Once-only canonical synthetic acceptance; normal allowance, no public hooks."""
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import time
import wave

RUN='gmlnatural20261024'
ARM='KILAS_TRANSLATOR_NATURAL_QA_ARM'
EXPIRY='KILAS_TRANSLATOR_NATURAL_QA_EXPIRES_AT'


def config():
    from . import live_gemini_smoke as smoke
    try:
        expiry=datetime.fromisoformat(os.environ[EXPIRY].replace('Z','+00:00'));now=datetime.now(timezone.utc)
        if (os.environ.get(ARM)!=RUN or os.environ.get('RENDER_SERVICE_ID')!=smoke.SERVICE
                or expiry.tzinfo is None or not now<expiry<=now+timedelta(minutes=30)):return None
        return {'owner':int(os.environ['KILAS_LIVE_GEMINI_QA_OWNER_ID']),
                'email':os.environ['KILAS_LIVE_GEMINI_QA_OWNER_EMAIL'].strip().lower(),
                'expiry':expiry.isoformat(),'remaining':False}
    except (KeyError,TypeError,ValueError):return None


def launch():
    if not config():return False
    try:subprocess.Popen([sys.executable,'-m','kilas_ai.live_gemini_natural_qa'],close_fds=True);return True
    except OSError:return False


def pcm_proof(case, raw):
    # Only invoked below for outputs of exact server-selected nonprivate sources.
    # Never accepts HTTP/user uploads or real microphone data. Bounded QA logs
    # transport the synthetic PCM to the offline browser replay harness.
    if case not in ('id-en','en-id','pair-id','pair-en') or not 0<len(raw)<=90*48000:return
    encoded=base64.b64encode(raw).decode('ascii');size=3000
    count=(len(encoded)+size-1)//size;digest=hashlib.sha256(raw).hexdigest()
    for index in range(count):
        print('KILAS_SYNTHETIC_PCM '+json.dumps({'run':RUN,'case':case,'index':index,'count':count,'sha256':digest,'data':encoded[index*size:(index+1)*size]},separators=(',',':')),flush=True)


def full_enough(result):
    return bool(result.get('setup_complete') and not result.get('code')
                and result.get('input_ms')==15000 and result.get('output_ms',0)>0
                and result.get('source_tail_word_confirmed') and result.get('target_tail_word_confirmed')
                and result.get('all_accepted_pcm_read') and result.get('post_end_output_access')=='blocked')


def paired(configured, samples, observations):
    from . import live_gemini as native, live_gemini_pair as pair, live_translator_store as sessions
    owner=configured['owner'];ident=sessions.create(owner,'id','en',pair.VOICE)
    key='live-'+hashlib.sha256((RUN+'pair').encode()).hexdigest()[:32]
    relay=None;result={'run':RUN,'case':'pair','physical_streams':2}
    try:
        relay=pair.start(owner,ident,key);started=time.monotonic()
        raw=samples['id']+bytes(32000)+samples['en']
        for index,offset in enumerate(range(0,len(raw),16000)):
            if relay.finished:break
            relay.accept(index,raw[offset:offset+16000]);time.sleep(max(0,started+(index+1)*.5-time.monotonic()))
        if not relay.finished:relay.finish_input(relay.expected)
        deadline=started+85
        while not relay.finished and time.monotonic()<deadline:time.sleep(.05)
        if not relay.finished:relay.stop(native.failure('gemini_deadline'))
        deadline=time.monotonic()+4
        while not relay.finished and time.monotonic()<deadline:time.sleep(.05)
        cursor=0;audio={'id':bytearray(),'en':bytearray()}
        while relay.finished and cursor<len(relay.frames):
            snapshot=relay.snapshot(cursor)
            for frame in snapshot['frames']:
                if frame['type']=='audio':audio[frame['stream_id']].extend(base64.b64decode(frame['pcm'],validate=True))
            cursor=snapshot['next_index']
        result.update(input_ms=relay.accepted/32,output_ms=relay.output_bytes/48,tail_confirmed=relay.tail_confirmed,
                      completion=relay.completion_kind,code=getattr(relay.error,'code',None),all_accepted_read=sum(map(len,audio.values()))==relay.output_bytes,
                      streams={target:{'source_text':stream.source_text,'translated_text':stream.target_text,'output_ms':stream.output_bytes/48,
                               'first_pcm_ms':None if stream.first_output_at is None else (stream.first_output_at-relay.started)*1000,
                               'setup_complete':observations[i].get('setup_complete',False)}
                               for i,(target,stream) in enumerate(relay.streams.items())})
        for target,pcm in audio.items():pcm_proof('pair-'+target,bytes(pcm))
        result['passed_mechanics']=bool(not result['code'] and result['all_accepted_read'] and all(stream['output_ms']>0 and stream['setup_complete'] for stream in result['streams'].values()))
    finally:
        sessions.end(owner,ident);pair.cancel(owner,ident)
        print('KILAS_NATURAL_QA '+json.dumps(result,separators=(',',':')),flush=True)
    return result


def run():
    configured=config()
    if not configured:return
    os.environ[ARM]='off'
    from . import live_gemini_smoke as smoke, live_gemini as native, live_gemini_budget as budget, live_gemini_capture as capture
    allowance=budget.status(configured['owner'],streams=2)
    if not allowance.get('available') or allowance.get('remaining_micro_usd',0)<1000000:
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'insufficient_allowance_no_calls'}),flush=True);return
    # Hash-verified original15-second natural-rate eSpeak sources, no synthesis.
    samples={language:smoke.fixture(language) for language in ('id','en')}
    smoke.RUN=RUN;smoke.passed=full_enough
    if not smoke.once(configured):
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'already_attempted_no_retry'}),flush=True);return
    original_connect=native.connect;original_setup=native.setup;probe=smoke.ProbeSocket
    observations=[]
    class TimedProbe(probe):
        def recv(self):
            raw=super().recv()
            if raw not in ('',b''):
                value=json.loads(raw);content=value.get('serverContent',{})
                fields=[name for name in ('generationComplete','turnComplete','interrupted') if content.get(name) is True]
                if 'usageMetadata' in value:fields.append('usageMetadata')
                if 'setupComplete' in value:fields.append('setupComplete')
                if fields:
                    events=self.observation.setdefault('timed_events',[])
                    if len(events)<256:events.append({'at_ms':round((time.monotonic()-self.observation.setdefault('event_origin',time.monotonic()))*1000,1),'events':fields})
            return raw
    smoke.ProbeSocket=TimedProbe
    def setup(target):
        value=original_setup(target);value['setup']['generationConfig']['maxOutputTokens']=2048;return value
    native.setup=setup;native.INPUT_BYTES=59*32000;native.OUTPUT_BYTES=45*48000
    signal.alarm(240)
    try:
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'started','max_cases':3,'max_physical_sockets':4,'reserved_total_micro':1000000}),flush=True)
        outcomes=[]
        for source,target in (('id','en'),('en','id')):
            result=smoke.session(configured,source,target,samples[source]);outcomes.append({'direction':source+'-'+target,'complete_captions':full_enough(result)})
            if result.get('fixture_capture_id'):
                artifact=capture.export(configured['owner'],result['fixture_capture_id'],'wav')
                with wave.open(io.BytesIO(artifact['data']),'rb') as wav:
                    if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,24000):raise ValueError('output_format')
                    pcm_proof(source+'-'+target,wav.readframes(wav.getnframes()))
        native.OUTPUT_BYTES=90*48000
        def observed_connect():
            observation={'usage_snapshots':[],'setup_complete':False};observations.append(observation)
            return TimedProbe(original_connect(),observation)
        native.connect=observed_connect
        result=paired(configured,samples,observations)
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'finished_no_retry','single_directions':outcomes,'pair_mechanics':result.get('passed_mechanics',False),'pair_events':observations},separators=(',',':')),flush=True)
    except Exception:
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'stopped_no_retry'}),flush=True)
    finally:signal.alarm(0)


if __name__=='__main__':run()
