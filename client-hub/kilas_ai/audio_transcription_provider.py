"""VO-only STT. A persisted reservation capability gates the sole paid request."""
import hashlib
import io
import json
import os
import wave
import requests
from . import audio_transcription_budget as budget


def normalize(pcm):
    # Canonicalize locally; no user URL/file path/video is sent to the provider.
    try:
        if len(pcm)>20*1024*1024:raise ValueError()
        with wave.open(io.BytesIO(pcm)) as source:
            count=source.getnframes();samples=source.readframes(count)
            if source.getnchannels()!=1 or source.getsampwidth()!=2 or source.getframerate()!=16000 or not 0<count<=9600000 or len(samples)!=count*2:raise ValueError()
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
    success=False;evidence={};text=None
    try:
        with requests.post('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'].strip()},
                           files={'file':('recording.wav',raw,'audio/wav')},data={'model':budget.MODEL,'response_format':'json'},
                           timeout=(5,45),stream=True,allow_redirects=False) as response:
            if response.status_code!=200:raise budget.BudgetError('transcription_failed')
            body=bytearray()
            for part in response.iter_content(4096):
                body.extend(part)
                if len(body)>65536:raise budget.BudgetError('transcription_failed')
            parsed=json.loads(body);text=parsed.get('text')
            evidence=parsed.get('usage') if isinstance(parsed.get('usage'),dict) else {}
            if not isinstance(text,str) or not text.strip():raise budget.BudgetError('transcription_failed')
            text=text.strip()
            if len(text)>4000:raise budget.BudgetError('script_too_long',422)
            success=True
    except budget.BudgetError:
        raise
    except (requests.RequestException,ValueError,KeyError,TypeError,AttributeError):
        raise budget.BudgetError('transcription_failed') from None
    finally:
        committed=budget.finish(capability,success,evidence)
    return text if committed else None
