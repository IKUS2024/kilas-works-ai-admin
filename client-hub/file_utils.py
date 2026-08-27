"""Business file upload validation + best-effort text extraction (section 11).

Validation is defense-in-depth, not just extension checking:
  - extension must be in the allow-list
  - size must be under MAX_UPLOAD_BYTES
  - the file's ACTUAL bytes are checked to match the claimed type (PDF magic number, or a real
    decodable image for PNG/JPEG via Pillow) — a renamed .exe with a .pdf extension is rejected.
  - the original filename is sanitized before ever being shown back in the UI (no path traversal,
    no HTML injection via filename).
  - uploaded files are NEVER executed, imported, or eval'd — they are stored as opaque bytes in
    the database and, for PDF/TXT, best-effort text-extracted for the AI to read. Extracted
    pricing/knowledge is NEVER trusted blindly (see ai_onboarding.py — it always sets
    needs_review rather than silently accepting extracted numbers, per section 11's instruction).
"""
import io
import os
import re

from PIL import Image
import pypdf

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per file, generous for a katalog PDF/menu photo
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "txt"}


class UploadRejected(Exception):
    pass


def sanitize_filename(filename):
    base = os.path.basename(filename or "upload")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "upload"
    return base[:120]


def _extension_of(filename):
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def validate_and_extract(filename, content_bytes, claimed_mime_type):
    """Returns (safe_filename, mime_type, extracted_text_or_None). Raises UploadRejected with a
    user-safe message on any validation failure."""
    if not content_bytes:
        raise UploadRejected("File kosong.")
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"File terlalu besar (maks {MAX_UPLOAD_BYTES // (1024*1024)}MB).")

    safe_name = sanitize_filename(filename)
    ext = _extension_of(safe_name)
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected("Tipe file tidak didukung. Gunakan PDF, PNG, JPG, atau TXT.")

    if ext == "pdf":
        if not content_bytes.startswith(b"%PDF"):
            raise UploadRejected("File tidak terbaca sebagai PDF yang valid.")
        extracted = _extract_pdf_text(content_bytes)
        return safe_name, "application/pdf", extracted

    if ext in ("png", "jpg", "jpeg"):
        try:
            img = Image.open(io.BytesIO(content_bytes))
            img.verify()  # raises if not a genuine, decodable image
        except Exception:
            raise UploadRejected("File gambar tidak valid/rusak.")
        mime = "image/png" if ext == "png" else "image/jpeg"
        return safe_name, mime, None  # image text extraction (OCR) is out of scope for V1

    if ext == "txt":
        try:
            text = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            raise UploadRejected("File teks tidak terbaca sebagai UTF-8.")
        return safe_name, "text/plain", text[:20000]

    raise UploadRejected("Tipe file tidak didukung.")


def _extract_pdf_text(content_bytes):
    try:
        reader = pypdf.PdfReader(io.BytesIO(content_bytes))
        text_parts = []
        for page in reader.pages[:20]:  # guard against pathological huge PDFs
            text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)[:20000]
    except Exception:
        return None  # extraction failing is not fatal — file is still stored, just without text
