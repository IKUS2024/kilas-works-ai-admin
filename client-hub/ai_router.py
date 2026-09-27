"""Configurable, bounded provider routing. No credentials or response bodies in errors.

The caller owns business scope and validates structured output. This boundary records
returned usage even when a response is later rejected. Capacity warnings never block replies.
"""
import os

import requests
import ai_usage


def _openai(system, messages, maximum, model):
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        return None, None, 'provider_not_configured'
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions',
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            json={'model': model, 'messages': [{'role': 'system', 'content': system}] + messages,
                  'max_completion_tokens': maximum, 'store': False}, timeout=45)
        response.raise_for_status()
        data = response.json()
        choice = data['choices'][0]
        text = choice['message'].get('content')
        usage = data.get('usage') or {}
        cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
        # Anthropic reports uncached input separately; OpenAI includes cached input in prompt.
        normalized = {'input_tokens': max(0, usage.get('prompt_tokens', 0)-cached),
                      'output_tokens': usage.get('completion_tokens', 0),
                      'cache_read_input_tokens': cached}
        if 'prompt_tokens' in usage and 'completion_tokens' in usage:
            ai_usage.record(model, {'usage': normalized, 'content': [{'text': text}]}, provider='openai')
        if not isinstance(text, str) or not text.strip():
            return None, None, 'empty_provider_response'
        return text, 'max_tokens' if choice.get('finish_reason') == 'length' else 'end_turn', None
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
        return None, None, 'provider_request_failed'


def complete(system, messages, maximum=1500, *, claude, legacy_model=None, strong=False):
    """One economical route, at most one configured escalation on failure.

    A caller may request strong=True after detecting low confidence; that request never
    falls back to the cheap route. Existing Claude-only installations remain supported.
    """
    default = 'openai' if os.environ.get('OPENAI_API_KEY', '').strip() else 'anthropic'
    fast = os.environ.get('KILAS_AI_FAST_PROVIDER', default).lower()
    high = os.environ.get('KILAS_AI_STRONG_PROVIDER', 'anthropic').lower()

    def invoke(provider, high_capacity):
        if provider == 'openai':
            model = os.environ.get('KILAS_AI_STRONG_MODEL' if high_capacity else 'KILAS_AI_FAST_MODEL',
                                   'gpt-4.1' if high_capacity else 'gpt-4.1-mini')
            return _openai(system, messages, maximum, model)
        if provider == 'anthropic':
            model = os.environ.get('KILAS_AI_STRONG_MODEL' if high_capacity else 'KILAS_AI_FAST_MODEL')
            if not model:
                model = (os.environ.get('CLIENT_HUB_MODEL', 'claude-sonnet-4-6') if high_capacity
                         else os.environ.get('CLIENT_HUB_SIMULATION_MODEL', 'claude-haiku-4-5-20251001'))
            return claude(system, messages, maximum, model=model)
        return None, None, 'invalid_provider_configuration'

    if strong:
        return invoke(high, True)
    result = invoke(fast, False)
    if result[2] or result[1] == 'max_tokens':
        return invoke(high, True)
    return result
