"""Bounded Kilas AI file validation, extraction and provider context."""
import base64
import io
import os
import re
import zipfile
from xml.etree import ElementTree

from PIL import Image
from pypdf import PdfReader

MAX_FILES = 4
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 12000
PLAN_FILE_LIMITS = {"FREE": 2, "PLUS": 3, "PRO": 4, "MAX": 5}
MIMES = {
    "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain", "csv": "text/csv", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp",
}


class AttachmentError(ValueError):
    pass


def limits(plan):
    return {"max_files": PLAN_FILE_LIMITS.get(plan, PLAN_FILE_LIMITS["FREE"]),
            "max_file_bytes": MAX_FILE_BYTES}


def prepare(upload, max_file_bytes=MAX_FILE_BYTES):
    filename = os.path.basename(upload.filename or "")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")[:120]
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime = MIMES.get(extension)
    if not mime:
        raise AttachmentError("Tipe file tidak didukung. Gunakan PDF, DOCX, TXT, CSV, atau gambar.")
    claimed = (upload.mimetype or "").lower()
    if claimed not in (mime, "application/octet-stream") and not (extension == "csv" and claimed == "application/vnd.ms-excel"):
        raise AttachmentError("Tipe file tidak sesuai dengan isi yang dipilih.")
    raw = upload.stream.read(max_file_bytes + 1)
    if not raw or len(raw) > max_file_bytes:
        raise AttachmentError("File kosong atau melebihi batas 2 MB.")
    extracted = None
    if mime.startswith("image/"):
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime]
                if image.format != expected or image.width * image.height > 20_000_000 or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("invalid_image")
        except Exception:
            raise AttachmentError("Gambar tidak dapat dibaca atau formatnya tidak sesuai.") from None
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
