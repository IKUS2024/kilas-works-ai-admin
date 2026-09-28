"""Private Kilas AI streaming adapters. No Assist router or provider state is reused."""
import json
import os

import requests


class ProviderError(Exception):
    """Safe sentinel; never expose provider response bodies to the browser."""


SYSTEM = (
    "You are Kilas AI, a helpful general assistant. Reply naturally in the user's language. "
    "Separate known facts from uncertainty. Never claim to have searched the web or inspected "
    "an attachment unless its content is in this request."
)
PROVIDERS = ("openai", "anthropic")


def candidates(mode):
    mode = mode.upper()
    if mode not in ("FAST", "SMART", "EXPERT"):
        raise ValueError("invalid_mode")
    primary = os.environ.get("KILAS_AI_" + mode + "_PRIMARY", "openai").strip().lower()
    if primary not in PROVIDERS:
        raise ProviderError("invalid_provider_configuration")
    alternate = "anthropic" if primary == "openai" else "openai"
    for provider in (primary, alternate):
        model = os.environ.get("KILAS_AI_" + provider.upper() + "_" + mode + "_MODEL", "").strip()
        key = os.environ.get("OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY", "").strip()
        if model and key:
            yield provider, model, key


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


def _openai(model, key, messages):
    try:
        with requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "system", "content": SYSTEM}] + messages,
                  "max_completion_tokens": 2048, "stream": True,
                  "stream_options": {"include_usage": True}, "store": False},
            stream=True, timeout=(10, 90),
        ) as response:
            response.raise_for_status()
            for event in _events(response):
                usage = event.get("usage") or {}
                if usage:
                    yield {"type": "usage", "input_tokens": usage.get("prompt_tokens", 0),
                           "output_tokens": usage.get("completion_tokens", 0)}
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


def _anthropic(model, key, messages):
    try:
        with requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": model, "system": SYSTEM, "messages": messages,
                  "max_tokens": 2048, "stream": True},
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


def stream(mode, messages):
    """At most one fallback, only before any answer text has reached the caller."""
    attempted = False
    for provider, model, key in candidates(mode):
        attempted = True
        emitted = False
        finished = False
        try:
            source = _openai(model, key, messages) if provider == "openai" else _anthropic(model, key, messages)
            yield {"type": "provider", "provider": provider, "model": model}
            for event in source:
                if event["type"] == "delta":
                    emitted = True
                elif event["type"] == "finish":
                    finished = True
                yield event
            if emitted and finished:
                return
            if emitted:
                raise ProviderError("incomplete_provider_stream")
        except ProviderError:
            if emitted:
                raise
    raise ProviderError("providers_unavailable" if attempted else "providers_not_configured")
