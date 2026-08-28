"""
Generate katalog.pdf LANGSUNG dari PRICING_CONFIG di app.py — SATU sumber data yang sama dipakai
AI WhatsApp Admin (SYSTEM_PROMPT) & katalog PDF ini, biar gak ada lagi harga beda-beda antar tempat.

Business Hub V2, Phase I (Section 27/33): Section 9 (TALENT MANAGEMENT) di bawah dibaca dari
client-hub/talent_service.py's SEED_TALENTS — bukan angka harga (talent SELALU CUSTOM_QUOTE, tidak
pernah ada harga di katalog ini), hanya nama/handle/follower count untuk tujuan marketing. Ini
HANYA membaca modul (import python biasa), TIDAK menyentuh ../app.py (bot produksi) sama sekali dan
TIDAK menjalankan/mengubah perilaku bot apapun — satu-satunya efek dari script ini adalah menulis
ulang file statis katalog.pdf di disk. Sama seperti PRICING_CONFIG, follower count di sini adalah
snapshot pada saat generate — kalau admin mengubah follower count lewat Client Hub, PDF ini perlu
di-generate ulang secara manual (limitasi yang sama dengan duplikasi PRICING_CONFIG, lihat
BOT_INTEGRATION_GUIDE.md).

Jalanin: python3 generate_katalog_pdf.py
Ini bikin ulang file katalog.pdf di folder yang sama (replace file lama).
"""
import os
import sys

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "placeholder")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "placeholder")
os.environ.setdefault("ANTHROPIC_API_KEY", "placeholder")
os.environ.setdefault("VERIFY_TOKEN", "placeholder")

import app as appmod  # import SATU-SATUNYA sumber data pricing (PRICING_CONFIG)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import talent_service  # noqa: E402 — hanya untuk baca SEED_TALENTS (nama/handle/followers), no I/O

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)

cfg = appmod.PRICING_CONFIG
fmt = appmod.format_price_full

ORANGE = colors.HexColor("#E8622C")
DARK = colors.HexColor("#1A1A1A")
GREY = colors.HexColor("#555555")
LIGHT_BG = colors.HexColor("#F5F3F0")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="KWTitle", fontSize=24, leading=28, textColor=DARK, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWSubtitle", fontSize=11, leading=15, textColor=GREY, fontName="Helvetica"))
styles.add(ParagraphStyle(name="KWSection", fontSize=14, leading=18, textColor=ORANGE, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6))
styles.add(ParagraphStyle(name="KWPakName", fontSize=12.5, leading=15, textColor=DARK, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWPrice", fontSize=13, leading=16, textColor=ORANGE, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWBody", fontSize=9.5, leading=13.5, textColor=DARK, fontName="Helvetica"))
styles.add(ParagraphStyle(name="KWNote", fontSize=8.5, leading=12, textColor=GREY, fontName="Helvetica-Oblique"))
styles.add(ParagraphStyle(name="KWCell", fontSize=9, leading=12.5, textColor=DARK, fontName="Helvetica"))
styles.add(ParagraphStyle(name="KWCellBold", fontSize=9.5, leading=12.5, textColor=DARK, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWCellPrice", fontSize=9.5, leading=12.5, textColor=ORANGE, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWCellHead", fontSize=9.5, leading=12.5, textColor=colors.white, fontName="Helvetica-Bold"))

story = []


def cell(text, style="KWCell"):
    return Paragraph(text, styles[style])


def header_row(labels):
    return [cell(l, "KWCellHead") for l in labels]

story.append(Paragraph("KILAS WORKS", styles["KWTitle"]))
story.append(Paragraph("Katalog Layanan &amp; Harga — Content, AI &amp; Digital Solutions", styles["KWSubtitle"]))
story.append(Spacer(1, 4 * mm))
story.append(HRFlowable(width="100%", thickness=1.4, color=ORANGE))
story.append(Spacer(1, 6 * mm))


def bullet_list(items):
    return "<br/>".join(f"&bull; {i}" for i in items)


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


def section(number_label, title, body_flowables, gap_after=5 * mm):
    """Bungkus judul section + isinya (table/paragraph) pakai KeepTogether biar section pendek gak
    kepotong ganjil antar halaman (judul kepisah dari isinya) — ini yang bikin komposisi katalog
    tetap satu kesatuan rapi walau lebih dari 1 halaman."""
    block = [Paragraph(f"{number_label}. {title}", styles["KWSection"])] + body_flowables + [Spacer(1, gap_after)]
    story.append(KeepTogether(block))


# ===== 1. AI WHATSAPP ADMIN (Basic vs Pro) =====
ai_basic = cfg["ai_admin"]["basic"]
ai_pro = cfg["ai_admin"]["pro"]
ai_body = []
for tier in (ai_basic, ai_pro):
    ai_body.append(Paragraph(f"{tier['nama']}", styles["KWPakName"]))
    ai_body.append(Paragraph(f"{fmt(tier['harga'])} / {tier['satuan']}  <font size=8 color='#777777'>({tier['catatan']})</font>", styles["KWPrice"]))
    ai_body.append(Spacer(1, 1.5 * mm))
    ai_body.append(Paragraph(f"<i>{tier['positioning']}</i>", styles["KWNote"]))
    ai_body.append(Spacer(1, 1.5 * mm))
    ai_body.append(Paragraph("<b>Yang didapat:</b><br/>" + bullet_list(tier["fitur"]), styles["KWBody"]))
    ai_body.append(Spacer(1, 3 * mm))
ai_body.append(Paragraph(
    "<b>Tidak termasuk di kedua paket AI Admin:</b> " + ", ".join(ai_pro["tidak_termasuk"]) +
    " — di luar paket ini, bisa didiskusikan terpisah dengan tim sesuai kebutuhan.",
    styles["KWNote"],
))
section("1", "AI WHATSAPP ADMIN — BASIC vs PRO", ai_body)

# ===== 2. CONTENT PACKAGES =====
rows = [header_row(["Paket", "Harga/bulan", "Deliverables"])]
for key in ("basic", "growth", "pro"):
    p = cfg["content_packages"][key]
    name = p["nama"] + (" — Paling Diminati" if p.get("most_popular") else "")
    rows.append([cell(name, "KWCellBold"), cell(fmt(p["harga"]), "KWCellPrice"), cell(", ".join(p["deliverables"]))])
section("2", "CONTENT PACKAGES", [
    pkg_table(rows, [42 * mm, 26 * mm, 97 * mm]),
    Spacer(1, 2 * mm),
    Paragraph(f"<b>Catatan Static Visual:</b> {cfg['static_visual_note']}", styles["KWNote"]),
])

# ===== 3. CONTENT + AI ADMIN BUNDLE =====
rows = [header_row(["Bundle", "Harga/bulan", "Isi"])]
for key in ("growth_ai_basic", "growth_ai", "pro_ai"):
    b = cfg["bundles"][key]
    rows.append([cell(b["nama"], "KWCellBold"), cell(fmt(b["harga"]), "KWCellPrice"), cell(" + ".join(b["isi"]))])
section("3", "CONTENT + AI ADMIN BUNDLE", [pkg_table(rows, [42 * mm, 26 * mm, 97 * mm])])

# ===== 4. META ADS =====
ma = cfg["meta_ads"]
mgmt = ma["management"]
setup = ma["setup_only"]
section("4", "META ADS", [
    Paragraph(f"{mgmt['nama']} <font size=8 color='#777777'>({mgmt['fokus']})</font>", styles["KWPakName"]),
    Paragraph(f"{fmt(mgmt['harga'])} / {mgmt['satuan']}", styles["KWPrice"]),
    Spacer(1, 2 * mm),
    Paragraph("<b>Yang didapat:</b><br/>" + bullet_list(mgmt["fitur"]), styles["KWBody"]),
    Spacer(1, 2 * mm),
    Paragraph(f"<b>Catatan:</b> {mgmt['catatan']}", styles["KWNote"]),
    Spacer(1, 4 * mm),
    Paragraph(f"<b>{setup['nama']}</b> — {fmt(setup['harga'])} ({setup['satuan']})", styles["KWPakName"]),
    Paragraph(setup["deskripsi"], styles["KWBody"]),
    Spacer(1, 2 * mm),
    Paragraph(f"<b>Penting:</b> {ma['no_guarantee_note']}", styles["KWNote"]),
])

# ===== 5. ADS BUNDLES =====
ab = cfg["ads_bundles"]
rows = [header_row(["Bundle", "Harga", "Isi"])]
for key in ("ai_basic_ads", "ai_ads", "growth_ai_ads", "pro_ai_ads"):
    b = ab[key]
    label = b["nama"] + (" — Direkomendasikan" if b.get("recommended") else "")
    rows.append([cell(label, "KWCellBold"), cell(fmt(b["harga"]) + "/bulan", "KWCellPrice"), cell(" + ".join(b["isi"]))])
alp = ab["ads_landing_page"]
rows.append([
    cell(alp["nama"], "KWCellBold"),
    cell(fmt(alp["harga"]) + f" ({alp['satuan']})", "KWCellPrice"),
    cell(" + ".join(alp["isi"]) + f" — {alp['catatan_lanjutan']}"),
])
section("5", "ADS BUNDLES", [
    pkg_table(rows, [42 * mm, 36 * mm, 87 * mm]),
    Spacer(1, 2 * mm),
    Paragraph(f"<b>Catatan:</b> {ab['ad_spend_note']}", styles["KWNote"]),
])

# ===== 6. WEBSITE =====
w = cfg["website"]
rows = [
    header_row(["Layanan", "Harga", "Keterangan"]),
    [cell(w["landing_page"]["nama"], "KWCellBold"), cell(fmt(w["landing_page"]["harga"]), "KWCellPrice"), cell(w["landing_page"]["deskripsi"])],
    [cell(w["company_profile"]["nama"], "KWCellBold"), cell(fmt(w["company_profile"]["harga"]), "KWCellPrice"), cell(w["company_profile"]["deskripsi"])],
    [cell(w["halaman_tambahan"]["nama"], "KWCellBold"), cell(fmt(w["halaman_tambahan"]["harga"]) + " / halaman", "KWCellPrice"), cell("Tambahan halaman di luar paket dasar")],
    [cell(w["maintenance"]["nama"], "KWCellBold"), cell(fmt(w["maintenance"]["harga"]) + " / bulan", "KWCellPrice"), cell(w["maintenance"]["deskripsi"])],
]
section("6", "WEBSITE", [pkg_table(rows, [38 * mm, 26 * mm, 101 * mm])])

# ===== 7. DOMAIN & HOSTING =====
dh = cfg["domain_hosting"]
rows = [
    header_row(["Paket", "Harga/tahun", "Termasuk"]),
    [cell(dh["com"]["nama"], "KWCellBold"), cell(fmt(dh["com"]["harga"]), "KWCellPrice"), cell(", ".join(dh["termasuk"]))],
    [cell(dh["id"]["nama"], "KWCellBold"), cell(fmt(dh["id"]["harga"]), "KWCellPrice"), cell(", ".join(dh["termasuk"]))],
]
section("7", "DOMAIN &amp; HOSTING", [
    Paragraph("Opsional, terpisah dari harga jasa pembuatan website.", styles["KWNote"]),
    Spacer(1, 2 * mm),
    pkg_table(rows, [38 * mm, 26 * mm, 101 * mm]),
    Spacer(1, 2 * mm),
    Paragraph(dh["catatan"], styles["KWNote"]),
])

# ===== 8. EVENT PHOTO & VIDEO =====
ev = cfg["event"]
rows = [header_row(["Paket", "Harga", "Detail"])]
for key, label in (("standard", "Acara Standard"), ("lengkap", "Acara Lengkap — Paling Diminati"), ("premium", "Acara Premium")):
    e = ev[key]
    rows.append([cell(label, "KWCellBold"), cell(fmt(e["harga"]), "KWCellPrice"), cell(e["deskripsi"])])
ta = cfg["transport_acara"]
section("8", "EVENT PHOTO &amp; VIDEO", [
    pkg_table(rows, [46 * mm, 26 * mm, 93 * mm]),
    Spacer(1, 2 * mm),
    Paragraph(
        f"<b>Biaya transport:</b> Tangerang &amp; Jakarta gratis. Bandung +{fmt(ta['bandung'])} flat. {ta['notes']}",
        styles["KWNote"],
    ),
], gap_after=6 * mm)

# ===== 9. TALENT MANAGEMENT =====
# Section 15/27 dari spec: publik SELALU custom quote, TIDAK PERNAH ada angka harga di sini.
# Follower count murni informasi marketing, editable oleh admin lewat Client Hub (lihat catatan
# di atas file ini) — bukan realtime, bukan hardcode kode program.
talent_rows = "<br/>".join(
    f"&bull; <b>{t['name']}</b> ({t['social_handle']}) — "
    f"{'{:,}'.format(t['follower_count']).replace(',', '.')} followers, {t['niche']}"
    for t in talent_service.SEED_TALENTS
)
section("9", "TALENT MANAGEMENT", [
    Paragraph(
        "Kilas Works juga membuka kerja sama endorsement/kolaborasi konten dengan talent berikut:",
        styles["KWBody"],
    ),
    Spacer(1, 2 * mm),
    Paragraph(talent_rows, styles["KWBody"]),
    Spacer(1, 2 * mm),
    Paragraph(f"<i>{talent_service.PUBLIC_DISCLAIMER}</i>", styles["KWNote"]),
    Spacer(1, 2 * mm),
    Paragraph(
        "<b>Harga:</b> Custom quote — tergantung jenis campaign, jumlah konten, dan kebutuhan brand. "
        "Hubungi kami untuk konsultasi & penawaran.",
        styles["KWNote"],
    ),
], gap_after=6 * mm)

story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#CCCCCC")))
story.append(Spacer(1, 3 * mm))
story.append(Paragraph(
    "Semua harga berlaku sampai pemberitahuan lebih lanjut. Kebutuhan di luar cakupan paket di atas bisa "
    "didiskusikan langsung dengan tim kami. Hubungi kami via WhatsApp untuk konsultasi lebih lanjut.",
    styles["KWNote"],
))
story.append(Spacer(1, 2 * mm))
story.append(Paragraph("<b>Kilas Works</b> — Tangerang &amp; Jakarta, Indonesia · instagram.com/kilasworks · kilasworks.id", styles["KWNote"]))

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "katalog.pdf")
doc = SimpleDocTemplate(
    OUT_PATH, pagesize=A4,
    topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    title="Katalog Layanan & Harga Kilas Works",
)
doc.build(story)
print(f"Katalog PDF berhasil di-generate: {OUT_PATH}")
