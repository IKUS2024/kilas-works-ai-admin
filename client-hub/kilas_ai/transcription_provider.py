"""Bounded OpenAI file transcription; no retries, translation, TTS or key creation.

Verified 2026-10-10 against official audio/transcriptions reference:
https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create
"""
import json
import os
import requests

MODEL = 'gpt-4o-mini-transcribe'


class TranscriptionError(ValueError):
    pass


def budget_ready():
    # STT has no approved reservation/rate/settlement path in existing usage/audio billing.
    # Intentionally not environment-configurable. Enabling the feature cannot bypass this.
    return False


def configured():
    return bool(os.environ.get('OPENAI_API_KEY', '').strip())


def transcribe(pcm):
    if not budget_ready() or not configured():
        raise TranscriptionError('transcription_budget_unavailable')
    try:
        with requests.post('https://api.openai.com/v1/audio/transcriptions',
                           headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'].strip()},
                           files={'file': ('recording.wav', pcm, 'audio/wav')},
                           data={'model': MODEL, 'response_format': 'json'},
                           timeout=(5, 45), stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise TranscriptionError('transcription_failed')
            raw = bytearray()
            for chunk in response.iter_content(4096):
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise TranscriptionError('transcription_failed')
            result = json.loads(raw)
            text = result['text'].strip()
            if not isinstance(text, str) or not 1 <= len(text) <= 4000:
                raise TranscriptionError('transcription_failed')
            # Keep bounded usage evidence for a future approved STT settlement implementation.
            evidence = result.get('usage', {})
            if not isinstance(evidence, dict):
                evidence = {}
            return text, evidence
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        raise TranscriptionError('transcription_failed') from None
