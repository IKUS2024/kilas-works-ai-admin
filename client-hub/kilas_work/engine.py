"""Responses API adapter for Work conversation and bounded automatic tool routing."""
import base64
import os
import re

import requests

from . import quota

API = "https://api.openai.com/v1/responses"
SYSTEM = ("You are Kilas Work, a capable work assistant. Answer in the user's language. "
          "Perform authorized low-risk work, distinguish verified facts from uncertainty, "
          "and never claim to have browsed, opened a file, or performed an action you did not do. "
          "Never reveal hidden reasoning. Before a purchase, destructive action, public publishing, "
          "sensitive external message, or consequential form submission, request explicit confirmation.")


class EngineError(Exception):
    pass


def route(text):
    """Conservative one-composer routing; ambiguous requests stay on economical Luna."""
    value = (text or "").lower()
    browser = bool(re.search(r"\b(?:buka|navigasi|klik|isi formulir|login|unggah ke|unduh dari|"
                             r"open|navigate|click|fill (?:in|out)|sign in|upload to|download from)\b", value)
                   and re.search(r"\b(?:website|situs|portal|browser|halaman|https?://|\.com\b|\.id\b)", value))
    image = bool(re.search(r"\b(?:buat|generate|edit|ubah|create)\b.{0,80}\b(?:gambar|image|foto|illustration)\b", value))
    pdf = bool(re.search(r"\b(?:buat|generate|export|ekspor|simpan|create)\b.{0,80}\bpdf\b", value))
    web = bool(re.search(r"\b(?:cari di web|search (?:the )?web|riset|research|berita terbaru|harga terbaru|"
                         r"informasi terkini|cek situs)\b", value))
    complex_task = bool(re.search(r"\b(?:arsitektur|architecture|debug (?:complex|kompleks)|multi.site|"
                                  r"beberapa situs|riset mendalam|deep research|rencana menyeluruh|"
                                  r"complex|kompleks)\b", value))
    operation = "BROWSER" if browser else "IMAGE" if image else "PDF" if pdf else "WEB" if web else "CHAT"
    model = "gpt-6-sol" if complex_task else "gpt-6-luna"
    return operation, model


def _content(text, files):
    blocks = [{"type": "input_text", "text": text[:12000]}]
    for item in files:
        if item.get("extracted_text"):
            blocks[0]["text"] += ("\n\nAttachment " + item["filename"] + ":\n" +
                                  item["extracted_text"][:12000])
        elif item["mime_type"].startswith("image/"):
            encoded = base64.b64encode(item["content"]).decode("ascii")
            blocks.append({"type": "input_image", "image_url": "data:" + item["mime_type"] +
                           ";base64," + encoded})
    return blocks


def respond(context, text, files, model, operation):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise EngineError("Kilas Work belum siap. Coba lagi nanti.")
    messages = [{"role": role, "content": content[:8000]} for role, content in context[-12:]
                if role in ("user", "assistant")]
    messages.append({"role": "user", "content": _content(text, files)})
    payload = {"model": model, "instructions": SYSTEM, "input": messages, "store": False,
               "max_output_tokens": 1800 if model == "gpt-6-luna" else 3000,
               "reasoning": {"effort": "medium" if model == "gpt-6-sol" else "none"}}
    if operation == "WEB":
        payload.update({"tools": [{"type": "web_search"}], "max_tool_calls": 2})
    try:
        response = requests.post(API, headers={"Authorization": "Bearer " + key,
                                               "Content-Type": "application/json"},
                                 json=payload, timeout=(10, 120))
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        raise EngineError("Kilas Work sedang tidak tersedia. Coba lagi.") from None
    parts, web_calls, citations = [], 0, []
    for item in data.get("output", []):
        if item.get("type") == "web_search_call":
            web_calls += 1
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    parts.append(block.get("text") or "")
                    for annotation in block.get("annotations") or []:
                        if annotation.get("type") == "url_citation":
                            citations.append({"url": annotation.get("url"),
                                              "title": annotation.get("title") or "Sumber"})
    answer = "\n".join(parts).strip()[:30000]
    if not answer:
        raise EngineError("Belum ada hasil yang bisa ditampilkan. Coba lagi.")
    usage = data.get("usage") or {}
    charged = quota.estimate_micro(model, usage.get("input_tokens", 0),
                                    usage.get("output_tokens", 0), web_calls=web_calls)
    return {"answer": answer, "usage": usage, "charged_micro": charged,
            "web_calls": web_calls, "citations": citations[:20]}
