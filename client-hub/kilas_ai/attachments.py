"""Bounded Kilas AI file validation, extraction and provider context."""
import base64
import csv
import io
import math
import os
import re
import tempfile
import zipfile
from xml.etree import ElementTree

from PIL import Image, ImageOps

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
    vision_pages=[]
    if is_image:
        pass
    elif extension == "pdf":
        if not raw.startswith(b"%PDF"):
            raise AttachmentError("PDF tidak valid.")
        try:
            from .pdf_vision import native
            parsed=native(raw)
            extracted=parsed['text']
        except AttachmentError:
            raise
        except Exception:
            raise AttachmentError("PDF tidak dapat dibaca dengan aman. Periksa apakah file terkunci, rusak, atau terlalu kompleks.") from None
        if parsed['scan']:
            from .capabilities import current
            if not current()['uploaded_image_understanding']:
                if not parsed['has_text']:
                    raise AttachmentError('PDF ini berupa scan. Pembacaan gambar belum aktif; unggah PDF teks atau salin isi yang dibutuhkan.')
                extracted+='\nHalaman gambar belum dibaca; gunakan hanya teks yang berhasil diekstrak.'
                return {'filename':filename,'mime_type':mime,'byte_size':len(raw),'content':raw,'extracted_text':extracted[:MAX_EXTRACTED_CHARS],'vision_pages':[]}
            try:
                from .pdf_vision import render
                vision_pages=render(raw)
            except Exception:
                raise AttachmentError('Halaman scan PDF belum dapat diproses dengan aman. Unggah maksimal tiga halaman sebagai JPG/PNG atau gunakan PDF teks.') from None
            extracted=extracted[:MAX_EXTRACTED_CHARS-200]+'\nPDF scan: hanya '+str(len(vision_pages))+' halaman pertama disertakan sebagai gambar; jangan menebak halaman lain.'
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
                if b'<!DOCTYPE' in document or b'<!ENTITY' in document:
                    raise ValueError('unsafe_document_xml')
            root = ElementTree.fromstring(document)
            paragraphs=[]
            body=next((node for node in root.iter() if node.tag.endswith('}body')),root)
            for node in body:
                if node.tag.endswith('}tbl'):
                    paragraphs.append('Table:')
                    for row in node:
                        if row.tag.endswith('}tr'):
                            cells=[' '.join(part.text or '' for part in cell.iter() if part.tag.endswith('}t')) for cell in row if cell.tag.endswith('}tc')]
                            paragraphs.append(' | '.join(cells))
                elif node.tag.endswith('}p'):
                    value=''.join(part.text or '' for part in node.iter() if part.tag.endswith('}t'))
                    style=next((part.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val','') for part in node.iter() if part.tag.endswith('}pStyle')),'')
                    if style.lower().startswith('heading'):value='Heading: '+value
                    if value.strip():paragraphs.append(value)
            extracted = '\n'.join(paragraphs)[:MAX_EXTRACTED_CHARS].strip()
        except Exception:
            raise AttachmentError("DOCX tidak dapat dibaca.") from None
        if not extracted:
            raise AttachmentError("DOCX ini tidak berisi teks yang dapat dibaca.")
    else:
        if b"\x00" in raw and not raw.startswith((b'\xff\xfe',b'\xfe\xff')):
            raise AttachmentError("File teks tidak valid.")
        try:
            extracted = raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else "utf-8-sig")[:MAX_EXTRACTED_CHARS].strip()
        except UnicodeDecodeError:
            raise AttachmentError("Gunakan file teks UTF-8.") from None
        if extension=='csv':
            try:
                dialect=csv.Sniffer().sniff(extracted[:2048],delimiters=',;\t')
            except csv.Error:
                dialect=csv.excel
            rows=csv.reader(io.StringIO(extracted),dialect)
            extracted='\n'.join('Row '+str(number)+': '+' | '.join(cell[:200] for cell in row[:20])
                                for number,row in zip(range(1,201),rows))[:MAX_EXTRACTED_CHARS]
    return {"filename": filename, "mime_type": mime, "byte_size": len(raw), "content": raw,
            "extracted_text": extracted, 'vision_pages':vision_pages}


def prepare_many(files, plan=None):
    max_files = limits(plan)["max_files"] if plan else MAX_FILES
    if len(files) > max_files:
        raise AttachmentError(f"Maksimal {max_files} lampiran per pesan.")
    return [prepare(upload) for upload in files]


def prompt_content(text, attachments):
    content = text
    documents=[item for item in attachments if item.get('extracted_text')]
    source_budget=max(0,16000-len(text)-350*len(documents))
    per_source=min(MAX_EXTRACTED_CHARS,source_budget//max(1,len(documents)))
    for attachment in attachments:
        if attachment.get("extracted_text"):
            content += ("\n\nTeks berikut berhasil diekstrak dari lampiran '" + attachment["filename"] +
                        "'. Gunakan teks ini sebagai isi dokumen untuk menjawab pertanyaan saya. "
                        "Jangan menganggap lampiran tidak dapat dibaca.\n<isi_lampiran>\n" +
                        attachment["extracted_text"][:per_source] + "\n</isi_lampiran>")
    images = [attachment for attachment in attachments if attachment["mime_type"].startswith("image/")]
    images+= [page for attachment in attachments for page in attachment.get('vision_pages',[])]
    if not images:
        return content[:16000]
    blocks = [{"type": "text", "text": content[:16000]}]
    for attachment in images:
        blocks.append({"type": "image_url", "image_url": {"url": "data:" + attachment["mime_type"] +
                       ";base64," + base64.b64encode(bytes(attachment["content"])).decode("ascii")}})
    return blocks
