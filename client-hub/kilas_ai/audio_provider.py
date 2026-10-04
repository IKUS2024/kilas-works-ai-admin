"""ElevenLabs legacy Dubbing v1 and TTS adapters; secrets never leave the server."""
import os
import time
import json
import logging
import re
import requests

BASE = 'https://api.elevenlabs.io/v1'
# Base tags verified against the Dubbing v1 language table, 2026-10-04.
LANGUAGES = {'id':'Indonesian','en':'English','ja':'Japanese','ko':'Korean','zh':'Chinese / Mandarin',
             'es':'Spanish','fr':'French','de':'German','th':'Thai','vi':'Vietnamese','ar':'Arabic',
             'pt':'Portuguese','it':'Italian','hi':'Hindi','ms':'Malay','nl':'Dutch','ru':'Russian','tr':'Turkish'}
_voices = None
_voices_at = 0


class ProviderError(ValueError):
    def __init__(self, code='provider_failed'):
        self.code = code
        super().__init__('Audio belum berhasil diproses. Saldo tidak dipotong. Coba lagi nanti.')


def configured():
    return bool(os.environ.get('ELEVENLABS_API_KEY', '').strip())


def request(method, path, *, binary=False, **kwargs):
    key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
    if not key:
        raise ProviderError('not_configured')
    try:
        # No automatic retries: POST timeout can mean the provider accepted a paid job.
        with requests.request(method, BASE+path, headers={'xi-api-key':key},
                              timeout=(5,55 if method=='POST' else 25), stream=True, **kwargs) as response:
            if response.status_code >= 400:
                # Read only a bounded error body. Never log headers, input, or raw JSON.
                body = bytearray()
                for chunk in response.iter_content(1024):
                    body.extend(chunk[:8192-len(body)])
                    if len(body) >= 8192:
                        break
                try:
                    detail = json.loads(body).get('detail', {})
                    if isinstance(detail, dict):
                        category = str(detail.get('status', detail.get('type', 'unknown')))
                        message = str(detail.get('message', ''))
                    else:
                        category, message = 'validation', str(detail)
                    safe = (category + ': ' + message).replace(key, '[redacted]')
                    safe = re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+|(?:sk_|Bearer\s+)[\w.-]+', '[redacted]', safe)
                    safe = re.sub(r'[\r\n\x00-\x1f]', ' ', safe)[:600]
                except (ValueError, AttributeError):
                    safe = 'unparseable_provider_error'
                logging.getLogger(__name__).warning('KILAS_AUDIO_PROVIDER status=%s detail=%s', response.status_code, safe)
                raise ProviderError('provider_http_'+str(response.status_code))
            deadline=time.monotonic()+60
            raw = bytearray()
            for chunk in response.iter_content(65536):
                if time.monotonic()>deadline:raise ProviderError('provider_timeout')
                raw.extend(chunk)
                if len(raw) > (20*1024*1024 if binary else 2*1024*1024):
                    raise ProviderError('provider_output_limit')
            if binary:
                return bytes(raw), response.headers.get('request-id','')[:120]
            return json.loads(raw)
    except (requests.RequestException, ValueError) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError('provider_transport') from None


def voices():
    """Stable curated choices drawn only from voices actually present in this account."""
    global _voices, _voices_at
    if not configured():
        return []
    if _voices is not None and time.monotonic()-_voices_at < 300:
        return _voices
    try:
        available = request('GET','/voices').get('voices',[])
        # Sort by persistent provider ID; identical account libraries retain identical choices.
        curated = []
        preferred = ['George','Brian','Charlie','Daniel','Rachel','Alice','Sarah','Matilda']
        def priority(v):
            name=str(v.get('name','')).split(' - ')[0]
            return (preferred.index(name) if name in preferred else len(preferred),str(v.get('voice_id','')))

        counts = {'male':0,'female':0}
        for v in sorted(available, key=priority):
            labels = v.get('labels') or {}; gender = labels.get('gender','').lower()
            ident = str(v.get('voice_id',''))
            if gender not in counts or counts[gender]>=4 or not ident.isalnum() or len(ident)>80:
                continue
            counts[gender]+=1
            curated.append({'id':ident,'name':str(v.get('name','Voice'))[:45],
                            'style':(gender.title()+' · '+str(labels.get('description') or labels.get('use_case') or 'Natural'))[:70]})
        _voices, _voices_at = curated, time.monotonic()
        return curated
    except ProviderError:
        return []


def dub(pcm, source, target, job_id):
    data = request('POST','/dubbing', files={'file':('audio.wav', pcm,'audio/wav')},
                   data={'source_lang':source,'target_lang':target,'name':'Kilas audio '+str(job_id),
                         'dubbing_studio':'false','mode':'automatic'})
    ident = str(data.get('dubbing_id',''))
    if not ident or not all(c.isalnum() or c in '_-' for c in ident) or len(ident)>120:
        raise ProviderError('invalid_provider_job')
    return ident


def dub_status(ident):
    data = request('GET','/dubbing/'+ident)
    return {'status':data.get('status'), 'source_language':data.get('source_language')}


def dub_result(ident, language):
    return request('GET','/dubbing/'+ident+'/audio/'+language, binary=True)[0]


def speech(script, voice, language):
    # Multilingual v2 is the current documented default. It detects script language;
    # language_code is explicitly unsupported by that model, so do not pretend to enforce it.
    return request('POST','/text-to-speech/'+voice, binary=True,
                   params={'output_format':'mp3_44100_128'},
                   json={'text':script,'model_id':'eleven_multilingual_v2'})
