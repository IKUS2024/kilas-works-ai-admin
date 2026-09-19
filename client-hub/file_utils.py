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
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "txt", "webp"}

# Final Operations Polish, Section 2: talent profile photo direct upload reuses this same
# validation, restricted to just the image types it actually needs (no PDF/TXT for a photo field).
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB — generous for a phone photo, small enough for a profile pic


class UploadRejected(Exception):
    def __init__(self, message, code='validation_rejected'):
        super().__init__(message)
        self.code = code


FINANCE_IMAGE_INPUT_BYTES = 20 * 1024 * 1024


def prepare_finance_document(filename, raw):
    """Preserve original identity at the caller; normalize only provider-bound pixels.

    Finance-only: other upload limits and storage flows remain unchanged.
    """
    ext = _extension_of(filename or '')
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        name, mime, text = validate_receipt_upload(filename, raw)
        return name, mime, text, raw
    if not raw or len(raw) > FINANCE_IMAGE_INPUT_BYTES:
        raise UploadRejected('Foto maksimal 20 MiB sebelum normalisasi aman.', 'image_input_size')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            expected={'jpg':'JPEG','jpeg':'JPEG','png':'PNG','webp':'WEBP'}[ext]
            if image.format != expected or image.width * image.height > 80_000_000 or getattr(image,'n_frames',1)!=1:
                raise ValueError()
            unchanged=(len(raw)<=MAX_ATTACHMENT_UPLOAD_BYTES and image.width*image.height<=20_000_000
                       and max(image.size)<=8000 and image.getexif().get(274,1)==1
                       and image.mode in ('RGB','L'))
        if unchanged:
            name,mime,text=validate_receipt_upload(filename,raw)
            return name,mime,text,raw
    except Exception:
        raise UploadRejected('File gambar tidak dapat dibaca atau format tidak sesuai.', 'image_structure') from None
    import subprocess
    import sys
    from pathlib import Path
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('finance_image.py'))],
                                input=raw, capture_output=True, timeout=10, check=True)
        if not result.stdout or len(result.stdout) > 4 * 1024 * 1024:
            raise ValueError()
        name = sanitize_filename(filename)
        return name, 'image/jpeg', None, result.stdout
    except Exception:
        raise UploadRejected('File gambar tidak dapat dibaca atau terlalu besar setelah normalisasi aman. Gunakan foto lebih dekat atau resolusi lebih rendah.', 'image_normalization') from None


def sanitize_filename(filename):
    base = os.path.basename(filename or "upload")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "upload"
    return base[:120]


def _extension_of(filename):
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def _looks_like_valid_pdf(content_bytes):
    """Content-sniffing (not filename-based): true only for genuine PDF bytes."""
    return content_bytes.startswith(b"%PDF")


def _looks_like_valid_image(content_bytes):
    """Content-sniffing (not filename-based): true only for bytes Pillow can actually decode as a
    real image — rejects a script/HTML/executable renamed with an image extension."""
    try:
        img = Image.open(io.BytesIO(content_bytes))
        img.verify()  # raises if not a genuine, decodable image
        return True
    except Exception:
        return False


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
        if not _looks_like_valid_pdf(content_bytes):
            raise UploadRejected("File tidak terbaca sebagai PDF yang valid.")
        extracted = _extract_pdf_text(content_bytes)
        return safe_name, "application/pdf", extracted

    if ext in ("png", "jpg", "jpeg", "webp"):
        if not _looks_like_valid_image(content_bytes):
            raise UploadRejected("File gambar tidak valid/rusak.")
        mime = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
        return safe_name, mime, None  # image text extraction (OCR) is out of scope for V1

    if ext == "txt":
        try:
            text = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            raise UploadRejected("File teks tidak terbaca sebagai UTF-8.")
        return safe_name, "text/plain", text[:20000]

    raise UploadRejected("Tipe file tidak didukung.")


def validate_image_upload(filename, content_bytes):
    """Section 2 (talent profile photo direct upload): a tighter validator than
    validate_and_extract() above — image types only (JPG/JPEG/PNG/WEBP), a smaller size cap
    appropriate for a profile photo, and no text-extraction step (irrelevant for a photo).
    Returns (safe_filename, mime_type). Raises UploadRejected with a user-safe message."""
    if not content_bytes:
        raise UploadRejected("File kosong.")
    if len(content_bytes) > MAX_IMAGE_UPLOAD_BYTES:
        raise UploadRejected(f"File terlalu besar (maks {MAX_IMAGE_UPLOAD_BYTES // (1024*1024)}MB).")

    safe_name = sanitize_filename(filename)
    ext = _extension_of(safe_name)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise UploadRejected("Tipe file tidak didukung. Gunakan JPG, JPEG, PNG, atau WEBP.")

    if not _looks_like_valid_image(content_bytes):
        raise UploadRejected("File gambar tidak valid/rusak.")

    mime = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return safe_name, mime


# Section (custom project attachments): allowed types JPG/JPEG/PNG/WEBP/PDF, 5MB max — reuses the
# SAME content-sniffing helpers as validate_and_extract()/validate_image_upload() above (never a
# third, independent implementation of the actual byte checks), just a distinct extension set/size
# cap for this specific field ("Upload Brief / Referensi" on a custom project request).
ALLOWED_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
MAX_ATTACHMENT_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def validate_project_attachment_upload(filename, content_bytes):
    """Returns (safe_filename, mime_type). Raises UploadRejected with a user-safe message on any
    validation failure — oversized file, disallowed type, or content that doesn't actually match
    its claimed type (e.g. a script/HTML file renamed with a .jpg/.pdf extension)."""
    if not content_bytes:
        raise UploadRejected("File kosong.")
    if len(content_bytes) > MAX_ATTACHMENT_UPLOAD_BYTES:
        raise UploadRejected(f"File terlalu besar (maks {MAX_ATTACHMENT_UPLOAD_BYTES // (1024*1024)}MB).")

    safe_name = sanitize_filename(filename)
    ext = _extension_of(safe_name)
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise UploadRejected("Tipe file tidak didukung. Gunakan JPG, JPEG, PNG, WEBP, atau PDF.")

    if ext == "pdf":
        if not _looks_like_valid_pdf(content_bytes):
            raise UploadRejected("File tidak terbaca sebagai PDF yang valid.")
        return safe_name, "application/pdf"

    if not _looks_like_valid_image(content_bytes):
        raise UploadRejected("File gambar tidak valid/rusak.")
    mime = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return safe_name, mime


def _extract_pdf_text(content_bytes):
    try:
        reader = pypdf.PdfReader(io.BytesIO(content_bytes))
        text_parts = []
        for page in reader.pages[:20]:  # guard against pathological huge PDFs
            text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)[:20000]
    except Exception:
        return None  # extraction failing is not fatal — file is still stored, just without text


def validate_receipt_upload(filename, content_bytes):
    """Receipt-only restrictions layered over existing attachment byte validation.

    PDFs are parsed in a bounded child process: no archive, temporary draft or OCR
    vendor. Return safe name, real MIME and bounded PDF text (None for scans/images).
    """
    if _extension_of(sanitize_filename(filename)) == 'pdf':
        safe_name = _validate_finance_pdf_bytes(filename, content_bytes, receipt=True)
        return safe_name, 'application/pdf', _finance_pdf_text(content_bytes, receipt=True) or None
    safe_name, mime = validate_project_attachment_upload(filename, content_bytes)
    if mime != 'application/pdf':
        try:
            with Image.open(io.BytesIO(content_bytes)) as img:
                actual = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}.get(img.format)
                if actual != mime or img.width * img.height > 20_000_000 or getattr(img, 'n_frames', 1) != 1:
                    raise ValueError('unsupported_image')
                img.load()
        except Exception:
            raise UploadRejected('Gambar tidak valid, terlalu besar, atau format tidak sesuai.') from None
        return safe_name, mime, None


def validate_bank_pdf(filename, content_bytes):
    """Bank-only 10 MiB/20-page wrapper sharing existing PDF sniff and isolated worker."""
    safe_name = _validate_finance_pdf_bytes(filename, content_bytes)
    return safe_name, _finance_pdf_text(content_bytes)


def validate_finance_pdf(filename, content_bytes):
    """Generic pre-classification structure check; no bank or receipt interpretation.

    Up to 10 MiB/20 pages. Specialized workflows retain their own limits afterward.
    The original bytes are kept request-local for document classification/vision.
    """
    safe_name = _validate_finance_pdf_bytes(filename, content_bytes)
    _run_finance_pdf(content_bytes, structure_only=True)
    return safe_name


def _pdf_rejected(reason, receipt=False):
    import finance_ai_safety as safety
    messages = {
        'encrypted/password_required': 'PDF ini terenkripsi dan memerlukan password. Upload PDF tanpa password atau foto/screenshot.',
        'page_limit': f'PDF melebihi batas {10 if receipt else 20} halaman. Pisahkan dokumen lalu upload kembali.',
        'size_limit': f'PDF melebihi batas {5 if receipt else 10} MiB. Upload dokumen yang lebih kecil.',
        'parser_timeout': 'PDF terlalu kompleks untuk diperiksa dengan aman. Upload PDF sederhana atau foto/screenshot.',
        'resource_limit': 'PDF melewati batas sumber daya pemeriksaan aman. Upload PDF sederhana atau foto/screenshot.',
        'malformed_pdf': 'File PDF tidak dapat dibaca atau strukturnya rusak. Upload ulang PDF atau foto/screenshot.',
    }
    reason = reason if reason in messages else 'malformed_pdf'
    safety.pdf_event(reason)
    return UploadRejected(messages[reason], reason)


def _validate_finance_pdf_bytes(filename, raw, receipt=False):
    if len(raw) > (5 if receipt else 10) * 1024 * 1024:
        raise _pdf_rejected('size_limit', receipt)
    safe_name = sanitize_filename(filename)
    if _extension_of(safe_name) != 'pdf' or not raw or not _looks_like_valid_pdf(raw):
        raise _pdf_rejected('malformed_pdf', receipt)
    return safe_name


def _run_finance_pdf(raw, receipt=False, structure_only=False):
    import json
    import subprocess
    import sys
    from pathlib import Path
    import finance_ai_safety as safety
    args = [sys.executable, str(Path(__file__).with_name('finance_receipt_pdf.py'))]
    if not receipt:
        args.append('--document')
    if structure_only:
        args.append('--validate-only')
    try:
        result = subprocess.run(args, input=raw, capture_output=True, timeout=8, check=True)
        data = json.loads(result.stdout)
        if set(data) == {'error'} and isinstance(data['error'], str):
            raise _pdf_rejected(data['error'], receipt)
        if (set(data) != {'text'} or not isinstance(data['text'], str)
                or len(data['text']) > (20000 if receipt else 100000)
                or (structure_only and data['text'])):
            raise ValueError()
        if b'text_extraction_failed\n' in result.stderr:
            safety.pdf_event('text_extraction_failed')
        return data['text']
    except UploadRejected:
        raise
    except subprocess.TimeoutExpired:
        raise _pdf_rejected('parser_timeout', receipt) from None
    except subprocess.CalledProcessError as error:
        # SIGKILL/SIGXCPU are the worker's OS resource ceilings; no child diagnostics logged.
        reason = 'resource_limit' if error.returncode in (-9, -24) else 'malformed_pdf'
        raise _pdf_rejected(reason, receipt) from None
    except (MemoryError, OSError):
        raise _pdf_rejected('resource_limit', receipt) from None
    except (ValueError, TypeError, KeyError):
        raise _pdf_rejected('malformed_pdf', receipt) from None


def _finance_pdf_text(raw, receipt=False):
    try:
        return _run_finance_pdf(raw, receipt=receipt)
    except UploadRejected as error:
        if error.code in ('encrypted/password_required', 'page_limit', 'size_limit'):
            raise
        # A failed text decoder is not proof of a bad document. A separate bounded
        # structure-only pass must succeed before passing original bytes to vision.
        _run_finance_pdf(raw, receipt=receipt, structure_only=True)
        return ''
