"""Explicit two-source validation, once only, using normal operating allowance."""
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import wave
from datetime import datetime, timezone, timedelta

RUN='gmlvalidate20261024'
ARM='KILAS_TRANSLATOR_VALIDATION_ARM'
HASHES={'id':'a76e081d3a1b128c8ee1b9f66befa21b30b15a6690579304c36330b85e5f4019',
        'en':'f04c50fd63dc716418edeb80f09153079a8718d107dd2055927d21528323eed9'}


def config():
    from . import live_gemini_smoke as smoke
    try:
        expiry=datetime.fromisoformat(os.environ['KILAS_TRANSLATOR_VALIDATION_EXPIRES_AT'].replace('Z','+00:00'))
        now=datetime.now(timezone.utc)
        if (os.environ.get(ARM)!=RUN or os.environ.get('RENDER_SERVICE_ID')!=smoke.SERVICE
                or expiry.tzinfo is None or not now<expiry<=now+timedelta(minutes=30)):
            return None
        return {'owner':int(os.environ['KILAS_LIVE_GEMINI_QA_OWNER_ID']),
                'email':os.environ['KILAS_LIVE_GEMINI_QA_OWNER_EMAIL'].strip().lower(),
                'expiry':expiry.isoformat(), 'remaining':False}
    except (KeyError,ValueError,TypeError):
        return None


def launch():
    if not config():return False
    try:
        subprocess.Popen([sys.executable,'-m','kilas_ai.live_gemini_validation_once'],close_fds=True)
        return True
    except OSError:
        return False


def fixture(language):
    path=Path(__file__).resolve().parents[1]/'tests/fixtures/gemini_live_synthetic_10s'/(language+'.wav')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=HASHES[language]:raise ValueError('fixture_changed')
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes())!=(1,2,16000,160000):raise ValueError('fixture_invalid')
        return wav.readframes(160000)


def passed(value):
    return bool(value.get('setup_complete') and not value.get('code')
                and value.get('input_ms')==10000 and value.get('output_ms',0)>0
                and value.get('settled_after_end') and value.get('post_end_output_access')=='blocked')


def run():
    configured=config()
    if not configured:return
    os.environ[ARM]='off'
    from . import live_gemini_smoke as smoke, live_gemini as native, live_gemini_budget as budget
    # Normal policy/admission, including all history; never override funding.
    allowance=budget.status(configured['owner'])
    if allowance.get('remaining_micro_usd',0)<2*allowance.get('reserve_micro_usd',250000):
        smoke.report({'run':RUN,'status':'insufficient_operating_allowance_no_calls'});return
    samples={language:fixture(language) for language in HASHES}
    smoke.RUN=RUN;smoke.passed=passed
    if not smoke.once(configured):
        smoke.report({'run':RUN,'status':'already_attempted_no_retry'});return
    native.INPUT_BYTES=10*32000;native.OUTPUT_BYTES=15*48000;budget.LEASE_MS=45000
    setup=native.setup
    def bounded_setup(target):
        value=setup(target);value['setup']['generationConfig']['maxOutputTokens']=512;return value
    native.setup=bounded_setup
    original_probe=smoke.ProbeSocket
    class LimitedSocket(original_probe):
        responses=0
        def recv(self):
            import json
            raw=super().recv()
            if raw not in ('',b''):
                content=json.loads(raw).get('serverContent',{})
                if content.get('generationComplete') is True or content.get('turnComplete') is True:
                    self.responses+=1
                    if self.responses>4:
                        self.socket.close()
                        raise ValueError('response_limit')
            return raw
    smoke.ProbeSocket=LimitedSocket
    # Each request is one fixed-target connection, max10s source/15s accepted
    # output,45s deadline,512 tokens/response. Existing ProbeSocket also aborts
    # at$0.09 observed token estimate; normal$0.25 reservation is retained.
    # Two such attempts fit$0.50 operating reserve, below separate$1 test cap.
    signal.alarm(110)
    outcomes=[]
    try:
        smoke.report({'run':RUN,'status':'started','max_attempts':2,'source_ms_each':10000,'output_ms_each':15000,'reservation_total_micro':500000})
        for source,target in (('id','en'),('en','id')):
            result=smoke.session(configured,source,target,samples[source])
            outcomes.append({'direction':source+'-'+target,'passed':passed(result)})
        smoke.report({'run':RUN,'status':'finished_no_retry','outcomes':outcomes})
    except Exception:
        smoke.report({'run':RUN,'status':'stopped_no_retry'})
    finally:
        signal.alarm(0)


if __name__=='__main__':run()
