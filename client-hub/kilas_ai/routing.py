"""Conservative, deterministic routing for the customer-facing composer."""
import re


def mode_for(content, attachments=()):
    text = content.lower()
    difficult = (
        r"\b(?:debug|refactor|optimasi|architecture|arsitektur|implementasi|analisis mendalam|"
        r"rencana strategis|multi.?step|langkah demi langkah yang kompleks)\b",
        r"\b(?:bandingkan|compare|perbandingan)\b.*\b(?:dua|2|beberapa|multiple)\b.*\b(?:dokumen|file|laporan)\b",
    )
    documents = sum(bool(item.get("extracted_text")) for item in attachments)
    if documents >= 2 and re.search(r"\b(?:bandingkan|compare|analisis|sintesis)\b", text):
        return "SMART"
    return "SMART" if any(re.search(pattern, text) for pattern in difficult) else "FAST"


def tool_for(content, attachments=(), *, search=False, pdf_request=False):
    text = content.lower()
    if search:
        return "WEB"
    if pdf_request:
        return "PDF"
    if any(item.get("mime_type", "").startswith("image/") for item in attachments) and re.search(
            r"\b(?:edit|ubah|hapus|ganti|retouch|change)\b", text):
        return "IMAGE_EDIT"
    if re.search(r"\b(?:edit|ubah|hapus|ganti|remove|retouch|change)\b.{0,70}\b(?:foto|gambar|image|background|latar|color|warna)\b|\b(?:foto|gambar|image)\b.{0,35}\b(?:edit|ubah|hapus|ganti)\b", text):
        return "IMAGE_EDIT"
    if re.search(r"\b(?:buat|bikin|generate|ciptakan|create|draw|lukis)\b.{0,45}\b(?:gambar|foto|ilustrasi|image|poster)\b|\b(?:gambarkan|draw|lukis)\b\s+\S+", text):
        return "IMAGE_GENERATE"
    return "CHAT"
