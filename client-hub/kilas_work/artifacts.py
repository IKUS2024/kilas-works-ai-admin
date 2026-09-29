"""Bounded downloadable source/text artifact from an explicit Work file request."""
import re

MIMES = {"txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
         "json": "application/json", "py": "text/x-python", "js": "text/javascript",
         "html": "text/html", "css": "text/css"}


def from_answer(request_text, answer):
    if not re.search(r"\b(?:buat|simpan|export|ekspor|create|save|generate)\b.{0,80}\b(?:file|berkas)\b",
                     request_text or "", re.I):
        return None
    match = re.search(r"\b([A-Za-z0-9][A-Za-z0-9_-]{0,79}\.(?:txt|md|csv|json|py|js|html|css))\b",
                      request_text or "", re.I)
    if not match:
        return None
    filename = match.group(1)
    extension = filename.rsplit(".", 1)[1].lower()
    fenced = re.search(r"```(?:[A-Za-z0-9_-]+)?\s*\n([\s\S]*?)\n```", answer or "")
    content = (fenced.group(1) if fenced else answer or "").strip()
    raw = content.encode("utf-8")
    if not raw or len(raw) > 200000:
        return None
    return {"filename": filename, "mime_type": MIMES[extension], "content": raw,
            "extracted_text": content[:12000]}
