"""VO-only STT. A persisted reservation capability gates the sole paid request."""
import hashlib
import io
import json
import os
import wave
from time import monotonic
import requests
from . import audio_transcription_budget as budget
from . import live_translator_transport as transport


def require_subscription_credit():
    """Read the existing Voice Over account; never purchase or enable overage."""
    try:
        response=transport.get('https://api.elevenlabs.io/v1/user/subscription',
                              headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},
                              timeout=(5,10),allow_redirects=False)
        if response.status_code!=200:raise budget.BudgetError('provider_credit_check_failed')
        subscription=response.json()
        if (subscription.get('tier')!='creator' or subscription.get('status')!='active'
                or subscription.get('max_credit_limit_extension')!=0
                or subscription.get('allowed_to_extend_character_limit') is not False
                or subscription.get('can_extend_character_limit') is not False):
            raise budget.BudgetError('provider_billing_unverified')
        used,limit=subscription.get('character_count'),subscription.get('character_limit')
        if type(used) is not int or type(limit) is not int or used<0 or limit<0:
            raise budget.BudgetError('provider_credit_check_failed')
        if used>=limit:raise budget.BudgetError('provider_credit_exhausted',402)
    except budget.BudgetError:
        raise
    except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError):
        raise budget.BudgetError('provider_credit_check_failed') from None


def normalize(pcm):
    # Canonicalize locally; no user URL/file path/video is sent to the provider.
    try:
        if len(pcm)>20*1024*1024:raise ValueError()
        with wave.open(io.BytesIO(pcm)) as source:
            count=source.getnframes();samples=source.readframes(count)
            if source.getnchannels()!=1 or source.getsampwidth()!=2 or source.getframerate()!=16000 or not 1600<=count<=9600000 or len(samples)!=count*2:raise ValueError()
        ms=(count*1000+15999)//16000
    except (ValueError,wave.Error,EOFError):raise budget.BudgetError('invalid_audio',400) from None
    canonical=io.BytesIO()
    with wave.open(canonical,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(samples)
    raw=canonical.getvalue()
    return raw,ms


def transcribe(pcm,capability):
    raw,ms=normalize(pcm)
    budget.dispatch(capability,hashlib.sha256(raw).hexdigest(),ms)
    success=False;text=None
    try:
        deadline=monotonic()+60
        with transport.post('https://api.elevenlabs.io/v1/speech-to-text',headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},
                           files={'file':('recording.wav',raw,'audio/wav')},params={'enable_logging':'true'},
                           data={'model_id':budget.MODEL,'file_format':'other','timestamps_granularity':'none',
                                 'tag_audio_events':'false','diarize':'false','webhook':'false',
                                 'use_multi_channel':'false','use_speaker_library':'false','detect_speaker_roles':'false','no_verbatim':'false'},
                           timeout=(5,45),stream=True,allow_redirects=False) as response:
            if response.status_code!=200:
                # The provider is authoritative if remaining credits cannot cover
                # this recording, including a race with another Voice Over request.
                if response.status_code in (401,402,403):
                    error_body=bytearray()
                    for part in response.iter_content(4096):
                        error_body.extend(part)
                        if monotonic()>deadline or len(error_body)>65536:raise budget.BudgetError('transcription_failed')
                    try:
                        detail=json.loads(error_body).get('detail',{})
                        reason=detail.get('status') if isinstance(detail,dict) else None
                    except (ValueError,AttributeError):reason=None
                    if response.status_code==402 or reason in ('quota_exceeded','insufficient_credits','insufficient_credit_balance','insufficient_balance'):
                        raise budget.BudgetError('provider_credit_exhausted',402)
                raise budget.BudgetError('transcription_failed')
            body=bytearray()
            for part in response.iter_content(4096):
                if monotonic()>deadline:raise budget.BudgetError('transcription_failed')
                body.extend(part)
                if len(body)>65536:raise budget.BudgetError('transcription_failed')
            parsed=json.loads(body);text=parsed.get('text')
            if not isinstance(text,str) or not text.strip():raise budget.BudgetError('transcription_failed')
            text=text.strip()
            if len(text)>4000:raise budget.BudgetError('script_too_long',422)
            success=True
    except budget.BudgetError:
        raise
    except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError):
        raise budget.BudgetError('transcription_failed') from None
    finally:
        committed=budget.finish(capability,success)
    return text if committed else None
