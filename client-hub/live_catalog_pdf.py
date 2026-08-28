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
import talent_service

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")
_CACHE_PATH = os.path.join(_CACHE_DIR, "katalog_live.pdf")
_CACHE_STATE = {"version": None, "path": None}

_CUSTOM_QUOTE_ONLY_CATEGORIES = ("PHOTO", "VIDEO", "TALENT")


def generate_catalog_pdf_bytes():
    """Builds the current catalog PDF from live DB state and returns it as raw bytes (never writes
    to disk itself — callers decide whether/where to cache)."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
    )

    items = catalog_service.list_active_catalog()
    talents = talent_service.list_active_talents()

    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    ORANGE = colors.HexColor("#E8622C")
    DARK = colors.HexColor("#1A1A1A")
    GREY = colors.HexColor("#555555")
    LIGHT_BG = colors.HexColor("#F5F3F0")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="KWTitle", fontSize=24, leading=28, textColor=DARK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWSubtitle", fontSize=11, leading=15, textColor=GREY, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWSection", fontSize=14, leading=18, textColor=ORANGE, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle(name="KWNote", fontSize=8.5, leading=12, textColor=GREY, fontName="Helvetica-Oblique"))
    styles.add(ParagraphStyle(name="KWBody", fontSize=9.5, leading=13.5, textColor=DARK, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCell", fontSize=9, leading=12.5, textColor=DARK, fontName="Helvetica"))
    styles.add(ParagraphStyle(name="KWCellBold", fontSize=9.5, leading=12.5, textColor=DARK, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCellPrice", fontSize=9.5, leading=12.5, textColor=ORANGE, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="KWCellHead", fontSize=9.5, leading=12.5, textColor=colors.white, fontName="Helvetica-Bold"))

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

    story = []
    story.append(Paragraph("KILAS WORKS", styles["KWTitle"]))
    story.append(Paragraph("Katalog Layanan &amp; Harga — Content, AI &amp; Digital Solutions", styles["KWSubtitle"]))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.4, color=ORANGE))
    story.append(Spacer(1, 6 * mm))

    category_labels = {
        "AI_ADMIN": "AI WHATSAPP ADMIN",
        "CONTENT": "CONTENT PACKAGES",
        "BUNDLE": "BUNDLE",
        "ADS": "META ADS",
        "WEBSITE": "WEBSITE",
        "EVENT": "EVENT PHOTO & VIDEO",
        "VIDEO": "VIDEO",
        "PHOTO": "PHOTO",
        "APPLICATION": "APPLICATION / CUSTOM SYSTEM",
        "TALENT": "TALENT MANAGEMENT",
    }
    # Fixed, deliberate section order (AI Admin first, Talent last before the closing note) rather
    # than whatever order categories happen to appear in the DB.
    category_order = ["AI_ADMIN", "CONTENT", "BUNDLE", "ADS", "WEBSITE", "EVENT", "VIDEO", "PHOTO",
                       "APPLICATION", "TALENT"]

    section_number = 1
    for category in category_order:
        rows_for_cat = by_category.get(category, [])
        if not rows_for_cat and category != "TALENT":
            continue
        title = category_labels.get(category, category)

        if category in _CUSTOM_QUOTE_ONLY_CATEGORIES and category != "TALENT":
            # Photo/Video: always Custom Quote, never a public number — even if a row somehow
            # carries a stray price_amount, this section never prints it.
            body = [
                Paragraph(
                    f"{title.title()} sifatnya custom quote — harga tergantung kebutuhan campaign/"
                    "project. Hubungi kami untuk konsultasi & penawaran.",
                    styles["KWBody"],
                ),
            ]
            story.append(KeepTogether(
                [Paragraph(f"{section_number}. {title}", styles["KWSection"])] + body + [Spacer(1, 5 * mm)]
            ))
            section_number += 1
            continue

        if category == "TALENT":
            body = []
            if talents:
                talent_lines = "<br/>".join(
                    f"&bull; <b>{t['name']}</b>"
                    + (f" ({t['social_handle']})" if t.get("social_handle") else "")
                    + (f" — {'{:,}'.format(t['follower_count']).replace(',', '.')} followers" if t.get("follower_count") else "")
                    + (f", {t['niche']}" if t.get("niche") else "")
                    for t in talents
                )
                body.append(Paragraph(
                    "Kilas Works juga membuka kerja sama endorsement/kolaborasi konten dengan talent berikut:",
                    styles["KWBody"],
                ))
                body.append(Spacer(1, 2 * mm))
                body.append(Paragraph(talent_lines, styles["KWBody"]))
                body.append(Spacer(1, 2 * mm))
                body.append(Paragraph(
                    "<i>Follower count dapat berubah. Harga dan ketersediaan tergantung kebutuhan campaign.</i>",
                    styles["KWNote"],
                ))
            else:
                body.append(Paragraph(
                    "Kilas Works membuka kerja sama endorsement/kolaborasi konten dengan talent pilihan — "
                    "hubungi kami untuk daftar talent terkini.",
                    styles["KWBody"],
                ))
            body.append(Spacer(1, 2 * mm))
            body.append(Paragraph(
                "<b>Harga:</b> Custom quote — tergantung jenis campaign, jumlah konten, dan kebutuhan "
                "brand. Hubungi kami untuk konsultasi &amp; penawaran.",
                styles["KWNote"],
            ))
            story.append(KeepTogether(
                [Paragraph(f"{section_number}. {title}", styles["KWSection"])] + body + [Spacer(1, 6 * mm)]
            ))
            section_number += 1
            continue

        # Generic fixed-price-or-custom-quote table for every other category (AI_ADMIN, CONTENT,
        # BUNDLE, ADS, WEBSITE, EVENT, APPLICATION).
        rows = [header_row(["Layanan", "Harga", "Mode"])]
        for it in rows_for_cat:
            price_label = catalog_service.format_price(it.get("price_amount"), it.get("price_unit"))
            mode_label = "Custom Quote" if it["pricing_mode"] == "CUSTOM_QUOTE" else "Fixed"
            rows.append([
                cell(it["name"], "KWCellBold"),
                cell(price_label, "KWCellPrice" if it["pricing_mode"] != "CUSTOM_QUOTE" else "KWCell"),
                cell(mode_label),
            ])
        body = [pkg_table(rows, [70 * mm, 55 * mm, 40 * mm])]
        story.append(KeepTogether(
            [Paragraph(f"{section_number}. {title}", styles["KWSection"])] + body + [Spacer(1, 5 * mm)]
        ))
        section_number += 1

    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#CCCCCC")))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Semua harga berlaku sampai pemberitahuan lebih lanjut. Kebutuhan di luar cakupan paket di "
        "atas bisa didiskusikan langsung dengan tim kami. Hubungi kami via WhatsApp untuk konsultasi "
        "lebih lanjut.",
        styles["KWNote"],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "<b>Kilas Works</b> — Tangerang &amp; Jakarta, Indonesia &middot; instagram.com/kilasworks &middot; kilasworks.id",
        styles["KWNote"],
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
        title="Katalog Layanan & Harga Kilas Works",
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
