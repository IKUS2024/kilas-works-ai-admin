"""Bounded Kilas AI file validation, extraction and provider context."""
import base64
import io
import math
import os
import re
import tempfile
import zipfile
from xml.etree import ElementTree

from PIL import Image, ImageOps
from pypdf import PdfReader

MAX_FILES = 4
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_STORED_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SOURCE_PIXELS = 250_000_000
MAX_NON_JPEG_SOURCE_PIXELS = 60_000_000
MAX_EXTRACTED_CHARS = 12000
PLAN_FILE_LIMITS = {"FREE": 2, "PLUS": 3, "PRO": 4, "MAX": 5}
MIMES = {
    "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain", "csv": "text/csv", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp",
}

# Samsung flagship 200 MP JPEGs are valid inputs. PIL still fails closed above this
# ceiling, and non-JPEG formats keep a tighter source-pixel bound because they do
# not support JPEG-style draft decoding before resize.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_SOURCE_PIXELS


class AttachmentError(ValueError):
    pass


def limits(plan):
    return {"max_files": PLAN_FILE_LIMITS.get(plan, PLAN_FILE_LIMITS["FREE"]),
            "max_file_bytes": MAX_FILE_BYTES,
            "max_image_bytes": MAX_IMAGE_BYTES}


def _spool_upload(stream, limit):
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    total = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            spool.close()
            return None, total
        spool.write(chunk)
    spool.seek(0)
    return spool, total


def _target_size(width, height):
    pixels = width * height
    if pixels <= MAX_IMAGE_PIXELS:
        return width, height
    scale = math.sqrt(MAX_IMAGE_PIXELS / float(pixels))
    return max(1, int(width * scale)), max(1, int(height * scale))


def _encode_image(image, image_format):
    working = image
    if image_format == "JPEG" and working.mode != "RGB":
        working = working.convert("RGB")
    quality = 92
    for _ in range(7):
        output = io.BytesIO()
        if image_format == "JPEG":
            working.save(output, "JPEG", quality=quality, optimize=True, progressive=True)
        elif image_format == "WEBP":
            working.save(output, "WEBP", quality=quality, method=4)
        else:
            working.save(output, "PNG", optimize=True)
        raw = output.getvalue()
        if len(raw) <= MAX_IMAGE_STORED_BYTES:
            return raw
        quality = max(78, quality - 4)
        next_size = (max(1, int(working.width * 0.82)), max(1, int(working.height * 0.82)))
        if next_size == working.size:
            break
        resized = working.copy()
        resized.thumbnail(next_size, Image.Resampling.LANCZOS)
        working = resized
    raise AttachmentError("Gambar terlalu besar untuk diproses dengan aman. Coba gunakan JPG atau resolusi yang lebih rendah.")


def _prepare_image(spool, total, mime):
    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime]
    try:
        with Image.open(spool) as opened:
            if opened.format != expected or getattr(opened, "n_frames", 1) != 1:
                raise ValueError("invalid_image")
            width, height = opened.size
            source_pixels = width * height
            if source_pixels <= 0 or source_pixels > MAX_IMAGE_SOURCE_PIXELS:
                raise AttachmentError("Resolusi gambar terlalu besar untuk diproses dengan aman.")
            if expected != "JPEG" and source_pixels > MAX_NON_JPEG_SOURCE_PIXELS:
                raise AttachmentError("PNG/WebP beresolusi sangat besar belum didukung. Gunakan JPG untuk foto resolusi tinggi.")

            # Preserve ordinary uploads byte-for-byte. Large phone photos are
            # normalized only when their payload or pixel count would be costly
            # for the DB/provider path.
            if source_pixels <= MAX_IMAGE_PIXELS and total <= MAX_IMAGE_STORED_BYTES:
                opened.verify()
                spool.seek(0)
                return spool.read()

            target = _target_size(width, height)
            if expected == "JPEG":
                opened.draft("RGB", target)
            normalized = ImageOps.exif_transpose(opened)
            if normalized.width * normalized.height > MAX_IMAGE_PIXELS:
                normalized.thumbnail(_target_size(normalized.width, normalized.height), Image.Resampling.LANCZOS)
            normalized.load()
            return _encode_image(normalized, expected)
    except AttachmentError:
        raise
    except Exception:
        raise AttachmentError("Gambar tidak dapat dibaca atau formatnya tidak sesuai.") from None


def prepare(upload, max_file_bytes=MAX_FILE_BYTES, max_image_bytes=MAX_IMAGE_BYTES):
    filename = os.path.basename(upload.filename or "")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")[:120]
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime = MIMES.get(extension)
    if not mime:
        raise AttachmentError("Tipe file tidak didukung. Gunakan PDF, DOCX, TXT, CSV, atau gambar.")
    claimed = (upload.mimetype or "").lower()
    if claimed not in (mime, "application/octet-stream") and not (extension == "csv" and claimed == "application/vnd.ms-excel"):
        raise AttachmentError("Tipe file tidak sesuai dengan isi yang dipilih.")

    is_image = mime.startswith("image/")
    limit = max_image_bytes if is_image else max_file_bytes
    spool, total = _spool_upload(upload.stream, limit)
    if spool is None or not total:
        label = f"{limit // 1024 // 1024} MB"
        raise AttachmentError(f"File kosong atau melebihi batas {label}.")
    try:
        raw = _prepare_image(spool, total, mime) if is_image else spool.read()
    finally:
        spool.close()

    extracted = None
    if is_image:
        pass
    elif extension == "pdf":
        if not raw.startswith(b"%PDF"):
            raise AttachmentError("PDF tidak valid.")
        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise AttachmentError("PDF terkunci belum dapat dibaca.")
            extracted = "\n".join((page.extract_text() or "") for page in reader.pages[:15])[:MAX_EXTRACTED_CHARS].strip()
        except AttachmentError:
            raise
        except Exception:
            raise AttachmentError("PDF tidak dapat dibaca.") from None
        if not extracted:
            raise AttachmentError("PDF ini tidak berisi teks yang dapat dibaca. Coba unggah PDF teks.")
    elif extension == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if len(archive.infolist()) > 300 or sum(info.file_size for info in archive.infolist()) > 12 * 1024 * 1024:
                    raise ValueError("oversized_docx")
                if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                    raise ValueError("invalid_docx")
                document = archive.read("word/document.xml")
                if len(document) > 4 * 1024 * 1024:
                    raise ValueError("large_document_xml")
            root = ElementTree.fromstring(document)
            extracted = " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))[:MAX_EXTRACTED_CHARS].strip()
        except Exception:
            raise AttachmentError("DOCX tidak dapat dibaca.") from None
        if not extracted:
            raise AttachmentError("DOCX ini tidak berisi teks yang dapat dibaca.")
    else:
        if b"\x00" in raw:
            raise AttachmentError("File teks tidak valid.")
        try:
            extracted = raw.decode("utf-8-sig")[:MAX_EXTRACTED_CHARS].strip()
        except UnicodeDecodeError:
            raise AttachmentError("Gunakan file teks UTF-8.") from None
    return {"filename": filename, "mime_type": mime, "byte_size": len(raw), "content": raw,
            "extracted_text": extracted}


def prepare_many(files, plan=None):
    max_files = limits(plan)["max_files"] if plan else MAX_FILES
    if len(files) > max_files:
        raise AttachmentError(f"Maksimal {max_files} lampiran per pesan.")
    return [prepare(upload) for upload in files]


def prompt_content(text, attachments):
    content = text
    for attachment in attachments:
        if attachment.get("extracted_text"):
            content += ("\n\nTeks berikut berhasil diekstrak dari lampiran '" + attachment["filename"] +
                        "'. Gunakan teks ini sebagai isi dokumen untuk menjawab pertanyaan saya. "
                        "Jangan menganggap lampiran tidak dapat dibaca.\n<isi_lampiran>\n" +
                        attachment["extracted_text"] + "\n</isi_lampiran>")
    images = [attachment for attachment in attachments if attachment["mime_type"].startswith("image/")]
    if not images:
        return content[:16000]
    blocks = [{"type": "text", "text": content[:16000]}]
    for attachment in images:
        blocks.append({"type": "image_url", "image_url": {"url": "data:" + attachment["mime_type"] +
                       ";base64," + base64.b64encode(bytes(attachment["content"])).decode("ascii")}})
    return blocks
