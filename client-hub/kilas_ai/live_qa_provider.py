"""Fixed OpenAI QA transports. Reservations are never refunded or auto-retried."""
import io
import json
import os
import wave
import requests
from . import live_qa_budget as budget


def _read(response):
    if response.status_code != 200:
        raise budget.BudgetError('qa_provider_failed')
    raw = bytearray()
    for part in response.iter_content(4096):
        raw.extend(part)
        if len(raw) > 65536:
            raise budget.BudgetError('qa_provider_failed')
    return json.loads(raw)


def _key():
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise budget.BudgetError('qa_provider_unavailable')
    return key


def transcribe(owner, token, sequence, pcm):
    # Transport boundary revalidates the approved <=10s input, independently of UI.
    if type(sequence) is not int or not 1 <= sequence <= 12 or len(pcm) > 512*1024:
        raise budget.BudgetError('qa_invalid_audio')
    try:
        with wave.open(io.BytesIO(pcm)) as audio:
            frames = audio.getnframes()
            samples = audio.readframes(frames)
            if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=16000 or not 0 < frames <= 160000 or len(samples) != frames*2:
                raise budget.BudgetError('qa_invalid_audio')
    except (wave.Error, EOFError):
        raise budget.BudgetError('qa_invalid_audio') from None
    # Send a canonical file containing only validated samples. Extra RIFF chunks
    # or trailing bytes cannot change the duration interpreted by the provider.
    normalized = io.BytesIO()
    with wave.open(normalized,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(samples)
    pcm = normalized.getvalue()
    key = _key()
    operation = str(sequence)
    budget.dispatch(owner, token, 'STT', operation, budget.STT_MODEL)
    success = False
    try:
        with requests.post('https://api.openai.com/v1/audio/transcriptions',
                           headers={'Authorization':'Bearer '+key},
                           files={'file':('tab-sample.wav',pcm,'audio/wav')},
                           data={'model':budget.STT_MODEL,'response_format':'json'},
                           timeout=(5,15),stream=True,allow_redirects=False) as response:
            data = _read(response)
            text = data['text'].strip()
            if not isinstance(text,str) or not 1 <= len(text) <= 4000:
                raise budget.BudgetError('qa_provider_failed')
            budget.assert_active(owner,token)
            success = True
            return text
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        raise budget.BudgetError('qa_provider_failed') from None
    finally:
        budget.finish(owner,token,'STT',operation,success)


def text(owner, token, kind, operation, instruction, content):
    if kind not in ('TRANSLATE','REPLY') or not isinstance(instruction,str) or not isinstance(content,str):
        raise budget.BudgetError('qa_invalid_text')
    payload={'model':budget.TEXT_MODEL,'messages':[{'role':'system','content':instruction},{'role':'user','content':content}],
             'max_completion_tokens':512,'reasoning_effort':'low','response_format':{'type':'json_object'},'store':False,'service_tier':'default'}
    # Entire serialized request <=16k bytes, conservatively <=20k input tokens
    # including the fixed two-message protocol. No images/audio/tools/fallbacks.
    if len(json.dumps(payload).encode('utf-8')) > budget.TEXT_MAX_BYTES:
        raise budget.BudgetError('qa_input_limit')
    key = _key()
    budget.dispatch(owner,token,kind,operation,budget.TEXT_MODEL)
    success = False
    try:
        with requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+key},
                           json=payload,timeout=(5,15),stream=True,allow_redirects=False) as response:
            data = _read(response)
            choice = data['choices'][0]
            if choice['finish_reason'] != 'stop' or data.get('service_tier') not in (None,'default'):
                raise budget.BudgetError('qa_provider_failed')
            result = json.loads(choice['message']['content'])['text'].strip()
            if not isinstance(result,str) or not 1 <= len(result) <= 3000:
                raise budget.BudgetError('qa_provider_failed')
            budget.assert_active(owner,token)
            success = True
            return result
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, IndexError):
        raise budget.BudgetError('qa_provider_failed') from None
    finally:
        budget.finish(owner,token,kind,operation,success)
