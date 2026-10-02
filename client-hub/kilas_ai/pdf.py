"""Small account-owned PDF renderer for Kilas AI document requests."""
import html
import io
import os
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


MAX_MARKDOWN = 24000
INK = colors.HexColor("#202126")
MUTED = colors.HexColor("#626974")
ACCENT = colors.HexColor("#E56D21")


def is_request(text, previous_document=None):
    value = " ".join((text or "").lower().split())
    if re.search(r"\bpdf\b", value) and re.search(r"\b(buat|jadikan|ubah|export|ekspor|generate|simpan|versi|hasilkan|cetak)\b", value):
        return True
    return bool(previous_document and re.search(r"\b(cover|sampul|tabel|tambahkan|revisi|perbaiki|lebih elegan|lebih premium|ubah desain)\b", value))


def document_context(context, previous_document=None):
    prepared = [dict(item) for item in context]
    if not prepared or prepared[-1]["role"] != "user":
        return prepared
    instruction = ("\n\nBuat isi dokumen yang diminta dalam Markdown yang rapi. Tulis dokumen itu sendiri, "
                   "bukan petunjuk membuat PDF. Gunakan judul #, subjudul ##, paragraf, daftar, dan tabel Markdown "
                   "hanya bila relevan. Jangan mengarang fakta atau harga. Jangan menulis blok kode atau penjelasan di luar dokumen.")
    if previous_document:
        instruction += "\n\nDokumen sebelumnya untuk revisi (gunakan sebagai konteks, jangan salin mentah):\n" + previous_document[:10000]
    content = prepared[-1]["content"]
    if isinstance(content, list):
        content = [dict(block) for block in content]
        content[0]["text"] += instruction
    else:
        content += instruction
    prepared[-1]["content"] = content
    return prepared


def _font_names():
    import reportlab
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    regular, bold = os.path.join(folder, "Vera.ttf"), os.path.join(folder, "VeraBd.ttf")
    if os.path.isfile(regular) and os.path.isfile(bold):
        if "KilasVera" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("KilasVera", regular))
            pdfmetrics.registerFont(TTFont("KilasVeraBold", bold))
        pdfmetrics.registerFontFamily("KilasVera", normal="KilasVera", bold="KilasVeraBold")
        return "KilasVera", "KilasVeraBold"
    return "Helvetica", "Helvetica-Bold"


def _inline(value):
    from urllib.parse import urlsplit
    value=re.sub(r'\[([^\]]+)\]\(https?://[^\s)]+\)',r'\1',value)
    value=re.sub(r'https?://[^\s<>]+',lambda m:urlsplit(m[0]).hostname or 'sumber',value)
    escaped = html.escape(value.strip())
    escaped=re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)',r'<i>\1</i>',escaped)


def _styles():
    regular, bold = _font_names()
    return {
        "title": ParagraphStyle("KilasTitle", fontName=bold, fontSize=24, leading=32, textColor=INK, spaceAfter=14),
        "cover": ParagraphStyle("KilasCover", fontName=bold, fontSize=30, leading=40, textColor=INK, alignment=TA_CENTER, spaceAfter=18),
        "h2": ParagraphStyle("KilasH2", fontName=bold, fontSize=15, leading=21, textColor=INK, spaceBefore=22, spaceAfter=9, keepWithNext=True),
        "h3": ParagraphStyle("KilasH3", fontName=bold, fontSize=11, leading=16, textColor=INK, spaceBefore=16, spaceAfter=7, keepWithNext=True),
        "body": ParagraphStyle("KilasBody", fontName=regular, fontSize=10, leading=16, textColor=INK, spaceAfter=10),
        "bullet": ParagraphStyle("KilasBullet", fontName=regular, fontSize=10, leading=16, textColor=INK, leftIndent=18, firstLineIndent=-10, spaceAfter=5),
        "cell": ParagraphStyle("KilasCell", fontName=regular, fontSize=9, leading=13, textColor=INK),
        "cell_head": ParagraphStyle("KilasCellHead", fontName=bold, fontSize=9, leading=13, textColor=INK),
    }


def _table(lines, styles, width, professional=False):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None
    if all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in rows[1]):
        rows.pop(1)
    if professional and (len(rows[0])>8 or any(len(row)!=len(rows[0]) for row in rows)):
        raise ValueError('invalid_document_table')
    columns = len(rows[0]) if professional else min(len(rows[0]), 5)
    if columns < 2:
        return None
    data = []
    for index, row in enumerate(rows if professional else rows[:31]):
        data.append([Paragraph(_inline(row[column] if column < len(row) else ""),
                               styles["cell_head"] if index == 0 else styles["cell"]) for column in range(columns)])
    table = Table(data, colWidths=[width / columns] * columns, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F1EC")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, ACCENT), ("LINEBELOW", (0, 1), (-1, -1), .4, colors.HexColor("#DFE1E5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return table


def render(markdown, *, title_hint="Dokumen", logo=None, cover=False, professional=False):
    text = (markdown or "").strip()[:MAX_MARKDOWN]
    if not text:
        raise ValueError("empty_document")
    styles = _styles()
    lines = text.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), title_hint.strip() or "Dokumen")[:100]
    stream = io.BytesIO()
    margin = 54
    width = A4[0] - 2 * margin
    document = SimpleDocTemplate(stream, pagesize=A4, leftMargin=margin, rightMargin=margin,
                                 topMargin=64, bottomMargin=58, title=title, author="Kilas Works")
    story = ([Spacer(1, 190), Paragraph(_inline(title), styles["cover"]),
              Spacer(1, 35), PageBreak()] if cover else
             [Paragraph(_inline(title), styles["title"]), Spacer(1, 7)])
    if logo:
        try:
            from PIL import Image as PILImage
            raw = io.BytesIO(logo)
            with PILImage.open(raw) as picture:
                picture.verify()
            raw.seek(0)
            with PILImage.open(raw) as picture:
                ratio = min(180 / picture.width, 90 / picture.height, 1)
                position = 1 if cover else 0
                story.insert(position, Image(raw, width=picture.width * ratio, height=picture.height * ratio))
                story.insert(position + 1, Spacer(1, 20))
        except Exception:
            pass
    index = 0
    title_skipped = False
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("# ") and not title_skipped:
            title_skipped = True
        elif line.startswith("## "):
            story.append(Paragraph(_inline(line[3:]), styles["h2"]))
        elif line.startswith("### "):
            story.append(Paragraph(_inline(line[4:]), styles["h3"]))
        elif line in ("---", "***"):
            story.append(Spacer(1, 10))
        elif line.startswith("|"):
            block = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index]); index += 1
            table = _table(block, styles, width,professional)
            if table:
                story.extend((Spacer(1, 8), table, Spacer(1, 12)))
            continue
        elif re.match(r"^(?:[-*]|\d+[.)])\s+", line):
            bullet = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)
            story.append(Paragraph("•  " + _inline(bullet), styles["bullet"]))
        else:
            paragraph = [line]
            while index + 1 < len(lines) and lines[index + 1].strip() and not re.match(r"^(?:#|[-*] |\d+[.)] |\|)", lines[index + 1].strip()):
                index += 1
                paragraph.append(lines[index].strip())
            story.append(Paragraph(_inline(" ".join(paragraph)), styles["body"]))
        index += 1

    def page(canvas, doc):
        if cover and doc.page == 1:
            return
        canvas.saveState()
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1.4)
        canvas.line(margin, A4[1] - 43, A4[0] - margin, A4[1] - 43)
        canvas.setFont(styles["body"].fontName, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 32, ('Kilas Works · ' if professional else '')+title[:55])
        canvas.drawRightString(A4[0] - margin, 32, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=page, onLaterPages=page)
    raw = stream.getvalue()
    if not raw.startswith(b"%PDF") or len(raw) < 1000 or len(raw) > 8 * 1024 * 1024:
        raise ValueError("invalid_generated_pdf")
    filename = re.sub(r"[^A-Za-z0-9-]+", "-", title.lower()).strip("-")[:55] or "dokumen-kilas"
    return {"filename": filename + ".pdf", "mime_type": "application/pdf", "byte_size": len(raw),
            "content": raw, "extracted_text": text, "title": title}
