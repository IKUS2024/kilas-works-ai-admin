"""Private Kilas AI streaming adapters. No Assist router or provider state is reused."""
import json
import os

import requests

from . import response_style, model_policy


class ProviderError(Exception):
    """Safe sentinel; never expose provider response bodies to the browser."""


SYSTEM = response_style.CHAT_SYSTEM
PROVIDERS = ("openai", "anthropic")
MODEL_TIERS = {mode: {"openai": model_policy.LUNA} for mode in ("FAST","SMART","EXPERT")}
OUTPUT_LIMITS = {"FAST": 1000, "SMART": 1500, "EXPERT": 1500}
EFFORT = {"FAST": "low", "SMART": "medium", "EXPERT": "medium"}


def candidates(mode, messages=None):
    if mode.upper() not in MODEL_TIERS:
        raise ValueError("invalid_mode")
    try:
        model = model_policy.chat_profile(messages)['model'] if messages is not None else model_policy.luna_model()
    except ValueError:
        raise ProviderError("invalid_provider_configuration") from None
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    # Legacy SMART/EXPERT provider configuration cannot promote ordinary Chat or its fallback.
    if key:
        yield "openai", model, key


def _events(response):
    """Parse provider SSE payloads; both APIs use data lines with JSON objects."""
    parts = []
    for raw in response.iter_lines(decode_unicode=True):
        line = raw.decode("utf-8") if isinstance(raw, bytes) else (raw or "")
        if line.startswith("data:"):
            parts.append(line[5:].strip())
        elif not line and parts:
            payload = "\n".join(parts)
            parts = []
            if payload == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except (ValueError, TypeError):
                raise ProviderError("bad_provider_stream") from None
    if parts:
        try:
            yield json.loads("\n".join(parts))
        except (ValueError, TypeError):
            raise ProviderError("bad_provider_stream") from None


def _openai(model, key, messages, mode, system=SYSTEM):
    profile = model_policy.chat_profile(messages)
    try:
        with requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "system", "content": system}] + messages,
                  "max_completion_tokens": profile["output_tokens"], "reasoning_effort": profile["effort"], "stream": True,
                  "stream_options": {"include_usage": True}, "store": False},
            stream=True, timeout=(10, 90),
        ) as response:
            response.raise_for_status()
            for event in _events(response):
                usage = event.get("usage") or {}
                if usage:
                    yield {"type": "usage", "input_tokens": usage.get("prompt_tokens", 0),
                           "output_tokens": usage.get("completion_tokens", 0),
                           "cached_input_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens",0)}
                choices = event.get("choices") or []
                if choices:
                    delta = (choices[0].get("delta") or {}).get("content")
                    if isinstance(delta, str) and delta:
                        yield {"type": "delta", "text": delta}
                    reason = choices[0].get("finish_reason")
                    if reason:
                        yield {"type": "finish", "reason": reason}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise ProviderError("openai_unavailable") from None


def _anthropic(model, key, messages, mode, system=SYSTEM):
    try:
        converted = []
        for message in messages:
            content = message["content"]
            if isinstance(content, list):
                blocks = []
                for block in content:
                    if block["type"] == "image_url":
                        data_url = block["image_url"]["url"]
                        header, payload = data_url.split(";base64,", 1)
                        blocks.append({"type": "image", "source": {"type": "base64",
                                       "media_type": header[5:], "data": payload}})
                    else:
                        blocks.append(block)
                content = blocks
            converted.append({"role": message["role"], "content": content})
        with requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": model, "system": system, "messages": converted,
                  "max_tokens": OUTPUT_LIMITS[mode], "thinking": {"type": "adaptive"},
                  "output_config": {"effort": EFFORT[mode]}, "stream": True},
            stream=True, timeout=(10, 90),
        ) as response:
            response.raise_for_status()
            for event in _events(response):
                kind = event.get("type")
                if kind == "error":
                    raise ProviderError("anthropic_stream_error")
                if kind == "message_start":
                    usage = (event.get("message") or {}).get("usage") or {}
                    yield {"type": "usage", "input_tokens": usage.get("input_tokens", 0)}
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield {"type": "delta", "text": delta["text"]}
                elif kind == "message_delta":
                    usage = event.get("usage") or {}
                    yield {"type": "usage", "output_tokens": usage.get("output_tokens", 0)}
                    reason = (event.get("delta") or {}).get("stop_reason")
                    if reason:
                        yield {"type": "finish", "reason": reason}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise ProviderError("anthropic_unavailable") from None


def stream(mode, messages, system=None):
    """One server-selected candidate; only the separately metered guard may repair."""
    from .capabilities import instruction
    system=(SYSTEM if system is None else system)+'\n'+instruction()+'\n'+model_policy.intelligence.playbook(model_policy.chat_profile(messages))
    attempted = False
    for provider, model, key in candidates(mode,messages):
        attempted = True
        emitted = False
        finished = False
        try:
            adapter = _openai if provider == "openai" else _anthropic
            source = adapter(model, key, messages, mode, system)
            yield {"type": "provider", "provider": provider, "model": model}
            for event in source:
                if event["type"] == "delta":
                    emitted = True
                elif event["type"] == "finish":
                    finished = True
                yield event
            if finished:
                return
            if emitted:
                raise ProviderError("incomplete_provider_stream")
        except ProviderError:
            if emitted:
                raise
    raise ProviderError("providers_unavailable" if attempted else "providers_not_configured")
