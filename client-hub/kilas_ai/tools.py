"""Explicit provider-backed Kilas AI web and image operations."""
import base64
import io
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from PIL import Image

from . import response_style


class ToolUnavailable(Exception):
    pass


def _openai_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ToolUnavailable("OpenAI belum dikonfigurasi.")
    return key


SEARCH_CALL_CAPS = {"FREE": 1, "PLUS": 3, "PRO": 4, "MAX": 5}


def _search_text(context):
    recent = context[-8:]
    lines = []
    for index, message in enumerate(recent):
        content = message["content"] if isinstance(message["content"], str) else message["content"][0]["text"]
        limit = 6000 if index == len(recent) - 1 else 750
        if len(content) > limit:
            content = content[:limit // 2] + "\n[…ringkasan teks terpotong…]\n" + content[-limit // 2:]
        lines.append(message["role"] + ": " + content)
    return "\n".join(lines)[-12000:]


def research_requested(context):
    latest = context[-1]["content"] if context else ""
    text = (latest if isinstance(latest, str) else latest[0]["text"]).split(
        "\n\nTeks berikut berhasil diekstrak", 1)[0].lower()
    return bool(re.search(
        r"\b(?:riset|research|analisis lengkap|market research|pro dan kontra|berbagai sumber|"
        r"beberapa sumber|multi.sumber|verifikasi klaim|bandingkan kompetitor|"
        r"bandingkan (?:beberapa|tiga|3|dua|2)|sumber resmi dan sumber independen|"
        r"harga.{0,50}fitur.{0,50}(?:target|positioning)|apa yang berubah dan kenapa|"
        r"bandingkan\s+\S.{0,80}\s+dan\s+\S|compare\s+\S.{0,80}\s+(?:and|vs)\s+\S)\b", text))


def _source_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(url) > 2048:
        return None
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query)
                       if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")])
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", query, ""))


def _web_response(data):
    searched = sum(item.get("type") == "web_search_call" for item in data.get("output", []))
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
                url = _source_url(annotation.get("url"))
                if url and url not in [item["url"] for item in citations]:
                    citations.append({"url": url, "title": (annotation.get("title") or urlparse(url).netloc)[:160]})
    return searched, "\n".join(parts).strip(), citations


def _request(payload, timeout=90):
    try:
        response = requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + _openai_key(), "Content-Type": "application/json"},
            json=payload, timeout=(10, timeout))
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        raise ToolUnavailable("Web search sedang tidak tersedia. Coba lagi.") from None


def _enough_evidence(text, citations):
    domains = {urlparse(item["url"]).netloc.removeprefix("www.") for item in citations}
    return len(text) >= 300 and len(citations) >= 3 and len(domains) >= 2


def _synthesize_research(chunks, citations):
    from .model_policy import luna_model
    model = luna_model()
    sources = "\n".join(f"[{index}] {item['title']} — {item['url']}"
                        for index, item in enumerate(citations, 1))
    evidence = "\n\n".join(chunks)[:18000]
    payload = {"model": model, "instructions": (
        response_style.research_synthesis_instructions()),
        "input": "Verified search findings:\n" + evidence + "\n\nActual cited sources:\n" + sources,
        "store": False, "reasoning": {"effort": "medium"}, "max_output_tokens": 2300}
    data = _request(payload)
    _, answer, _ = _web_response(data)
    indices = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
    if not indices or any(index < 1 or index > len(citations) for index in indices):
        raise ToolUnavailable("research_synthesis_uncited")
    allowed = {item["url"] for item in citations}
    if any(_source_url(value.rstrip(".,)")) not in allowed
           for value in re.findall(r"https?://[^\s)]+", answer)):
        raise ToolUnavailable("research_synthesis_uncited")
    return answer, model, data.get("usage") or {}


def web_search_steps(context, mode="FAST", plan="FREE", max_calls=None, request_timeout=None):
    model = os.environ.get("KILAS_AI_OPENAI_WEB_MODEL", "").strip()
    if not model:
        raise ToolUnavailable("Web search belum tersedia.")
    complex_request = research_requested(context)
    limit = min(SEARCH_CALL_CAPS.get(plan, 1), max(1, int(max_calls or SEARCH_CALL_CAPS.get(plan, 1)))) if complex_request else 1
    prompt = _search_text(context)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    angles = ("Find the most relevant primary or official evidence for the request.",
              "Find independent evidence or missing comparison dimensions; avoid sources already found.",
              "Check conflicting claims, dates, and any still-missing comparison dimensions.",
              "Verify remaining gaps using current reputable sources.",
              "Cross-check any unresolved high-impact claim against a separate credible source.")
    parts, citations, calls = [], [], 0
    cost_components = []
    input_tokens = output_tokens = 0
    for index in range(limit):
        previous = "\n".join(item["url"] for item in citations[-8:])
        query = prompt if index == 0 else (prompt + "\n\nPrior sources (avoid duplicates):\n" + previous +
                                            "\nResearch gap: " + angles[index])
        payload = {"model": model, "instructions": response_style.search_instructions(
            today, angles[index] if complex_request else "Answer the user's question directly."),
            "input": query, "tools": [{"type": "web_search"}], "tool_choice": "required", "store": False,
            "reasoning": {"effort": "medium" if complex_request else "low"}, "max_tool_calls": 1, "max_output_tokens": 2048}
        calls += 1
        try:
            data = _request(payload) if request_timeout is None else _request(payload, timeout=request_timeout)
        except ToolUnavailable:
            if not complex_request or not parts:
                if index + 1 < limit:
                    continue
                break
            continue
        searched, answer, found = _web_response(data)
        used = data.get("usage") or {}
        cost_components.append({'model':model,'operation':'WEB_SEARCH',
            'input_tokens':used.get('input_tokens',0),'output_tokens':used.get('output_tokens',0),
            'cached_input_tokens':(used.get('input_tokens_details') or {}).get('cached_tokens',0)})
        input_tokens += int(used.get("input_tokens") or 0)
        output_tokens += int(used.get("output_tokens") or 0)
        if not searched or not answer or not found:
            if not complex_request:
                break
            continue
        new_sources = [item for item in found if item["url"] not in {source["url"] for source in citations}]
        if not new_sources and citations:
            break
        citations.extend(new_sources)
        parts.append(answer)
        if not complex_request or _enough_evidence("\n".join(parts), citations):
            break
        if index + 1 < limit:
            yield {"activity": "Membandingkan informasi…"}
    if not parts or not citations:
        raise ToolUnavailable("Web search tidak mengembalikan sumber yang dapat ditampilkan.")
    answer = "\n\n".join(parts)
    if complex_request and len(parts) > 1 and len(citations) > 1:
        yield {"activity": "Menyusun hasil riset…"}
        try:
            answer, model, used = _synthesize_research(parts, citations[:8])
            cost_components.append({'model':model,'operation':'CHAT',
                'input_tokens':used.get('input_tokens',0),'output_tokens':used.get('output_tokens',0),
                'cached_input_tokens':(used.get('input_tokens_details') or {}).get('cached_tokens',0)})
            input_tokens += int(used.get("input_tokens") or 0)
            output_tokens += int(used.get("output_tokens") or 0)
        except ToolUnavailable:
            pass  # Keep only the source-backed search findings when synthesis fails.
    yield {"result": {"text": answer[:30000], "citations": citations[:8], "model": model,
            "search_calls": calls, "research": complex_request,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "web_search_calls": calls,
                      'cost_components':cost_components}}}


def web_search(context, mode="FAST", plan="FREE", max_calls=None, request_timeout=None):
    return next(event["result"] for event in web_search_steps(context, mode, plan, max_calls, request_timeout)
                if "result" in event)


def finalize_scheduled_search(instruction, search_text, citations):
    """Rewrite completed scheduled Search economically using only verified findings."""
    from .model_policy import luna_model
    model = luna_model()
    safe_sources = [item for item in (citations or [])[:8] if str(item.get("url") or "").startswith("https://")]
    if not safe_sources or not str(search_text or "").strip():
        raise ToolUnavailable("Hasil Search belum cukup untuk disusun.")
    sources = "\n".join(
        f"[{index}] {str(item.get('title') or 'Sumber')[:160]} — {str(item.get('url') or '')[:1000]}"
        for index, item in enumerate(safe_sources, 1)
    )
    payload = {
        "model": model,
        "instructions": (
            "You are Kilas AI preparing the final result of a scheduled Search task. "
            + response_style.BASE_STYLE +
            " Use only the supplied verified search findings and source list. Do not invent facts, URLs, "
            "events, dates, or claims. Preserve important uncertainty and recency. Answer the user's original "
            "instruction directly in their language. Where useful, cite supplied sources with [number]. "
            "Do not claim to have emailed, messaged, or delivered the result outside Kilas AI."
        ),
        "input": (
            "Original scheduled task:\n" + str(instruction or "")[:1200] +
            "\n\nVerified search findings:\n" + str(search_text or "")[:16000] +
            "\n\nSources:\n" + sources
        ),
        "store": False,
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 1800,
    }
    data = _request(payload)
    _, answer, _ = _web_response(data)
    if not answer:
        raise ToolUnavailable("Hasil final belum tersedia. Coba lagi.")
    return {"text": answer[:12000], "model": model, "usage": data.get("usage") or {}}


def image(prompt, source=None, *, request_timeout=120):
    model = os.environ.get("KILAS_AI_OPENAI_IMAGE_MODEL", "").strip()
    if not model:
        raise ToolUnavailable("Pembuatan gambar belum tersedia.")
    key = _openai_key()
    headers = {"Authorization": "Bearer " + key}
    try:
        if source is None:
            response = requests.post("https://api.openai.com/v1/images/generations",
                headers=headers, json={"model": model, "prompt": prompt[:4000], "size": "1024x1024", "quality": "low", "n": 1},
                timeout=(10, request_timeout))
        else:
            response = requests.post("https://api.openai.com/v1/images/edits", headers=headers,
                data={"model": model, "prompt": prompt[:4000], "size": "1024x1024", "quality": "low", "n": "1"},
                files={"image": (source["filename"], bytes(source["content"]), source["mime_type"])},
                timeout=(10, request_timeout))
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
