"""ElevenLabs Dubbing v2 and TTS adapters; secrets never leave the server."""
import os
import time
import json
import logging
import re
import requests
from urllib.parse import urlsplit

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


def request(method, path, *, binary=False, private=False, **kwargs):
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
                    elif isinstance(detail, list):
                        category = 'validation'
                        message = '; '.join(str(v.get('loc', []))+': '+str(v.get('msg', '')) for v in detail if isinstance(v, dict))
                    else:
                        category, message = 'provider_error', str(detail)
                    safe = (category + ': ' + message).replace(key, '[redacted]')
                    safe = re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+|(?:sk_|Bearer\s+)[\w.-]+', '[redacted]', safe)
                    safe = re.sub(r'[\r\n\x00-\x1f]', ' ', safe)[:600]
                except (ValueError, AttributeError):
                    safe = 'unparseable_provider_error'
                logging.getLogger(__name__).warning('KILAS_AUDIO_PROVIDER status=%s detail=%s', response.status_code, 'personal_voice_request_failed' if private else safe)
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
            if not raw:return {}
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
            # Shared choices must never include another customer's cloned voice.
            if v.get('category') in ('cloned','professional') or (v.get('labels') or {}).get('kilas_personal')=='true':
                continue
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
    video = pcm[4:8] == b'ftyp'
    fields = {'target_language':target,'reference':'Kilas audio '+str(job_id),'model_id':'dubbing_v2'}
    if source != 'auto':fields['source_language'] = source
    data = request('POST','/dubbing/project',
                   files={'file':('source.mp4' if video else 'audio.wav',pcm,'video/mp4' if video else 'audio/wav')},
                   data=fields)
    ident = str(data.get('project_id',''))
    if not re.fullmatch(r'proj_[A-Za-z0-9_-]{1,110}',ident):
        raise ProviderError('invalid_provider_job')
    logging.getLogger(__name__).info('KILAS_AUDIO_DUB model=dubbing_v2 job=%s',job_id)
    return ident


def dub_status(ident, language=None):
    if ident.startswith('proj_'):
        project = request('GET','/dubbing/project/'+ident)
        if any(v.get('type')=='voices_not_permitted' for v in project.get('warnings') or []):
            raise ProviderError('voice_preservation_unavailable')
        if project.get('status') != 'ready':return {'status':project.get('status')}
        targets = request('GET','/dubbing/project/'+ident+'/language').get('languages',[])
        target = next((v for v in targets if v.get('target_language')==language),None)
        if not target:return {'status':'queued'}
        if any(v.get('type')=='voices_not_permitted' for v in target.get('warnings') or []):
            raise ProviderError('voice_preservation_unavailable')
        detected = project.get('source_language')
        if not detected and target.get('status')=='completed':
            detected = request('GET','/dubbing/project/'+ident+'/transcript').get('language')
        return {'status':target.get('status'),'source_language':detected,'outputs':target.get('outputs') or {}}
    # Read-only compatibility for jobs already submitted before the v2 release.
    data = request('GET','/dubbing/'+ident)
    return {'status':data.get('status'), 'source_language':data.get('source_language')}


def dub_result(ident, language, outputs=None):
    if ident.startswith('proj_'):
        url = (outputs or {}).get('lossless_audio','')
        parsed = urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='storage.googleapis.com' or parsed.username or parsed.port not in (None,443):
            raise ProviderError('invalid_provider_output')
        try:
            # Signed output only: no API key, no redirects, bounded media bytes.
            with requests.get(url,stream=True,timeout=(5,55),allow_redirects=False) as response:
                if response.status_code!=200:raise ProviderError('provider_output_unavailable')
                raw=bytearray();deadline=time.monotonic()+60
                for chunk in response.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw)>100*1024*1024 or time.monotonic()>deadline:raise ProviderError('provider_output_limit')
                return bytes(raw)
        except requests.RequestException:raise ProviderError('provider_transport') from None
    return request('GET','/dubbing/'+ident+'/audio/'+language, binary=True)[0]


def speech(script, voice, language, *, personal=False):
    # Multilingual v2 is the current documented default. It detects script language;
    # language_code is explicitly unsupported by that model, so do not pretend to enforce it.
    payload={'text':script,'model_id':'eleven_v4' if personal else 'eleven_multilingual_v2'}
    if personal:
        # Documented voice defaults; v4 supports Stability/Similarity, not style/speaker boost.
        payload['voice_settings']={'stability':0.5,'similarity_boost':0.75}
        if language!='auto':payload['language_code']=language
        logging.getLogger(__name__).info('KILAS_AUDIO_TTS model=eleven_v4 personal=true language=%s',language)
    return request('POST','/text-to-speech/'+voice, binary=True,
                   params={'output_format':'mp3_44100_128'},
                   json=payload)


def clone_voice(pcm):
    data=request('POST','/voices/add',private=True,
                 files=[('files',('voice.wav',pcm,'audio/wav'))],
                 data={'name':'Kilas personal voice','labels':json.dumps({'kilas_personal':'true'}),'remove_background_noise':'false'})
    ident=str(data.get('voice_id',''))
    if not re.fullmatch(r'[A-Za-z0-9]{1,80}',ident):raise ProviderError('invalid_voice')
    if data.get('requires_verification'):
        delete_voice(ident)
        raise ProviderError('voice_verification_required')
    return ident


def delete_voice(ident):
    try:request('DELETE','/voices/'+ident,private=True)
    except ProviderError:logging.getLogger(__name__).warning('KILAS_AUDIO personal_voice_cleanup_failed')
