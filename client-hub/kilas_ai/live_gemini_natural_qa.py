"""Once-only canonical synthetic acceptance; normal allowance, no public hooks."""
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

RUN='gmlcaption20261024'
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


def paired(configured, samples, observations, ident, source, observation_start):
    from . import live_gemini as native, live_gemini_pair as pair
    owner=configured['owner'];target='en' if source=='id' else 'id'
    key='live-'+hashlib.sha256((RUN+source).encode()).hexdigest()[:32]
    relay=None;result={'run':RUN,'case':source+'-'+target,'physical_streams':2}
    try:
        relay=pair.start(owner,ident,key);started=time.monotonic()
        raw=samples[source]
        for index,offset in enumerate(range(0,len(raw),16000)):
            if relay.finished:break
            relay.accept(index,raw[offset:offset+16000]);time.sleep(max(0,started+(index+1)*.5-time.monotonic()))
        input_finished_at=time.monotonic()
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
        result.update(input_ms=relay.accepted/32,output_ms=sum(map(len,audio.values()))/48,
                      provider_output_ms=relay.output_bytes/48,silent_output_ms=relay.silent_output_bytes/48,
                      tail_confirmed=relay.tail_confirmed,streamed_before_input_finished=relay.first_output_at is not None and relay.first_output_at<input_finished_at,
                      finish_to_settled_ms=round((time.monotonic()-input_finished_at)*1000,1),
                      completion=relay.completion_kind,code=getattr(relay.error,'code',None),all_accepted_read=sum(map(len,audio.values()))==sum(stream.output_bytes-stream.silent_output_bytes for stream in relay.streams.values() if stream.target_text.strip()),
                      streams={target:{'source_text':stream.source_text,'translated_text':stream.target_text,'output_ms':stream.output_bytes/48,
                               'first_pcm_ms':None if stream.first_output_at is None else (stream.first_output_at-relay.started)*1000,
                               'setup_complete':observations[observation_start+i].get('setup_complete',False)}
                               for i,(target,stream) in enumerate(relay.streams.items())})
        pcm_proof('pair-'+target,bytes(audio[target]))
        result['passed_mechanics']=bool(not result['code'] and result['all_accepted_read'] and audio[target] and not audio[source]
                                        and all(stream['setup_complete'] for stream in result['streams'].values()))
        result['complete_caption_tail']=bool(smoke_tail(result['streams'][target]['source_text'],source)
                                             and smoke_tail(result['streams'][target]['translated_text'],target))
    finally:
        print('KILAS_NATURAL_QA '+json.dumps(result,separators=(',',':')),flush=True)
    return result


def smoke_tail(text,language):
    from .live_gemini_smoke import tail_word
    return tail_word(text,language)


def run():
    configured=config()
    if not configured:return
    os.environ[ARM]='off'
    from . import live_gemini_smoke as smoke, live_gemini as native, live_gemini_budget as budget
    from . import live_gemini_pair as pair, live_translator_store as sessions
    allowance=budget.status(configured['owner'],streams=2)
    if not allowance.get('available') or allowance.get('remaining_micro_usd',0)<1000000:
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'insufficient_allowance_no_calls'}),flush=True);return
    # Hash-verified original15-second natural-rate eSpeak sources, no synthesis.
    samples={language:smoke.fixture(language) for language in ('id','en')}
    smoke.RUN=RUN
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
    native.setup=setup;native.INPUT_BYTES=59*32000;native.OUTPUT_BYTES=90*48000
    signal.alarm(180)
    ident=None
    try:
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'started','max_cases':2,'max_physical_sockets':4,'reserved_total_micro':1000000}),flush=True)
        outcomes=[]
        ident=sessions.create(configured['owner'],'id','en',pair.VOICE)
        def observed_connect():
            observation={'usage_snapshots':[],'setup_complete':False};observations.append(observation)
            return TimedProbe(original_connect(),observation)
        native.connect=observed_connect
        for source in ('id','en'):
            before=len(observations)
            result=paired(configured,samples,observations,ident,source,before)
            outcomes.append({'source':source,'passed_mechanics':result.get('passed_mechanics',False),'complete_caption_tail':result.get('complete_caption_tail',False)})
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'finished_no_retry','same_logical_session':True,'outcomes':outcomes,'pair_events':observations},separators=(',',':')),flush=True)
    except Exception:
        print('KILAS_NATURAL_QA '+json.dumps({'run':RUN,'status':'stopped_no_retry'}),flush=True)
    finally:
        signal.alarm(0)
        if ident is not None:
            sessions.end(configured['owner'],ident);pair.cancel(configured['owner'],ident)


if __name__=='__main__':run()
