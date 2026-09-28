"""Explicit provider-backed Kilas AI web and image operations."""
import base64
import io
import os
from urllib.parse import urlparse

import requests
from PIL import Image


class ToolUnavailable(Exception):
    pass


def _openai_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ToolUnavailable("OpenAI belum dikonfigurasi.")
    return key


def web_search(context):
    model = os.environ.get("KILAS_AI_OPENAI_WEB_MODEL", "").strip()
    if not model:
        raise ToolUnavailable("Web search belum tersedia.")
    key = _openai_key()
    prompt = "\n".join(message["role"] + ": " + (message["content"] if isinstance(message["content"], str)
                     else message["content"][0]["text"]) for message in context[-12:])[:18000]
    try:
        response = requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={"model": model, "instructions": "You are Kilas AI. Answer in the user's language. Use actual web search sources and cite them. Do not invent sources.",
                  "input": prompt, "tools": [{"type": "web_search"}], "tool_choice": "required", "store": False,
                  "max_output_tokens": 4096}, timeout=(10, 90))
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ToolUnavailable("Web search sedang tidak tersedia. Coba lagi.") from None
    searched = any(item.get("type") == "web_search_call" for item in data.get("output", []))
    parts, citations = [], []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for block in item.get("content", []):
            if block.get("type") != "output_text":
                continue
            parts.append(block.get("text") or "")
            for annotation in block.get("annotations", []):
                if annotation.get("type") != "url_citation":
                    continue
                url = annotation.get("url") or ""
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc or len(url) > 2048:
                    continue
                if url not in [item["url"] for item in citations]:
                    citations.append({"url": url, "title": (annotation.get("title") or parsed.netloc)[:160]})
    answer = "\n".join(parts).strip()
    if not searched or not answer or not citations:
        raise ToolUnavailable("Web search tidak mengembalikan sumber yang dapat ditampilkan.")
    usage = data.get("usage") or {}
    return {"text": answer[:30000], "citations": citations[:8], "model": model,
            "usage": {"input_tokens": usage.get("input_tokens", 0),
                      "output_tokens": usage.get("output_tokens", 0)}}


def image(prompt, source=None):
    model = os.environ.get("KILAS_AI_OPENAI_IMAGE_MODEL", "").strip()
    if not model:
        raise ToolUnavailable("Pembuatan gambar belum tersedia.")
    key = _openai_key()
    headers = {"Authorization": "Bearer " + key}
    try:
        if source is None:
            response = requests.post("https://api.openai.com/v1/images/generations",
                headers=headers, json={"model": model, "prompt": prompt[:4000], "size": "1024x1024", "n": 1},
                timeout=(10, 120))
        else:
            response = requests.post("https://api.openai.com/v1/images/edits", headers=headers,
                data={"model": model, "prompt": prompt[:4000], "size": "1024x1024", "n": "1"},
                files={"image": (source["filename"], bytes(source["content"]), source["mime_type"])},
                timeout=(10, 120))
        response.raise_for_status()
        data = response.json()
        encoded = data["data"][0]["b64_json"]
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise ValueError("image_size")
        with Image.open(io.BytesIO(raw)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(opened.format)
            if not mime or opened.width * opened.height > 20_000_000:
                raise ValueError("image_format")
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        raise ToolUnavailable("Gambar belum dapat dibuat. Coba lagi.") from None
    return {"raw": raw, "mime": mime, "model": model, "usage": data.get("usage") or {}}
