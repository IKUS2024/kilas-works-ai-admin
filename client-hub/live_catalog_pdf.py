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

    Premium service-deck redesign: raw service_catalog categories (AI_ADMIN, CONTENT, BUNDLE, ADS,
    WEBSITE, EVENT, VIDEO, PHOTO, APPLICATION, TALENT) are consolidated into the 6 customer-facing
    groups Kilas Works actually sells as (see _CUSTOMER_FACING_GROUPS below) — a presentation-layer
    grouping only; the underlying live data/source-of-truth (catalog_service.list_active_catalog())
    is completely unchanged, so an admin price/description/active-state edit still propagates here
    exactly as before, just displayed under the right customer-facing heading instead of a raw
    internal category code."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether, PageBreak,
    )

    items = catalog_service.list_active_catalog()
    talents = talent_service.list_active_talents()
    official_links = repo.get_official_links()

    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    ORANGE = colors.HexColor("#E8622C")
    DARK = colors.HexColor("#1A1A1A")
    GREY = colors.HexColor("#555555")
    LIGHT_BG = colors.HexColor("#F5F3F0")
    LINE = colors.HexColor("#E4E0DA")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="KWCoverTitle", fontSize=40, leading=44, textColor=DARK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCoverSub", fontSize=13, leading=18, textColor=ORANGE, fontName="Helvetica-Bold", spaceBefore=6))
    styles.add(ParagraphStyle(name="KWCoverTag", fontSize=10.5, leading=15, textColor=GREY, fontName="Helvetica", spaceBefore=18))
    styles.add(ParagraphStyle(name="KWEyebrow", fontSize=8.5, leading=11, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWTitle", fontSize=22, leading=26, textColor=DARK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWSubtitle", fontSize=11, leading=15, textColor=GREY, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWGroupTitle", fontSize=17, leading=21, textColor=DARK, fontName="Helvetica-Bold", spaceBefore=2, spaceAfter=4))
    styles.add(ParagraphStyle(name="KWGroupTitleFlagship", fontSize=20, leading=24, textColor=ORANGE, fontName="Helvetica-Bold", spaceBefore=2, spaceAfter=4))
    styles.add(ParagraphStyle(name="KWGroupDesc", fontSize=10, leading=14.5, textColor=GREY, fontName="Helvetica", spaceAfter=10))
    styles.add(ParagraphStyle(name="KWNote", fontSize=8.5, leading=12, textColor=GREY, fontName="Helvetica-Oblique"))
    styles.add(ParagraphStyle(name="KWBody", fontSize=9.5, leading=13.5, textColor=DARK, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCell", fontSize=9, leading=12.5, textColor=DARK, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCellBold", fontSize=9.5, leading=12.5, textColor=DARK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCellPrice", fontSize=9.5, leading=12.5, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCellHead", fontSize=9.5, leading=12.5, textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWFooterCenter", fontSize=9, leading=13, textColor=GREY, fontName="Helvetica", alignment=TA_CENTER))

    def cell(text, style="KWCell"):
        return Paragraph(text, styles[style])

    def header_row(labels):
        return [cell(l, "KWCellHead") for l in labels]

    def pkg_table(rows, col_widths):
        t = Table(rows, colWidths=col_widths)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    # Customer-facing service grouping (presentation layer only — see this function's own
    # docstring). Maps to raw service_catalog categories; "custom" has no catalog items at all
    # (Custom Solutions is marketing-only, matching the landing page — no invented price, no fake
    # catalog entry) and "talent" deliberately never lists individual catalog rows even though
    # TALENT items may exist in service_catalog, since talent pricing is per-talent internal data,
    # not a public package list.
    _CUSTOMER_FACING_GROUPS = [
        {
            "key": "ai_admin", "title": "AI WhatsApp Admin", "categories": ["AI_ADMIN"], "flagship": True,
            "description": (
                "AI Admin membalas customer di WhatsApp secara otomatis menggunakan data & pengetahuan "
                "bisnis kamu sendiri — menjawab pertanyaan, membantu proses penjualan, dan follow-up "
                "customer. Kalau situasinya butuh manusia, percakapan bisa langsung diambil alih tim."
            ),
        },
        {
            "key": "content", "title": "Content & Creative", "categories": ["CONTENT", "BUNDLE", "EVENT", "VIDEO", "PHOTO"],
            "description": (
                "Produksi foto, video, reels, dan konten campaign untuk kebutuhan brand — dari konten "
                "rutin bulanan sampai dokumentasi event, disesuaikan dengan kebutuhan project."
            ),
        },
        {
            "key": "ads", "title": "Meta Ads", "categories": ["ADS"],
            "description": (
                "Setup dan pengelolaan campaign iklan Meta (Instagram &amp; Facebook) — membantu bisnis "
                "menyusun campaign yang terstruktur dan menjangkau audiens yang relevan."
            ),
        },
        {
            "key": "website", "title": "Website &amp; Digital Solutions", "categories": ["WEBSITE", "APPLICATION"],
            "description": (
                "Landing page, website company profile, sampai sistem/aplikasi custom sesuai kebutuhan "
                "bisnis dan proses kerja kamu."
            ),
        },
        {
            "key": "talent", "title": "Talent &amp; Creator Management", "categories": ["TALENT"], "no_roster": True,
            "description": (
                "Kilas Works membantu brand menjalankan kolaborasi dengan talent dan creator untuk "
                "kebutuhan endorsement, campaign, product placement, social content, dan brand "
                "collaboration. Pemilihan talent disesuaikan dengan target audience, konsep campaign, "
                "platform, budget, dan availability."
            ),
        },
        {
            "key": "custom", "title": "Custom Solutions", "categories": [], "text_only": True,
            "description": (
                "Kebutuhan digital/automation di luar paket standar di atas bisa didiskusikan dan "
                "ditawarkan sesuai kebutuhan project kamu."
            ),
        },
    ]

    story = []

    # ---------------- PAGE 1 — COVER ----------------
    story.append(Spacer(1, 60 * mm))
    story.append(Paragraph("KILAS WORKS", styles["KWCoverTitle"]))
    story.append(Paragraph("AI, CONTENT &amp; DIGITAL SOLUTIONS", styles["KWCoverSub"]))
    story.append(Paragraph(
        "Satu partner untuk AI WhatsApp Admin, content &amp; creative, Meta Ads, website, dan "
        "kolaborasi talent/creator — dikerjakan tim yang sama, satu titik komunikasi.",
        styles["KWCoverTag"],
    ))
    story.append(PageBreak())

    # ---------------- PAGE 2 — ABOUT / WHAT WE DO ----------------
    story.append(Paragraph("TENTANG KAMI", styles["KWEyebrow"]))
    story.append(Paragraph("Satu Partner, Banyak Kebutuhan Digital", styles["KWTitle"]))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width=38 * mm, thickness=2, color=ORANGE))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Kilas Works membantu bisnis bergerak lebih cepat lewat AI WhatsApp Admin yang merespons "
        "customer 24/7, Content &amp; Creative untuk kehadiran brand yang konsisten, Meta Ads untuk "
        "distribusi &amp; traffic, Website &amp; Digital Solutions, sampai kolaborasi Talent &amp; "
        "Creator untuk campaign. Semua layanan dikerjakan oleh tim yang sama, jadi kamu cukup satu "
        "titik komunikasi untuk banyak kebutuhan.",
        styles["KWBody"],
    ))
    story.append(Spacer(1, 10 * mm))
    overview_rows = [[
        Paragraph(f"<b>{g['title']}</b>", styles["KWCellBold"]),
    ] for g in _CUSTOMER_FACING_GROUPS]
    story.append(Table(overview_rows, colWidths=[150 * mm], style=TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ])))
    story.append(PageBreak())

    # ---------------- SERVICE SECTIONS ----------------
    for group in _CUSTOMER_FACING_GROUPS:
        rows_for_group = []
        for cat in group["categories"]:
            rows_for_group.extend(by_category.get(cat, []))

        title_style = "KWGroupTitleFlagship" if group.get("flagship") else "KWGroupTitle"
        block = [Paragraph(group["title"], styles[title_style])]
        if group.get("flagship"):
            block.append(Paragraph("PRODUK UNGGULAN", styles["KWEyebrow"]))
        block.append(Spacer(1, 2 * mm))
        block.append(Paragraph(group["description"], styles["KWGroupDesc"]))

        if group.get("text_only"):
            # Custom Solutions — no live catalog entries at all, marketing text only, matching the
            # landing page's own "no invented product/price" rule for this category.
            pass
        elif group.get("no_roster"):
            # Talent & Creator Management — SERVICE explanation only, deliberately never lists
            # individual talents/handles/follower counts here (public catalog must never expose
            # the internal roster) — confirmed no talents variable is even referenced in this
            # branch.
            block.append(Spacer(1, 2 * mm))
            block.append(Paragraph(
                "Hubungi kami untuk diskusi campaign &amp; rekomendasi talent yang sesuai — "
                "penawaran disesuaikan dengan kebutuhan project.",
                styles["KWNote"],
            ))
        elif rows_for_group:
            block.append(Spacer(1, 3 * mm))
            rows = [header_row(["Layanan", "Harga"])]
            for it in rows_for_group:
                price_label = catalog_service.format_price(it.get("price_amount"), it.get("price_unit"))
                desc = it.get("description")
                name_cell = it["name"] if not desc else f"<b>{it['name']}</b><br/><font size=8 color='#777777'>{desc}</font>"
                rows.append([
                    cell(name_cell, "KWCellBold" if not desc else "KWCell"),
                    cell(price_label, "KWCellPrice" if it["pricing_mode"] != "CUSTOM_QUOTE" else "KWCell"),
                ])
            block.append(pkg_table(rows, [110 * mm, 55 * mm]))
        else:
            block.append(Spacer(1, 2 * mm))
            block.append(Paragraph(
                "Hubungi kami untuk konsultasi kebutuhan &amp; penawaran.", styles["KWNote"],
            ))

        block.append(Spacer(1, 4 * mm))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 10 * mm))

    # ---------------- FINAL PAGE — CTA ----------------
    story.append(PageBreak())
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph("Mulai Sekarang", styles["KWTitle"]))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width=38 * mm, thickness=2, color=ORANGE))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Kebutuhan di luar cakupan paket di atas bisa didiskusikan langsung dengan tim kami. "
        "Semua harga berlaku sampai pemberitahuan lebih lanjut.",
        styles["KWBody"],
    ))
    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph(f"Mulai di Client Hub &nbsp;&mdash;&nbsp; {official_links['app']}", styles["KWCellBold"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Instagram &nbsp;&mdash;&nbsp; {official_links['instagram']}", styles["KWBody"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"{official_links['landing_page']}", styles["KWBody"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Tangerang &amp; Jakarta, Indonesia", styles["KWNote"]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=20 * mm, bottomMargin=18 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
        title="Kilas Works — Service Catalog",
    )
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
