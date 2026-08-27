"""
Generate rencana-konten-hari-ini.pdf — brief produksi konten TikTok/IG Reels hari ini,
angle: promosi AI WhatsApp Admin. Talent: Irvan (owner) + Putri (2 orang aja).

Jalanin: python3 generate_content_brief_pdf.py
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    KeepTogether, PageBreak,
)

ORANGE = colors.HexColor("#E8622C")
DARK = colors.HexColor("#1A1A1A")
GREY = colors.HexColor("#555555")
LIGHT_BG = colors.HexColor("#F5F3F0")
GREEN = colors.HexColor("#2E7D32")

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rencana-konten-hari-ini.pdf")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="KWTitle", fontSize=23, leading=27, textColor=DARK, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWSubtitle", fontSize=11, leading=15, textColor=GREY, fontName="Helvetica"))
styles.add(ParagraphStyle(name="KWSection", fontSize=14, leading=18, textColor=ORANGE, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6))
styles.add(ParagraphStyle(name="KWSubSection", fontSize=11.5, leading=15, textColor=DARK, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3))
styles.add(ParagraphStyle(name="KWBody", fontSize=9.5, leading=14, textColor=DARK, fontName="Helvetica"))
styles.add(ParagraphStyle(name="KWNote", fontSize=8.5, leading=12, textColor=GREY, fontName="Helvetica-Oblique"))
styles.add(ParagraphStyle(name="KWCell", fontSize=9, leading=13, textColor=DARK, fontName="Helvetica"))
styles.add(ParagraphStyle(name="KWCellBold", fontSize=9.3, leading=13, textColor=DARK, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWCellHead", fontSize=9.3, leading=13, textColor=colors.white, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle(name="KWHook", fontSize=12.5, leading=17, textColor=ORANGE, fontName="Helvetica-BoldOblique"))
styles.add(ParagraphStyle(name="KWTag", fontSize=8.5, leading=12, textColor=colors.white, fontName="Helvetica-Bold"))

story = []


def cell(text, style="KWCell"):
    return Paragraph(text, styles[style])


def header_row(labels):
    return [cell(l, "KWCellHead") for l in labels]


def table(rows, col_widths, header=True):
    t = Table(rows, colWidths=col_widths)
    style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]
    if header:
        style_cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ]
    t.setStyle(TableStyle(style_cmds))
    return t


def bullets(items):
    return "<br/>".join(f"&bull; {i}" for i in items)


def section(number_label, title, body_flowables, gap_after=6 * mm):
    block = [Paragraph(f"{number_label}  {title}", styles["KWSection"])] + body_flowables + [Spacer(1, gap_after)]
    story.append(KeepTogether(block))


# ---------------- COVER ----------------
story.append(Paragraph("KILAS WORKS", styles["KWTitle"]))
story.append(Paragraph("Rencana Konten Hari Ini — Promosi AI WhatsApp Admin", styles["KWSubtitle"]))
story.append(Spacer(1, 2 * mm))
story.append(Paragraph("Talent: Irvan (owner) &amp; Putri  |  Platform: TikTok &amp; Instagram Reels", styles["KWNote"]))
story.append(Spacer(1, 4 * mm))
story.append(HRFlowable(width="100%", thickness=1.4, color=ORANGE))
story.append(Spacer(1, 6 * mm))

# ---------------- GOAL ----------------
section(
    "0.",
    "Goal &amp; Angle Hari Ini",
    [
        Paragraph(
            "Angle: <b>Promosi AI WhatsApp Admin</b> (paket Rp999rb/bulan) dengan gaya problem &rarr; solution. "
            "Target: orang yang punya bisnis/online shop dan ngerasa capek/lambat balesin chat customer. "
            "Karena talent cuma berdua (Irvan &amp; Putri), semua konsep di bawah didesain supaya bisa dieksekusi "
            "hanya dengan 2 orang — satu jadi talent di depan kamera, satu pegang kamera/HP sekaligus bisa gantian jadi talent kedua.",
            styles["KWBody"],
        ),
    ],
)

# ---------------- CONCEPT A ----------------
concept_a_body = [
    Paragraph('Hook (0-2 detik): "Kalau chat masuk jam 11 malem, siapa yang bales?"', styles["KWHook"]),
    Spacer(1, 2 * mm),
    Paragraph("<b>Format:</b> Skit problem-solution, dialog Irvan + Putri, direkam pakai 1 HP di tripod/disandarin.", styles["KWBody"]),
    Spacer(1, 2 * mm),
    table(
        [
            header_row(["Waktu", "Siapa di kamera", "Yang dilakukan / dialog"]),
            [cell("0:00-0:02"), cell("Irvan", "KWCellBold"), cell("Ngomong ke kamera sambil pegang HP: \"Kalau chat masuk jam 11 malem, siapa yang bales?\" — ekspresi capek/mikir.")],
            [cell("0:02-0:06"), cell("Putri", "KWCellBold"), cell("Cut ke Putri lagi scroll WA Business penuh chat numpuk, banyak centang abu-abu belum dibales. Teks overlay: \"47 chat numpuk\"")],
            [cell("0:06-0:10"), cell("Irvan", "KWCellBold"), cell("Irvan: \"Makanya sekarang aku pake AI Admin buat WhatsApp bisnis.\" — nunjukin HP ke kamera.")],
            [cell("0:10-0:18"), cell("Screen record", "KWCellBold"), cell("Screen-record chat WA: customer nanya \"Ada promo bulan ini kak?\" lalu AI langsung balas natural dalam hitungan detik. Overlay teks: \"Bales 24/7 — otomatis\"")],
            [cell("0:18-0:23"), cell("Putri", "KWCellBold"), cell("Putri liat HP-nya udah kosong/rapi (chat udah dijawab semua), senyum lega ke kamera.")],
            [cell("0:23-0:28"), cell("Irvan", "KWCellBold"), cell("CTA ke kamera: \"Mau bisnis kamu direspon secepat ini juga? Chat kita, link di bio.\" Card WA + logo Kilas Works muncul.")],
        ],
        [22 * mm, 26 * mm, 108 * mm],
    ),
    Spacer(1, 2 * mm),
    Paragraph("<b>Lagu:</b> \"Saxophones Getting Louder - Sped Up\" (AntonioVivald) — dipakai di bagian 0:02-0:06 pas nunjukin chat numpuk (kesan makin \"gawat\"/dramatis), lalu potong ke audio asli/VO pas bagian solusi (0:06 dst) biar pesan AI Admin-nya jelas kedengeran.", styles["KWBody"]),
    Paragraph("<b>Caption:</b> \"POV: bisnis kamu gak pernah tidur, tapi kamu butuh tidur. Kenalin AI WhatsApp Admin dari Kilas Works — bales chat 24/7, kualifikasi calon customer, sampe atur jadwal meeting. Chat kita buat coba demo-nya, link di bio.\"", styles["KWBody"]),
    Paragraph("<b>Hashtag:</b> #AIWhatsApp #WhatsAppBusiness #UMKM #OtomasiBisnis #KilasWorks #AIAdmin #BisnisOnline #TangerangBusiness", styles["KWNote"]),
]
section("1.", "Konsep A — \"Siapa yang Bales Jam 11 Malem?\" (Problem-Solution Skit)", concept_a_body)

# ---------------- CONCEPT B ----------------
concept_b_body = [
    Paragraph('Hook (0-2 detik): "Ini captain chat WhatsApp bisnis gw... yang bales bukan gw."', styles["KWHook"]),
    Spacer(1, 2 * mm),
    Paragraph("<b>Format:</b> POV chat demo + reaction, lebih santai/personal branding. Cocok kalau waktu shoot mepet karena bagian utamanya screen record.", styles["KWBody"]),
    Spacer(1, 2 * mm),
    table(
        [
            header_row(["Waktu", "Siapa di kamera", "Yang dilakukan / dialog"]),
            [cell("0:00-0:03"), cell("Irvan", "KWCellBold"), cell("Selfie-style langsung ke kamera: \"Ini chat WhatsApp bisnis gw... yang bales bukan gw.\"")],
            [cell("0:03-0:15"), cell("Screen record", "KWCellBold"), cell("Scroll chat asli/demo: AI jawab FAQ harga, jelasin paket, nanya kebutuhan customer, sampe nawarin jadwal konsultasi. Overlay teks nunjuk tiap balasan: \"Ini AI\", \"Ini juga AI\", \"Bukan gw yang ketik ini\"")],
            [cell("0:15-0:20"), cell("Putri", "KWCellBold"), cell("Putri masuk frame nunjuk HP Irvan sambil geleng-geleng takjub: \"Serius ini bukan lo yang bales?\" Irvan: \"Serius. AI-nya kerja pas kita lagi shoot juga.\"")],
            [cell("0:20-0:26"), cell("Irvan", "KWCellBold"), cell("CTA: \"Kalau lo juga capek pegang HP seharian buat bales chat, ini solusinya. Chat kita, link di bio.\"")],
        ],
        [22 * mm, 26 * mm, 108 * mm],
    ),
    Spacer(1, 2 * mm),
    Paragraph("<b>Lagu:</b> \"On a Mission\" (Duomo) — vibe dramatis/dokumenter, pas dipakai selama bagian screen-record chat (0:03-0:15) biar kerasa kayak lagi \"membongkar\" sesuatu yang menarik.", styles["KWBody"]),
    Paragraph("<b>Caption:</b> \"Gw gak bales chat ini. AI Admin dari Kilas Works yang bales — 24/7, natural, dan tetep bisa handoff ke gw kalau udah closing-ready. Mau coba di bisnis kamu?\"", styles["KWBody"]),
    Paragraph("<b>Hashtag:</b> #AIAdmin #ChatbotWhatsApp #AutomationBisnis #KilasWorks #SoloFounder #DigitalSolution #UMKMNaikKelas", styles["KWNote"]),
]
section("2.", "Konsep B — \"Bukan Gw yang Bales\" (Screen-Record Reveal)", concept_b_body)

# ---------------- CONCEPT C ----------------
concept_c_body = [
    Paragraph('Hook (0-2 detik): "3 tanda bisnis kamu butuh AI WhatsApp Admin."', styles["KWHook"]),
    Spacer(1, 2 * mm),
    Paragraph("<b>Format:</b> Listicle to-camera, paling cepat direkam kalau waktu paling mepet — cukup 1 talent di kamera (Irvan), Putri pegang HP/bantu retake.", styles["KWBody"]),
    Spacer(1, 2 * mm),
    table(
        [
            header_row(["Waktu", "Siapa di kamera", "Yang dilakukan / dialog"]),
            [cell("0:00-0:02"), cell("Irvan", "KWCellBold"), cell("\"3 tanda bisnis kamu butuh AI WhatsApp Admin.\"")],
            [cell("0:02-0:08"), cell("Irvan", "KWCellBold"), cell("\"Satu — chat numpuk pas kamu lagi tidur atau di luar kota.\" Overlay teks besar: \"1. CHAT NUMPUK\"")],
            [cell("0:08-0:14"), cell("Irvan", "KWCellBold"), cell("\"Dua — capek jawabin pertanyaan yang itu-itu aja tiap hari.\" Overlay: \"2. FAQ BERULANG\"")],
            [cell("0:14-0:20"), cell("Irvan", "KWCellBold"), cell("\"Tiga — banyak calon customer yang chat terus ilang gitu aja karena kelamaan direspon.\" Overlay: \"3. LEAD KABUR\"")],
            [cell("0:20-0:27"), cell("Putri", "KWCellBold"), cell("Cut ke Putri nunjukin demo chat AI Admin balesin dengan cepat di HP. Overlay: \"Solusinya: AI WhatsApp Admin — Rp999rb/bulan\"")],
            [cell("0:27-0:30"), cell("Irvan", "KWCellBold"), cell("CTA to-camera: \"Kalau salah satu ini kerasa relate, chat kita sekarang.\"")],
        ],
        [22 * mm, 26 * mm, 108 * mm],
    ),
    Spacer(1, 2 * mm),
    Paragraph("<b>Lagu:</b> \"Mind Blank\" (OTE feat. Zorro) — beat-nya universal dan gampang buat nge-cut tiap poin listicle (potongan di setiap \"drop\"/hentakan beat pas ganti angka 1/2/3).", styles["KWBody"]),
    Paragraph("<b>Caption:</b> \"Relate salah satu dari ini? AI WhatsApp Admin Kilas Works bantu bales chat 24/7, saring calon customer serius, dan kasih tau kamu pas ada yang udah siap closing. Chat kita buat mulai.\"", styles["KWBody"]),
    Paragraph("<b>Hashtag:</b> #TipsBisnis #AIWhatsApp #WhatsAppAdmin #UMKMIndonesia #KilasWorks #ContentCreator #BisnisDigital", styles["KWNote"]),
]
section("3.", "Konsep C — \"3 Tanda Butuh AI Admin\" (Listicle, Paling Cepat Digarap)", concept_c_body)

story.append(PageBreak())

# ---------------- SONG REFERENCE TABLE ----------------
song_rows = [
    header_row(["Lagu / Sound", "Vibe", "Paling cocok buat"]),
    [cell("Saxophones Getting Louder - Sped Up (AntonioVivald)"), cell("Dramatis, tegang, makin \"gawat\""), cell("Bagian nunjukin masalah (chat numpuk, notif menumpuk) — Konsep A")],
    [cell("On a Mission (Duomo)"), cell("Dokumenter, membongkar sesuatu"), cell("Bagian reveal/screen-record chat AI — Konsep B")],
    [cell("Mind Blank (OTE feat. Zorro)"), cell("Universal, enak buat cut per-poin"), cell("Listicle / tips 1-2-3 — Konsep C")],
    [cell("petal (Ariana Grande)"), cell("Feel-good, fleksibel"), cell("Versi lebih santai/personal branding, bukan hard-sell")],
    [cell("Original Audio - Sonicallygifted (klip Beyoncé)"), cell("Inspiratif, cerita di balik layar"), cell("Behind-the-scenes proses bikin AI Admin / cerita founder")],
]
section(
    "4.",
    "Referensi Lagu buat Edit",
    [
        Paragraph(
            "Data diambil dari daftar sound yang lagi trending di TikTok per Agustus 2026 (Buffer &amp; TokChart). "
            "Cara pakai: buka TikTok &rarr; search judul lagu di kolom sound &rarr; pilih yang paling banyak dipakai (video count tinggi) &rarr; \"Add to favorites\" biar gampang dicari lagi pas edit di CapCut.",
            styles["KWBody"],
        ),
        Spacer(1, 2 * mm),
        table(song_rows, [55 * mm, 40 * mm, 61 * mm]),
    ],
)

# ---------------- EDITING GUIDE ----------------
edit_body = [
    Paragraph("<b>Aplikasi:</b> CapCut (gratis, paling gampang buat pemula, ada auto-caption Bahasa Indonesia).", styles["KWBody"]),
    Spacer(1, 1.5 * mm),
    Paragraph("<b>Langkah edit (urutan kerja):</b>", styles["KWBody"]),
    Paragraph(
        bullets([
            "Import semua klip mentah (talking head + screen record), potong bagian yang gagal/kelamaan diam.",
            "Susun urutan sesuai timing di tabel konsep (jangan lebih dari 30 detik total — durasi ideal Reels/TikTok promosi jasa: 20-30 detik).",
            "Tambahin sound yang dipilih dari tabel referensi lagu, taruh di track audio paling bawah, volume di-lower dikit (sekitar 40-50%) kalau ada voice over yang harus jelas kedengeran.",
            "Auto-caption (fitur \"Auto captions\" di CapCut) buat semua dialog/VO — banyak orang nonton tanpa suara.",
            "Tambahin teks overlay di bagian penting (hook, angka statistik/poin, CTA) pakai font tebal, warna putih dengan outline/background gelap biar kebaca di semua background.",
            "Kasih 1 jump cut tiap 2-3 detik biar ritmenya cepat dan gak bikin bosan (khas format short-form).",
            "End card 2 detik terakhir: logo Kilas Works + tulisan \"Chat kita — link di bio\" atau nomor WhatsApp.",
            "Export rasio 9:16, resolusi 1080x1920, minimal 30fps.",
        ]),
        styles["KWBody"],
    ),
    Spacer(1, 1.5 * mm),
    Paragraph(
        "<b>Konsistensi brand:</b> teks overlay pakai warna oranye (#E8622C) untuk kata kunci/hook dan putih untuk teks biasa, "
        "di atas background gelap — biar konten Reels/TikTok kelihatan satu identitas sama landing page &amp; katalog Kilas Works.",
        styles["KWNote"],
    ),
]
section("5.", "Panduan Edit Singkat", edit_body)

# ---------------- POSTING CHECKLIST ----------------
posting_body = [
    Paragraph(
        bullets([
            "Post di TikTok dan Instagram Reels di jam yang sama (idealnya jam makan siang 12:00-13:00 atau malam 19:00-21:00 WIB).",
            "Pakai cover/thumbnail yang nunjukin wajah + teks hook, biar orang yang scroll feed langsung ke-tangkep isinya.",
            "Caption jangan lupa CTA jelas: \"Chat kita, link di bio\" atau cantumin nomor WhatsApp Kilas Works.",
            "Reply setiap komentar dalam 1 jam pertama (algoritma TikTok/IG kasih boost ke video yang engagement-nya cepat).",
            "Simpan link video ke story/highlight biar calon customer yang mampir profile bisa langsung nonton.",
        ]),
        styles["KWBody"],
    ),
]
section("6.", "Checklist Posting", posting_body)

# ---------------- DAILY PRODUCTION CHECKLIST ----------------
daily_rows = [
    header_row(["Waktu", "Kegiatan"]),
    [cell("15 menit"), cell("Setup: charge HP, siapin tripod/sandaran, cek pencahayaan (dekat jendela/lampu terang), siapin HP kedua buat screen-record demo chat AI Admin.")],
    [cell("20 menit"), cell("Syuting Konsep A atau C (pilih 1 dulu kalau waktu terbatas) — take 2-3 kali tiap adegan biar ada opsi pas edit.")],
    [cell("10 menit"), cell("Screen-record demo chat AI Admin (bisa dipakai ulang buat konsep manapun, jadi rekam sekali yang bagus).")],
    [cell("25 menit"), cell("Edit di CapCut: susun klip, sound, caption, teks overlay, end card.")],
    [cell("5 menit"), cell("Export &amp; upload ke TikTok + Instagram Reels sekaligus, isi caption &amp; hashtag dari brief ini.")],
]
section(
    "7.",
    "Timeline Produksi Hari Ini (2 Orang, ~75 Menit)",
    [
        Paragraph("Kalau waktu cuma cukup buat 1 video hari ini, prioritasin <b>Konsep A</b> (paling kuat problem-solution-nya) atau <b>Konsep C</b> (paling cepat digarap).", styles["KWBody"]),
        Spacer(1, 2 * mm),
        table(daily_rows, [22 * mm, 134 * mm]),
    ],
    gap_after=2 * mm,
)

story.append(Spacer(1, 4 * mm))
story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#CCCCCC")))
story.append(Spacer(1, 2 * mm))
story.append(Paragraph(
    "Referensi lagu diambil dari data trending TikTok Agustus 2026 (Buffer, TokChart) — sound/trend bisa berubah cepat, "
    "cek ulang tab \"Trending\" di TikTok Creation sebelum posting buat mastiin sound yang dipilih masih trending pas hari-H.",
    styles["KWNote"],
))

doc = SimpleDocTemplate(
    OUT_PATH, pagesize=A4,
    topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
)
doc.build(story)
print(f"Generated: {OUT_PATH}")
