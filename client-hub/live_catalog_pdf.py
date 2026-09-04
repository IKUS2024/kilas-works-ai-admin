"""Live-generated public catalog PDF — Absolute Final Production Patch (master spec Sections 6-10).

Unlike ../generate_katalog_pdf.py (a manually-run script that reads ../app.py's hardcoded
PRICING_CONFIG dict and client-hub/talent_service.SEED_TALENTS — a snapshot that goes stale the
moment an admin edits a price or a talent's follower count), this module builds the catalog PDF
straight from LIVE database state every time it's asked to: `service_catalog` rows (via
catalog_service.list_active_catalog()) and `talents` rows (via talent_service.list_active_talents()).
There are no hardcoded prices or talent numbers anywhere in this file.

RULES ENFORCED HERE (never violate these when editing this file):
  - AI Admin items are shown fixed-price only. There is no "Custom AI Admin" — CATALOG_ITEMS has no
    such entry, so this is naturally true, but it's called out here as an invariant a future edit
    must not break.
  - Content Basic/Growth/Pro are shown with their fixed prices; "Custom Content Project" is shown
    as Custom Quote (never a number).
  - Photo, Video, and Talent are ALWAYS Custom Quote — never a public number, ever, for any of
    these three categories.
  - Website shows fixed prices for its concrete packages; "Custom Website / Application" is Custom
    Quote.
  - Talent entries show name / handle / follower count / niche only. `internal_rate` and
    `internal_notes` are never read by this module, let alone rendered — grep this file for
    "internal_rate" and you will find nothing, by design.
  - This module NEVER touches historical projects/quotations/invoices — it only ever reads
    service_catalog and talents, both of which are already documented (catalog_service.py,
    talent_service.py) as safe to change without disturbing any past order's locked-in price.

CACHING: generation is cheap (a handful of DB rows + reportlab), but there is no reason to pay that
cost on every single request either. `get_cached_catalog_pdf_path()` keeps one generated file on
disk plus the catalog_cache.version it was generated from; a request only regenerates when
catalog_cache.get_version() has moved (i.e. an admin changed a price, toggled a service, or edited
a talent — see catalog_service.update_catalog_item / talent_service._bump_catalog_cache) or when
the cached file is missing. No manual script re-run is ever required for this to reflect a change.
"""
import os

import catalog_cache
import catalog_service
import repo
import talent_service

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
_CACHE_PATH = os.path.join(_CACHE_DIR, "katalog_live.pdf")
_CACHE_STATE = {"version": None, "path": None}

_CUSTOM_QUOTE_ONLY_CATEGORIES = ("PHOTO", "VIDEO", "TALENT")


def generate_catalog_pdf_bytes():
    """Builds the current catalog PDF from live DB state and returns it as raw bytes (never writes
    to disk itself — callers decide whether/where to cache).

    Premium service-deck redesign (v2 — visual direction from a reference agency-deck image):
    dark cover/closing pages via a dedicated PageTemplate, light content pages with a consistent
    footer, and a two-column "benefits checklist + pricing card" layout per service page instead
    of a spreadsheet-style table. Raw service_catalog categories are consolidated into the 6
    customer-facing groups Kilas Works actually sells as (see _CUSTOMER_FACING_GROUPS below) — a
    presentation-layer grouping only; the underlying live data/source-of-truth
    (catalog_service.list_active_catalog()) is completely unchanged, so an admin price/description/
    active-state edit still propagates here exactly as before."""
    import io
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

    items = catalog_service.list_active_catalog()
    talents = talent_service.list_active_talents()
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
    styles.add(ParagraphStyle(name="KWCoverBrand", fontSize=13, leading=16, textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCoverKicker", fontSize=9, leading=12, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCoverTitle", fontSize=34, leading=38, textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCoverTitleAccent", fontSize=34, leading=38, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCoverTag", fontSize=11, leading=16, textColor=colors.HexColor("#D8D2C8"), fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCoverFooter", fontSize=8.5, leading=11, textColor=colors.HexColor("#9A9284"), fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWEyebrow", fontSize=8.5, leading=11, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWTitle", fontSize=21, leading=25, textColor=INK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWTitleAccent", fontSize=21, leading=25, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWBody", fontSize=9.5, leading=14, textColor=INK, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWBodyMuted", fontSize=9, leading=13.5, textColor=GREY, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCardHead", fontSize=8.5, leading=11, textColor=GREY, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWBullet", fontSize=9, leading=14, textColor=INK, fontName="Helvetica", leftIndent=2))
    styles.add(ParagraphStyle(name="KWPkgName", fontSize=9.5, leading=13, textColor=INK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWPkgPrice", fontSize=9.5, leading=13, textColor=ORANGE, fontName="Helvetica-Bold", alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="KWNote", fontSize=8, leading=11, textColor=GREY, fontName="Helvetica-Oblique"))
    styles.add(ParagraphStyle(name="KWGroupOverview", fontSize=8.5, leading=11, textColor=INK, fontName="Helvetica-Bold", alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="KWCTATitle", fontSize=25, leading=29, textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCTABody", fontSize=10, leading=15, textColor=colors.HexColor("#D8D2C8"), fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCTAContact", fontSize=9.5, leading=15, textColor=colors.white, fontName="Helvetica"))

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
        canv.setFont("Helvetica", 7.5)
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

    def pricing_card(rows_for_group):
        """A single light-bordered "card" flowable: package name + live price per row, right
        column right-aligned — the pricing-card half of the two-column benefit+investment layout
        the reference deck uses. Never a spreadsheet grid: no gridlines, just clean rows."""
        table_rows = [[para("PAKET &amp; INVESTASI", "KWCardHead"), ""]]
        for it in rows_for_group:
            price_label = catalog_service.format_price(it.get("price_amount"), it.get("price_unit"))
            table_rows.append([para(it["name"], "KWPkgName"), para(price_label, "KWPkgPrice")])
        t = Table(table_rows, colWidths=[110 * mm, 40 * mm])
        t.setStyle(TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, ORANGE),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, LINE),
            ("TOPPADDING", (0, 1), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        wrapper = Table([[t]], colWidths=[160 * mm])
        wrapper.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("BACKGROUND", (0, 0), (-1, -1), CREAM),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return wrapper

    def note_card(text):
        t = Table([[para(text, "KWNote")]], colWidths=[160 * mm])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("BACKGROUND", (0, 0), (-1, -1), CREAM),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return t

    # Customer-facing service grouping (presentation layer only — see this function's own
    # docstring). "benefits" bullets are generic value statements, never fabricated
    # metrics/results/testimonials (explicitly forbidden) — only capability statements.
    _CUSTOMER_FACING_GROUPS = [
        {
            "key": "ai_admin", "title": "Kilas Brain", "categories": ["AI_ADMIN"], "flagship": True,
            "description": (
                "Kilas Brain membantu bisnis menangani pertanyaan customer, informasi layanan, sales "
                "support, follow-up, dan kebutuhan WhatsApp sehari-hari — dengan tetap memungkinkan "
                "tim mengambil alih percakapan saat diperlukan."
            ),
            "benefits": [
                "Respons customer lebih cepat, 24/7",
                "Menggunakan knowledge bisnis kamu sendiri",
                "Bantu sales &amp; follow-up otomatis",
                "Human handoff kapan pun dibutuhkan",
                "Operasional WhatsApp lebih efisien",
            ],
        },
        {
            "key": "content", "title": "Content &amp; Creative", "categories": ["CONTENT", "BUNDLE", "EVENT", "VIDEO", "PHOTO"],
            "description": (
                "Produksi foto, video, reels, dan konten campaign untuk kebutuhan brand — dari konten "
                "rutin bulanan sampai dokumentasi event, disesuaikan dengan kebutuhan project."
            ),
            "benefits": [
                "Foto produk &amp; brand",
                "Video campaign / company profile",
                "Reels &amp; konten short-form",
                "Konten media sosial rutin",
                "Produksi konten custom",
            ],
        },
        {
            "key": "ads", "title": "Meta Ads", "categories": ["ADS"],
            "description": (
                "Setup dan pengelolaan campaign iklan Meta (Instagram &amp; Facebook) — membantu bisnis "
                "menyusun campaign yang terstruktur dan menjangkau audiens yang relevan."
            ),
            "benefits": [
                "Setup &amp; struktur campaign",
                "Manajemen &amp; optimasi iklan",
                "Targeting audiens tepat",
                "Laporan performa campaign",
                "Konsultasi strategi iklan",
            ],
        },
        {
            "key": "website", "title": "Website &amp; Digital Solutions", "categories": ["WEBSITE", "APPLICATION"],
            "description": (
                "Landing page, website company profile, sampai sistem/aplikasi custom sesuai kebutuhan "
                "bisnis dan proses kerja kamu."
            ),
            "benefits": [
                "Desain modern &amp; responsif",
                "Performa cepat &amp; aman",
                "Struktur SEO-friendly",
                "Mudah dikelola",
                "Support &amp; maintenance",
            ],
        },
        {
            "key": "talent", "title": "Talent &amp; Creator Management", "categories": ["TALENT"], "no_roster": True,
            "description": (
                "Kilas Works membantu brand menjalankan kolaborasi dengan talent dan creator untuk "
                "kebutuhan endorsement, campaign, product placement, social content, dan brand "
                "collaboration."
            ),
            "benefits": [
                "Endorsement &amp; kolaborasi konten",
                "Campaign &amp; product placement",
                "Social media content collaboration",
                "Rekomendasi talent sesuai campaign",
            ],
        },
        {
            "key": "custom", "title": "Custom Solutions", "categories": [], "text_only": True,
            "description": (
                "Setiap bisnis punya kebutuhan yang unik. Kami siap memberikan solusi khusus di luar "
                "layanan standar untuk mencapai tujuan bisnis yang lebih spesifik."
            ),
            "benefits": [],
        },
    ]

    story = []

    # ---------------- PAGE 1 — COVER (dark) ----------------
    story.append(NextPageTemplate("Dark"))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("K &nbsp;KILAS WORKS", styles["KWCoverBrand"]))
    story.append(Spacer(1, 46 * mm))
    story.append(Paragraph("SERVICE CATALOG", styles["KWCoverKicker"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("AI, CONTENT &amp;", styles["KWCoverTitle"]))
    story.append(Paragraph("DIGITAL SOLUTIONS", styles["KWCoverTitleAccent"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Satu Partner. Banyak Solusi.", styles["KWCoverTag"]))
    story.append(Paragraph("Hasil Nyata untuk Pertumbuhan Bisnis Anda.", styles["KWCoverTag"]))
    story.append(Spacer(1, 50 * mm))
    story.append(Paragraph(
        " &nbsp;&bull;&nbsp; ".join(g["title"] for g in _CUSTOMER_FACING_GROUPS),
        styles["KWCoverFooter"],
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(official_links["landing_page"].replace("https://", ""), styles["KWCoverFooter"]))

    # ---------------- PAGE 2 — ABOUT (light) ----------------
    story.append(NextPageTemplate("Light"))
    story.append(PageBreak())
    story.append(Paragraph("TENTANG", styles["KWEyebrow"]))
    story.append(Paragraph("Kilas Works", styles["KWTitle"]))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width=32 * mm, thickness=2, color=ORANGE))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Kilas Works adalah partner strategis untuk bisnis yang ingin tumbuh lebih cepat lewat AI "
        "WhatsApp Admin, content &amp; creative, Meta Ads, website &amp; digital solutions, sampai "
        "kolaborasi talent/creator — dikerjakan oleh tim yang sama, dengan satu titik komunikasi.",
        styles["KWBody"],
    ))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("6 AREA LAYANAN UTAMA", styles["KWCardHead"]))
    story.append(Spacer(1, 4 * mm))
    overview_cells = []
    for g in _CUSTOMER_FACING_GROUPS:
        cell_table = Table([[para(g["title"].replace("&amp;", "&amp;<br/>"), "KWGroupOverview")]], colWidths=[42 * mm])
        cell_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("BACKGROUND", (0, 0), (-1, -1), CREAM),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        overview_cells.append(cell_table)
    grid_rows = [overview_cells[i:i + 3] for i in range(0, len(overview_cells), 3)]
    grid = Table(grid_rows, colWidths=[52 * mm] * 3)
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    story.append(grid)

    # ---------------- SERVICE PAGES (light) ----------------
    for group in _CUSTOMER_FACING_GROUPS:
        rows_for_group = []
        for cat in group["categories"]:
            rows_for_group.extend(by_category.get(cat, []))

        story.append(PageBreak())
        if group.get("flagship"):
            story.append(Paragraph("PRODUK UNGGULAN", styles["KWEyebrow"]))
        else:
            story.append(Paragraph("LAYANAN", styles["KWEyebrow"]))
        story.append(Paragraph(group["title"], styles["KWTitle"]))
        story.append(Spacer(1, 2 * mm))
        story.append(HRFlowable(width=32 * mm, thickness=2, color=ORANGE))
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(group["description"], styles["KWBody"]))
        story.append(Spacer(1, 8 * mm))

        left_col = []
        if group["benefits"]:
            left_col.append(para("MANFAAT &amp; LAYANAN KAMI", "KWCardHead"))
            left_col.append(Spacer(1, 3 * mm))
            left_col.extend(bullets(group["benefits"]))
        elif group.get("no_roster"):
            left_col.append(para("PERTIMBANGAN PEMILIHAN TALENT", "KWCardHead"))
            left_col.append(Spacer(1, 3 * mm))
            left_col.extend(bullets([
                "Target audience", "Konsep campaign", "Platform", "Budget", "Availability",
            ]))

        if group.get("text_only"):
            right_col = [note_card("Penawaran disesuaikan dengan kebutuhan project.")]
        elif group.get("no_roster"):
            right_col = [note_card(
                "Hubungi kami untuk diskusi campaign &amp; rekomendasi talent yang sesuai — "
                "penawaran disesuaikan dengan kebutuhan project."
            )]
        elif rows_for_group:
            right_col = [pricing_card(rows_for_group)]
        else:
            right_col = [note_card("Hubungi kami untuk konsultasi kebutuhan &amp; penawaran.")]

        block = []
        block.extend(left_col)
        if left_col:
            block.append(Spacer(1, 6 * mm))
        block.extend(right_col)
        block.append(Spacer(1, 4 * mm))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 8 * mm))

    # ---------------- FINAL PAGE — CTA (dark) ----------------
    story.append(NextPageTemplate("Dark"))
    story.append(PageBreak())
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("SIAP TUMBUH BERSAMA", styles["KWCTATitle"]))
    story.append(Paragraph("KILAS WORKS?", styles["KWCoverTitleAccent"]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "Mari wujudkan ide, konten, dan strategi digital terbaik untuk bisnis Anda bersama kami.",
        styles["KWCTABody"],
    ))
    story.append(Spacer(1, 20 * mm))

    contact_lines = para(
        f"Client Hub &nbsp;&mdash;&nbsp; {official_links['app'].replace('https://', '')}<br/>"
        f"Website &nbsp;&mdash;&nbsp; {official_links['landing_page'].replace('https://', '')}<br/>"
        f"Instagram &nbsp;&mdash;&nbsp; {official_links['instagram'].replace('https://', '').replace('instagram.com/', '@')}",
        "KWCTAContact",
    )

    try:
        qr_widget = QrCodeWidget(official_links["app"])
        qr_bounds = qr_widget.getBounds()
        qr_w = qr_bounds[2] - qr_bounds[0]
        qr_h = qr_bounds[3] - qr_bounds[1]
        qr_drawing = Drawing(28 * mm, 28 * mm, transform=[28 * mm / qr_w, 0, 0, 28 * mm / qr_h, 0, 0])
        qr_drawing.add(qr_widget)
        cta_row = Table([[contact_lines, qr_drawing]], colWidths=[110 * mm, 30 * mm])
    except Exception as e:
        print(f"QR code generation gagal ({e}) — CTA page ditampilkan tanpa QR, link teks tetap ada.")
        cta_row = Table([[contact_lines]], colWidths=[140 * mm])
    cta_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(cta_row)
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph("K &nbsp;KILAS WORKS", styles["KWCoverBrand"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Tangerang &amp; Jakarta, Indonesia", styles["KWCoverFooter"]))

    doc.build(story)
    return buf.getvalue()


def get_cached_catalog_pdf_path(force=False):
    """Returns a filesystem path to an up-to-date catalog PDF, regenerating on disk only when the
    cache is missing, stale (catalog_cache.get_version() moved), or `force=True` (used by the
    admin 'Regenerate Catalog' action). Returns None only if generation itself fails (e.g.
    reportlab not installed) — callers must treat that as 'live catalog unavailable' and fall back
    to whatever static PDF mechanism they already have, never crash."""
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
        print(f"live_catalog_pdf: gagal generate katalog live ({e}) — caller sebaiknya fallback ke katalog statis.")
        return None
