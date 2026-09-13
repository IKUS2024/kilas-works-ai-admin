"""Dynamic public catalog: active live service_catalog rows, admin descriptions and official links.

Prices and pricing modes come only from the live catalog. No historical order data or private
customer/talent data is read. Cached output is invalidated by catalog/official-link admin edits.
"""
import os

import catalog_cache
import catalog_service
import repo

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
_CACHE_PATH = os.path.join(_CACHE_DIR, "katalog_live.pdf")
_CACHE_STATE = {"version": None, "path": None}



def generate_catalog_pdf_bytes():
    """Builds the current catalog PDF from live DB state and returns it as raw bytes (never writes
    to disk itself — callers decide whether/where to cache).

    Uses the existing premium palette with active live rows, shared display descriptions and
    official links. The reference brand deck is never a price or status source."""
    import io
    from xml.sax.saxutils import escape
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import (
        BaseDocTemplate, PageTemplate, Frame, NextPageTemplate, PageBreak,
        Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
    )
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics import renderPDF

    # Embed fonts bundled with the existing ReportLab dependency so mobile PDF viewers do not
    # substitute incompatible system font metrics. No repository font/binary or new dependency.
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_dir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for name, filename in (("KilasSans", "Vera.ttf"), ("KilasSansBold", "VeraBd.ttf"), ("KilasSansItalic", "VeraIt.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, os.path.join(font_dir, filename)))

    items = catalog_service.list_active_catalog()
    official_links = repo.get_official_links()

    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    ORANGE = colors.HexColor("#E8622C")
    DARK = colors.HexColor("#17130F")
    DARK_PANEL = colors.HexColor("#1F1A15")
    INK = colors.HexColor("#1A1A1A")
    GREY = colors.HexColor("#5A5550")
    LIGHT_BG = colors.HexColor("#F6F3EF")
    LINE = colors.HexColor("#E4E0DA")
    CREAM = colors.HexColor("#F3EFEA")
    PAGE_W, PAGE_H = A4

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="KWCoverBrand", fontSize=13, leading=16, textColor=colors.white, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWCoverKicker", fontSize=9, leading=12, textColor=ORANGE, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWCoverTitle", fontSize=34, leading=38, textColor=colors.white, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWCoverTitleAccent", fontSize=34, leading=38, textColor=ORANGE, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWCoverTag", fontSize=11, leading=16, textColor=colors.HexColor("#D8D2C8"), fontName="KilasSans"))
    styles.add(ParagraphStyle(name="KWCoverFooter", fontSize=8.5, leading=11, textColor=colors.HexColor("#9A9284"), fontName="KilasSans"))
    styles.add(ParagraphStyle(name="KWEyebrow", fontSize=8.5, leading=11, textColor=ORANGE, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWTitle", fontSize=21, leading=25, textColor=INK, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWTitleAccent", fontSize=21, leading=25, textColor=ORANGE, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWBody", fontSize=9.5, leading=14, textColor=INK, fontName="KilasSans"))
    styles.add(ParagraphStyle(name="KWBodyMuted", fontSize=9, leading=13.5, textColor=GREY, fontName="KilasSans"))
    styles.add(ParagraphStyle(name="KWCardHead", fontSize=8.5, leading=11, textColor=GREY, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWBullet", fontSize=9, leading=14, textColor=INK, fontName="KilasSans", leftIndent=2))
    styles.add(ParagraphStyle(name="KWPkgName", fontSize=9.5, leading=13, textColor=INK, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWPkgPrice", fontSize=9.5, leading=13, textColor=ORANGE, fontName="KilasSansBold", alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="KWNote", fontSize=8, leading=11, textColor=GREY, fontName="KilasSansItalic"))
    styles.add(ParagraphStyle(name="KWGroupOverview", fontSize=8.5, leading=11, textColor=INK, fontName="KilasSansBold", alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="KWCTATitle", fontSize=25, leading=29, textColor=colors.white, fontName="KilasSansBold"))
    styles.add(ParagraphStyle(name="KWCTABody", fontSize=10, leading=15, textColor=colors.HexColor("#D8D2C8"), fontName="KilasSans"))
    styles.add(ParagraphStyle(name="KWCTAContact", fontSize=9.5, leading=15, textColor=colors.white, fontName="KilasSans"))

    styles["KWCardHead"].keepWithNext = True
    styles["KWPkgPrice"].keepWithNext = True

    def para(text, style="KWBody"):
        return Paragraph(text, styles[style])

    def bullets(items_list, style="KWBullet"):
        return [Paragraph(f"&#10003;&nbsp;&nbsp;{t}", styles[style]) for t in items_list]

    # ---------------- Page backgrounds/footers (dark cover+closing, light content) ----------------
    def _dark_page(canv, doc_):
        canv.saveState()
        canv.setFillColor(DARK)
        canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        canv.setStrokeColor(ORANGE)
        canv.setLineWidth(2)
        canv.line(20 * mm, 14 * mm, 45 * mm, 14 * mm)
        canv.restoreState()

    def _light_page(canv, doc_):
        canv.saveState()
        canv.setFillColor(colors.white)
        canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.6)
        canv.line(20 * mm, 14 * mm, PAGE_W - 20 * mm, 14 * mm)
        canv.setFillColor(GREY)
        canv.setFont("KilasSans", 7.5)
        canv.drawString(20 * mm, 9 * mm, "KILAS WORKS — SERVICE CATALOG")
        canv.drawRightString(PAGE_W - 20 * mm, 9 * mm, f"{canv.getPageNumber()}")
        canv.restoreState()

    frame_kwargs = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    dark_frame = Frame(20 * mm, 16 * mm, PAGE_W - 40 * mm, PAGE_H - 32 * mm, **frame_kwargs)
    light_frame = Frame(20 * mm, 18 * mm, PAGE_W - 40 * mm, PAGE_H - 34 * mm, **frame_kwargs)

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
        title="Kilas Works — Service Catalog",
    )
    doc.addPageTemplates([
        PageTemplate(id="Dark", frames=[dark_frame], onPage=_dark_page),
        PageTemplate(id="Light", frames=[light_frame], onPage=_light_page),
    ])

    story = [Spacer(1, 8 * mm), para("K &nbsp;KILAS WORKS", "KWCoverBrand"),
             Spacer(1, 40 * mm), para("AI &amp; CREATIVE", "KWCoverTitle"),
             para("SYSTEMS", "KWCoverTitleAccent"), Spacer(1, 8 * mm),
             para("Untuk Bisnis Modern", "KWCoverTag"), Spacer(1, 35 * mm),
             para("Katalog Layanan &amp; Investasi", "KWCoverFooter"),
             para(escape(official_links["landing_page"]), "KWCoverFooter"),
             NextPageTemplate("Light"), PageBreak()]
    story.extend([para("TENTANG KILAS WORKS", "KWEyebrow"), para("AI &amp; Creative Systems", "KWTitle"),
                  Spacer(1, 5 * mm), para("Kilas Works membantu bisnis melalui AI automation, business systems, dan creative production. Pilih layanan sesuai kebutuhan bisnismu; setiap layanan memiliki scope tersendiri."),
                  Spacer(1, 12 * mm), para("Cara Kami Bekerja", "KWTitle")])
    for title, text in (
        ("1. Audit Kebutuhan", "Diskusikan kebutuhan dan brief bisnis."),
        ("2. Setup &amp; Creative Direction", "Sepakati arah pengerjaan dan scope layanan."),
        ("3. Launch &amp; Test", "Jalankan dan tinjau hasil sesuai scope yang disepakati."),
        ("4. Optimize", "Evaluasi kebutuhan pengembangan berikutnya."),
    ):
        story.extend([Spacer(1, 5 * mm), para(title, "KWCardHead"), para(text)])
    groups = [
        ("Kilas Brain", ("AI_ADMIN",)),
        ("Business Systems", ("WEBSITE", "APPLICATION")),
        ("Creative Production", ("CONTENT", "VIDEO", "PHOTO", "BUNDLE", "EVENT")),
        ("Layanan Lainnya", tuple(k for k in by_category if k not in
            ("AI_ADMIN", "WEBSITE", "APPLICATION", "CONTENT", "VIDEO", "PHOTO", "BUNDLE", "EVENT"))),
    ]
    for title, categories in groups:
        rows = [item for category in categories for item in by_category.get(category, [])]
        if not rows:
            continue
        story.extend([PageBreak(), para("LAYANAN &amp; INVESTASI", "KWEyebrow"),
                      para(title, "KWTitle"), Spacer(1, 6 * mm)])
        for item in rows:
            # Paragraphs split across pages, unlike an oversized unsplittable card/table.
            story.extend([para(escape(catalog_service.public_name(item)), "KWCardHead"),
                          para(escape(catalog_service.display_price(item)), "KWPkgPrice"),
                          para(escape(catalog_service.service_description(item))),
                          Spacer(1, 6 * mm), HRFlowable(width="100%", thickness=.5, color=LINE),
                          Spacer(1, 6 * mm)])
    story.extend([NextPageTemplate("Dark"), PageBreak(), Spacer(1, 30 * mm),
                  para("MULAI DARI", "KWCTATitle"), para("KEBUTUHAN BISNISMU", "KWCoverTitleAccent"),
                  Spacer(1, 10 * mm), para("Diskusikan brief atau pilih layanan melalui Client Hub.", "KWCTABody"),
                  Spacer(1, 15 * mm)])
    for label, key in (("Website", "landing_page"), ("Client Hub", "app"), ("Instagram", "instagram"), ("Katalog", "catalog")):
        story.append(para(escape(label + ": " + official_links[key]), "KWCTAContact"))
    story.extend([Spacer(1, 20 * mm), para("K &nbsp;KILAS WORKS", "KWCoverBrand")])

    doc.build(story)
    return buf.getvalue()


def get_cached_catalog_pdf_path(force=False):
    """Returns a filesystem path to an up-to-date catalog PDF, regenerating on disk only when the
    cache is missing, stale (catalog_cache.get_version() moved), or `force=True` (used by the
    admin 'Regenerate Catalog' action). Returns None only if generation itself fails (e.g.
    reportlab not installed) — callers must report live catalog unavailable safely."""
    try:
        current_version = catalog_cache.get_version()
    except Exception:
        current_version = None  # DB unavailable — still try to generate/serve a best-effort PDF.

    if not force and _CACHE_STATE["path"] and os.path.exists(_CACHE_STATE["path"]) \
            and _CACHE_STATE["version"] == current_version:
        return _CACHE_STATE["path"]

    try:
        pdf_bytes = generate_catalog_pdf_bytes()
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_PATH, "wb") as f:
            f.write(pdf_bytes)
        _CACHE_STATE.update(version=current_version, path=_CACHE_PATH)
        return _CACHE_PATH
    except Exception as e:
        print("live_catalog_pdf: generation_failed")
        return None
