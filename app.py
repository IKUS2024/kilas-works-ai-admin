import os
import re
import io
import json
import time
import base64
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

app = Flask(__name__)

# ==== KONFIGURASI (diambil dari environment variables) ====
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "kilasworks123")  # bebas, dipakai buat verifikasi webhook di Meta

# Password buat buka halaman dashboard (/dashboard?key=...). GANTI ini di environment variable
# Render, jangan pakai default di production.
DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "kilasworks-dashboard")

# Password buat trigger follow-up otomatis (/cron/followups?key=...). Endpoint ini HARUS dipanggil
# dari luar secara berkala (misal via cron-job.org tiap 1 jam) — Render gak bisa "bangunin dirinya
# sendiri" tiap 12 jam, jadi butuh trigger eksternal. Kalau kosong, fallback ke DASHBOARD_KEY.
CRON_SECRET = os.environ.get("CRON_SECRET", "") or DASHBOARD_KEY

# Connection string database Postgres (dari Supabase, dll). Kalau kosong, bot tetep jalan normal
# tapi history chat cuma kesimpen sementara di memori (ilang kalau server restart) — sama kayak
# sebelumnya. Isi env var ini di Render buat aktifin penyimpanan permanen.
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ==== DATABASE (opsional, buat nyimpen history chat secara permanen) ====

def db_enabled():
    return bool(DATABASE_URL) and psycopg2 is not None


def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    """Bikin tabel 'messages' kalau belum ada. Dipanggil sekali pas server start."""
    if not db_enabled():
        print("DATABASE_URL belum diset — history chat cuma kesimpen sementara di memori.")
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL,
                mode TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_number_mode ON messages (number, mode);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_profiles (
                number TEXT PRIMARY KEY,
                name TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_facts (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL,
                fact TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_facts_number ON customer_facts (number);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS followup_state (
                number TEXT PRIMARY KEY,
                last_customer_msg_at TIMESTAMPTZ,
                last_followup_at TIMESTAMPTZ,
                followup_count INTEGER NOT NULL DEFAULT 0,
                converted BOOLEAN NOT NULL DEFAULT FALSE
            );
            """
        )
        conn.commit()
        cur.close()
        conn.close()
        print("Database siap — history chat bakal kesimpen permanen.")
    except Exception as e:
        print(f"Gagal konek/init database ({e}). History chat cuma kesimpen sementara di memori.")


def save_message_to_db(number, mode, role, content):
    """Simpen satu pesan (dari customer/owner ATAU balasan AI) ke database. Kalau DB gak
    kekonek/gak diset, diem-diem gak ngapa-ngapain (bot tetep jalan normal)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (number, mode, role, content) VALUES (%s, %s, %s, %s)",
            (number, mode, role, content),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen pesan ke database ({e}).")


def load_recent_messages_from_db(number, mode, limit=20):
    """Ambil N pesan terakhir punya satu nomor dari database, buat isi ulang konteks chat
    AI pas server abis restart (jadi AI gak lupa obrolan sebelumnya)."""
    if not db_enabled():
        return []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM messages WHERE number = %s AND mode = %s "
            "ORDER BY id DESC LIMIT %s",
            (number, mode, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        rows.reverse()
        return [{"role": r[0], "content": r[1]} for r in rows]
    except Exception as e:
        print(f"Gagal ambil history dari database ({e}).")
        return []


def load_all_conversations_from_db(mode):
    """Ambil SEMUA history per nomor (dikelompokkin), dipakai buat nampilin dashboard biar
    tetep kelihatan lengkap walau server abis restart."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT number, role, content, created_at FROM messages WHERE mode = %s ORDER BY id ASC",
            (mode,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        grouped = {}
        for number, role, content, created_at in rows:
            grouped.setdefault(number, []).append(
                {"role": role, "content": content, "created_at": created_at}
            )
        return grouped
    except Exception as e:
        print(f"Gagal ambil semua history dari database ({e}).")
        return {}


def save_customer_name_to_db(number, name):
    """Simpen/update nama customer secara permanen. Kalau DB gak aktif, diem-diem gak ngapa-ngapain
    (nama tetep kesimpen sementara di cache in-memory `customer_names`)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO customer_profiles (number, name) VALUES (%s, %s)
            ON CONFLICT (number) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
            """,
            (number, name),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen nama customer ke database ({e}).")


def load_all_customer_names_from_db():
    """Ambil semua nama customer yang udah kesimpen, buat dipakai isi ulang cache pas server abis
    restart, dan buat disisipin ke konteks owner."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT number, name FROM customer_profiles")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {number: name for number, name in rows}
    except Exception as e:
        print(f"Gagal ambil nama customer dari database ({e}).")
        return {}


def save_customer_fact_to_db(number, fact):
    """Simpen satu 'fakta yang udah disepakati owner' buat customer tertentu (misal harga nego,
    keputusan lain) — permanen di DB, biar SELALU keinget & konsisten walau server restart, dan
    gak cuma ngandelin AI 'inget sendiri' dari histori chat freeform (yang kadang keliru)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO customer_facts (number, fact) VALUES (%s, %s)", (number, fact))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen fakta customer ke database ({e}).")


def load_all_customer_facts_from_db():
    """Ambil semua fakta yang udah disepakati per customer, dikelompokkin per nomor, buat isi
    ulang cache in-memory pas server abis restart."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT number, fact FROM customer_facts ORDER BY id ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        grouped = {}
        for number, fact in rows:
            grouped.setdefault(number, []).append(fact)
        return grouped
    except Exception as e:
        print(f"Gagal ambil fakta customer dari database ({e}).")
        return {}


def add_agreed_fact(number, fact):
    """Catet satu keputusan/kesepakatan yang UDAH FIX buat customer tertentu — dipanggil tiap kali
    owner beneran forward jawaban (baik lewat mode diskusi atau perintah langsung) ke customer.
    Ini disisipin ke system prompt customer sebagai daftar fakta yang GAK BOLEH dikontradiksi atau
    ditanyakan ulang, biar bot gak pernah lagi salah bilang 'belum dapet konfirmasi owner' padahal
    udah pernah dijawab."""
    agreed_facts.setdefault(number, [])
    agreed_facts[number].append(fact)
    agreed_facts[number] = agreed_facts[number][-15:]  # cukup 15 fakta terakhir per customer
    save_customer_fact_to_db(number, fact)


# ==== FOLLOW-UP OTOMATIS (chat lagi ke customer yang diem >12 jam) ====
# Maksimal berapa kali follow-up otomatis dikirim per customer sebelum berhenti (biar gak keliatan spam
# kalau customer emang udah gak minat/gak balas berkali-kali).
MAX_AUTO_FOLLOWUPS = 3
FOLLOWUP_GAP_HOURS = 12


def _utcnow():
    return datetime.now(timezone.utc)


def save_followup_state_to_db(number, state):
    """Simpen/update state follow-up satu customer ke DB (upsert)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO followup_state (number, last_customer_msg_at, last_followup_at, followup_count, converted)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (number) DO UPDATE SET
                last_customer_msg_at = EXCLUDED.last_customer_msg_at,
                last_followup_at = EXCLUDED.last_followup_at,
                followup_count = EXCLUDED.followup_count,
                converted = EXCLUDED.converted
            """,
            (
                number,
                state.get("last_customer_msg_at"),
                state.get("last_followup_at"),
                state.get("followup_count", 0),
                state.get("converted", False),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen followup_state ke database ({e}).")


def load_all_followup_state_from_db():
    """Ambil semua state follow-up dari DB, buat isi ulang cache in-memory pas server abis restart."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT number, last_customer_msg_at, last_followup_at, followup_count, converted FROM followup_state")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for number, last_customer_msg_at, last_followup_at, followup_count, converted in rows:
            result[number] = {
                "last_customer_msg_at": last_customer_msg_at,
                "last_followup_at": last_followup_at,
                "followup_count": followup_count,
                "converted": converted,
            }
        return result
    except Exception as e:
        print(f"Gagal ambil followup_state dari database ({e}).")
        return {}


def mark_customer_activity(number):
    """Dipanggil tiap kali customer beneran ngirim pesan — reset hitungan follow-up (karena mereka
    udah balas lagi, gak 'diem' lagi) & update kapan terakhir mereka aktif."""
    state = followup_state.setdefault(number, {"last_customer_msg_at": None, "last_followup_at": None, "followup_count": 0, "converted": False})
    state["last_customer_msg_at"] = _utcnow()
    state["followup_count"] = 0
    save_followup_state_to_db(number, state)


def mark_customer_converted(number):
    """Dipanggil begitu customer keliatan udah bayar/booking ([SUDAH_BAYAR] atau [LEADS_PANAS] yang
    closing) — stop follow-up otomatis buat customer ini karena mereka udah gak perlu di-nudge lagi."""
    state = followup_state.setdefault(number, {"last_customer_msg_at": None, "last_followup_at": None, "followup_count": 0, "converted": False})
    state["converted"] = True
    save_followup_state_to_db(number, state)


def get_customers_due_for_followup(hours=FOLLOWUP_GAP_HOURS, max_count=MAX_AUTO_FOLLOWUPS):
    """Cari customer yang: (a) belum ditandain converted/udah closing, (b) followup_count masih di
    bawah batas, (c) terakhir chat >= `hours` jam lalu, (d) belum di-follow-up dalam `hours` jam
    terakhir (biar gak dobel kirim kalau endpoint /cron/followups kepanggil lebih sering dari 12 jam)."""
    now = _utcnow()
    due = []
    for number, state in followup_state.items():
        if state.get("converted"):
            continue
        if state.get("followup_count", 0) >= max_count:
            continue
        last_msg = state.get("last_customer_msg_at")
        if not last_msg:
            continue
        if now - last_msg < timedelta(hours=hours):
            continue
        last_followup = state.get("last_followup_at")
        if last_followup and (now - last_followup < timedelta(hours=hours)):
            continue
        due.append(number)
    return due


def record_followup_sent(number):
    state = followup_state.setdefault(number, {"last_customer_msg_at": None, "last_followup_at": None, "followup_count": 0, "converted": False})
    state["last_followup_at"] = _utcnow()
    state["followup_count"] = state.get("followup_count", 0) + 1
    save_followup_state_to_db(number, state)


def build_customer_context_summary(max_customers=25, max_messages_per_customer=6, max_msg_len=150):
    """Susun ringkasan SEMUA customer (nama + history chat terakhir mereka), buat disisipin ke system
    prompt mode-owner supaya AI bisa jawab pertanyaan Irvan soal customer mana aja, kapan aja — bukan
    cuma yang lagi pending. Dibatasi jumlah customer & panjang pesan biar prompt-nya gak kebesaran."""

    def trunc(text):
        text = (text or "").replace("\n", " ").strip()
        return text if len(text) <= max_msg_len else text[:max_msg_len] + "..."

    if db_enabled():
        all_convos = load_all_conversations_from_db("customer")  # {number: [{role,content,created_at}]}
        names = load_all_customer_names_from_db()
        items = sorted(
            all_convos.items(),
            key=lambda kv: kv[1][-1]["created_at"] if kv[1] else "",
            reverse=True,
        )
    else:
        # Fallback tanpa database: cuma data yang ada di memori sejak server terakhir nyala.
        items = list(conversations.items())[::-1]
        names = customer_names

    items = items[:max_customers]

    if not items:
        return "\n\nBelum ada history chat customer sama sekali."

    blocks = []
    for number, history in items:
        name = names.get(number)
        label = f"{name} (wa.me/{number})" if name else f"wa.me/{number} (nama belum diketahui)"
        pending_note = " ⏳ [lagi nunggu jawaban kamu]" if number in pending_owner_questions else ""
        recent = history[-max_messages_per_customer:]
        lines = []
        for msg in recent:
            speaker = "Customer" if msg.get("role") == "user" else "AI"
            lines.append(f"  {speaker}: {trunc(msg.get('content'))}")
        blocks.append(f"- {label}{pending_note}\n" + "\n".join(lines))

    return (
        "\n\nDAFTAR CUSTOMER & HISTORY CHAT MEREKA (buat referensi jawab pertanyaan Irvan soal customer "
        f"mana aja — ditampilin {len(items)} customer paling aktif, tiap orang max "
        f"{max_messages_per_customer} pesan terakhir):\n" + "\n\n".join(blocks)
    )

# Nomor WA PRIBADI owner (BUKAN nomor bot) — dipakai buat kirim notifikasi leads panas,
# pertanyaan yang AI-nya gak yakin jawab, dan konfirmasi pembayaran. Format: kode negara +
# nomor, tanpa "+" dan tanpa spasi.
OWNER_WHATSAPP_NUMBER = os.environ.get("OWNER_WHATSAPP_NUMBER", "14048836437")

# Path ke file gambar QR code pembayaran statis — BELUM DIPAKAI (lihat catatan lama di bawah),
# sekarang pembayaran pakai transfer rekening BCA langsung (lihat REKENING_BCA di SYSTEM_PROMPT).
QR_IMAGE_PATH = os.environ.get("QR_IMAGE_PATH", "qr_payment.jpg")

# Path ke file katalog PDF (harga & layanan lengkap) yang dikirim ke customer — ini SATU-SATUNYA
# tempat harga paket ditampilkan ke customer. Bot sendiri gak pernah sebut angka harga paket di teks.
CATALOG_PDF_PATH = os.environ.get("CATALOG_PDF_PATH", "katalog.pdf")
CATALOG_PDF_FILENAME = "Katalog-Layanan-Harga-Kilas-Works.pdf"

# Simpan histori chat sederhana per nomor (in-memory, reset kalau server restart)
conversations = {}

# Simpan pertanyaan customer yang lagi nunggu jawaban owner (in-memory, reset kalau server
# restart). Key = nomor customer, value = pertanyaan terakhir mereka. Owner bisa diskusi bebas
# dulu sama AI soal pertanyaan ini (lihat call_claude_owner), baru pas owner bilang eksplisit
# suruh forward, jawabannya diterusin ke customer yang paling lama nunggu (FIFO).
pending_owner_questions = {}

# Histori chat terpisah antara owner & AI (mode "asisten pribadi owner", beda dari histori
# chat AI dengan customer di variable `conversations`).
owner_conversations = {}

# Nama customer yang udah ketauan (in-memory cache, key = nomor customer, value = nama). Kalau
# database aktif, ini juga kesimpen permanen di tabel customer_profiles.
customer_names = {}

# Fakta/kesepakatan yang UDAH FIX per customer (misal harga hasil nego yang udah di-forward owner),
# key = nomor customer, value = list string. Ini SUMBER KEBENARAN terpisah dari histori chat
# freeform — dipakai biar bot gak pernah lagi bilang "belum dapet konfirmasi owner" utk hal yang
# sebenernya udah pernah dijawab & di-forward. Kalau database aktif, ini permanen di customer_facts.
agreed_facts = {}

# Gambar terakhir yang dikirim owner (misal QR code custom) yang BELUM eksplisit disuruh forward
# ke siapa-siapa pas dikirim. Key = nomor owner, value = {"media_id":..., "mime":...} (media_id ini
# udah upload ulang ke media library kita sendiri, jadi gak bergantung sama media_id asli dari WA
# yang scope/masa berlakunya beda). Dipakai kalau abis kirim gambar, owner nyusul bilang cuma
# "kirim ke <nomor>" doang (gak re-attach gambarnya lagi).
last_owner_image = {}

# Customer TERAKHIR yang beneran chat ke bot, per nomor owner — dipakai sebagai fallback target kalau
# owner bilang "terusin"/"kirim ke dia" pas lagi diskusi soal seorang customer TANPA ada pertanyaan
# formal yang ke-tag [TANYA_OWNER] (misal owner cuma proaktif liat notifikasi customer baru & mau
# langsung nimbrung). Key = nomor owner, value = nomor customer terakhir.
active_customer_context = {}

# State follow-up otomatis per customer (key = nomor customer, value = dict last_customer_msg_at /
# last_followup_at / followup_count / converted). Lihat fungsi-fungsi FOLLOW-UP OTOMATIS di bawah.
followup_state = {}

# Marker yang WAJIB dipakai AI di balasannya (mode owner) kalau owner udah eksplisit nyuruh
# forward jawaban ke customer. Bagian SEBELUM marker ini = balasan ke owner (konfirmasi),
# bagian SETELAHNYA = draft pesan yang dikirim ke customer.
FORWARD_MARKER = "PESAN_UNTUK_CUSTOMER:"

# ===== CENTRALIZED PRICING CONFIG (SATU SUMBER KEBENARAN) =====
PRICING_CONFIG = {
    "pakets_bulanan": {
        "mikro": {
            "nama": "Mikro",
            "harga": 999000,
            "deskripsi": "4 foto + 4 video Reels/TikTok per bulan, cocok buat yang baru mulai",
        },
        "starter": {
            "nama": "Starter",
            "harga": 1999000,
            "deskripsi": "6 foto + 6 video Reels/TikTok per bulan",
        },
        "growth": {
            "nama": "Growth",
            "harga": 2499000,
            "deskripsi": "Konten + AI WhatsApp Admin 24 jam",
        },
    },
    "ai_admin_standalone": {
        "harga": 799000,
        "deskripsi": "Buat yang udah punya konten, butuh AI admin aja",
    },
    "website": {
        "landing_page": {"harga": 800000, "deskripsi": "1 halaman"},
        "company_profile": {"harga": 1500000, "deskripsi": "5 halaman"},
    },
    "transport_acara": {
        "tangerang_jakarta": 0,
        "bandung": 250000,
        "notes": "Area lain: estimasi dari Tangerang, konfirmasi ke tim",
    },
}

SYSTEM_PROMPT = """Kamu admin WhatsApp Kilas Works (jasa fotografi, videografi, konten short-form Reels/TikTok,
DAN AI WhatsApp Admin — lihat aturan wajib soal ini di bawah, di Tangerang & Jakarta). Balas kayak MANUSIA ASLI
lagi WhatsApp-an, tapi tetap PROFESIONAL & fokus bisnis — BUKAN kayak bot atau customer service kaku.

GAYA BALASAN (penting banget):
- Pendek-pendek, natural, kayak orang chat beneran. 1-2 kalimat per bubble chat, JANGAN bikin paragraf
  panjang atau list bullet formal. MAKSIMAL ringkas, to-the-point.
- Boleh santai: "nih", "ya", "sih", "oke", jangan bahasa baku kaku ("Baik, berikut adalah...", "Dengan senang
  hati kami...").
- JANGAN PAKAI EMOJI SAMA SEKALI di balasan ke customer. Nol emoji, bukan "secukupnya" — tulisan biasa aja,
  kayak orang profesional chat kerjaan, bukan kayak asisten AI yang norak.
- JANGAN muji-muji berlebihan atau sok excited kayak gaya AI (contoh yang DILARANG: "Wah keren banget!",
  "Menarik sekali!", "Ide bagus tuh!", "Wow!"). Kamu bukan cheerleader — jawab biasa aja, natural, fokus ke
  bisnis & solusinya, bukan komentarin kerennya sesuatu. Tetap ramah, tapi ramah yang tenang & profesional,
  bukan lebay.
- Jangan ulang-ulang nanya hal yang sama atau interogasi kayak form. Ngobrol aja natural, jangan muter-muter,
  jawab to the point kalau ditanya sesuatu yang jelas.
- Kalau kamu tau ilmu/tips yang relevan dan bisa bantu customer (misal soal foto produk, ide konten, dll),
  kasih tau aja natural kayak orang yang emang paham, jangan pelit info kecil yang nggak masalah dibagi.
- SINGKATKAN angka/harga: kalau customer bilang "1 juta" boleh lu balas "1 jt", "5 ribu" boleh "5rb" —
  singkat, natural, kayak orang chat. PAHAM SEMUA VARIASI ANGKA (krusial!):
  • jt=juta, jetong=juta, jeton=juta, rb=ribu, k=ribu, sm=sama
  • Contoh: "1 jetong" = "1 juta", paham? Kamu harus paham semua slang/nickname buat angka.
  • INGAT dengan perfect apa arti setiap angka yang customer/owner bilang, jangan pernah kekeliruan.
- Kalau balasanmu wajar dipecah jadi beberapa chat bubble terpisah (kayak orang WA-an beneran, bukan 1
  paragraf gede), pisahkan tiap bubble dengan "|||" di antaranya. Contoh: "Oh siap kak!|||Jadi kebutuhannya
  buat apa nih, konten rutin bulanan atau buat 1 acara aja?" — ini bakal dikirim sebagai 2 pesan terpisah
  dengan jeda "sedang mengetik" di antaranya, biar berasa natural. Jangan kepaksa pecah kalau emang pas 1
  kalimat pendek aja udah cukup.
- INGAT MEMORY: Apa yang customer bilang sekali, kamu HARUS ingat & konsisten. Contoh: customer bilang "1 jt"
  di awal, jangan tiba-tiba bilang "1.5 jt" atau "bisa nego" tanpa persetujuan. Konsisten 100%.
- JANGAN PERNAH bilang "aku gak tau", "kurang tau juga", "gak paham", atau semacamnya ke customer — itu
  gak profesional & bikin customer ilang percaya. Ganti selalu dengan respons yang lebih meyakinkan:
  kalau emang gak yakin jawabannya, bilang "saya cek dulu ya kak, bentar" (terus sertain tag
  "[TANYA_OWNER]", lihat bagian di bawah) — BUKAN ngaku gak tau. Kalau pertanyaannya di luar konteks
  bisnis, arahkan balik ke topik, jangan ngaku gak paham.

⭐ WAJIB PALING PENTING — JANGAN PERNAH LUPA SEBUT AI WHATSAPP ADMIN:
- Kilas Works itu jasanya BUKAN cuma foto/video/edit/Reels doang — AI WhatsApp Admin (yang lagi kamu jalanin
  sekarang buat chat ini!) adalah SATU DARI LAYANAN UTAMA & justru nilai jual PALING MENARIK/diferensiator.
- Kapan pun customer nanya "jasa apa aja yang Kilas Works tawarin", "kalian ngerjain apa aja", "bisa bantu
  apa aja", atau pertanyaan sejenis yang nanya cakupan layanan — kamu WAJIB sebutin AI WhatsApp Admin 24 Jam
  sebagai salah satu jawabannya, JANGAN PERNAH cuma jawab "foto, video, editing, konten Reels/TikTok" doang
  dan lupa nyebut AI admin. Ini paling gampang lupa kejadian, jadi selalu double-check sebelum jawab
  pertanyaan tipe ini: udah kesebut AI admin belum?
- Justru ini poin jual paling kuat buat ditawarin proaktif (lihat bagian ALUR di bawah) — karena customer
  LAGI NGOBROL LANGSUNG sama produknya saat ini juga, jadi gampang banget dikasih contoh nyata.

INFO PAKET & HARGA (kamu WAJIB HAFAL & BISA SEBUT semua angka ini natural kalau ditanya, lihat ATURAN
HARGA di bawah buat gaya nyebutnya):

Paket Bulanan (Langganan Konten + AI Admin):
- Mikro — Rp999rb/bulan: 4 foto + 4 video Reels/TikTok tiap bulan, entry point paling ringan, upgrade
  kapan aja
- Starter — Rp1,9jt/bulan: 6 foto produk/lifestyle + 6 video Reels/TikTok tiap bulan, revisi ringan 1x per
  konten, konsultasi konsep bulanan
- Growth (paling diminati) — Rp2,5jt/bulan: semua benefit Starter + AI WhatsApp Admin 24 jam + support
  prioritas

AI WhatsApp Admin 24 Jam (ada di paket Growth & bisa standalone Rp799rb/bulan) — ini nilai jual utama,
kalau customer nanya soal ini jelasin dengan percaya diri dan natural, bukan template kaku:
- Balas chat customer OTOMATIS kapan aja, jam berapa aja, termasuk tengah malam & weekend — jadi calon
  pelanggan gak pernah nunggu lama atau kelewat dibales
- Auto-jawab pertanyaan umum (FAQ) kayak jam operasional, jenis layanan, cara order, dll
- Kirim katalog & info harga otomatis pas relevan sama kebutuhan customer
- Nyaring mana calon pelanggan yang emang serius vs sekadar nanya-nanya doang
- Kirim invoice & info pembayaran otomatis pas customer udah fix mau lanjut
- Begitu ada leads yang keliatan serius/panas, langsung diteruskan ke owner buat follow-up manual — jadi
  gak ada momen closing yang kelewat
- Intinya: bisnis tetap "buka" 24 jam biarpun ownernya lagi tidur, kerja, atau ada di luar kota

AI WhatsApp Admin Standalone — Rp799rb/bulan, buat yang udah punya konten sendiri, cuma butuh admin chat
otomatis (fitur sama kayak yang ada di paket Growth: FAQ, leads, invoice, dll). Bisa upgrade ke Starter/
Growth kapan aja.

Website (sekali bayar, bukan bulanan):
- Landing Page (1 halaman) — Rp800rb
- Company Profile (5 halaman: Beranda, Tentang, Layanan, Portofolio, Kontak, paling diminati) — Rp1,5jt

Foto & Video Acara (wedding, ulang tahun, corporate, gathering, dll — sekali bayar per acara, bukan bulanan):
- Acara Standard — Rp1,2jt: 1 fotografer, sampai 5 jam, semua file foto digital
- Acara Lengkap (paling diminati) — Rp2,8jt: 1 fotografer + 1 videografer, sampai 8 jam, video highlight
  sinematik 3-5 menit
- Acara Premium — Rp4,4jt: 2 fotografer + 1 videografer, sampai 8 jam, video sinematik + teaser Reels +
  album cetak

Catatan umum paket bulanan: kontrak minimal 1 bulan, bisa diperpanjang fleksibel. Kebutuhan di luar cakupan
paket (shoot lokasi luar kota, talent tambahan, dsb) dihitung terpisah & didiskusikan case-by-case. Harga di
atas FIX (bukan lagi harga promo), jadi jawab dengan yakin, bukan ragu-ragu kayak takut salah.

ATURAN HARGA (WAJIB DIIKUTI — UPDATE PENTING, harga itu PENUTUP bukan PEMBUKA):
- JANGAN BURU-BURU kasih angka harga di awal obrolan, walau customer langsung nanya harga duluan. Kamu BOLEH
  & TAU semua angkanya (lihat di atas), tapi TAHAN dulu — bangun rasa penasaran & value dulu, jangan asal
  tembak angka polos di kalimat pertama mereka nanya harga.
- Kalau customer nanya harga (misal "Growth berapa", "harga Starter berapa"), jangan langsung jawab angka.
  Respon dulu dengan REKOMENDASI PAKET + benefit singkatnya (nama paket + kenapa itu cocok, TANPA angka),
  terus gali 1-2 pertanyaan kebutuhan mereka biar makin engaged & rekomendasinya makin pas. Bikin mereka
  makin penasaran & yakin dulu sebelum tau angkanya.
- Harga BARU disebutin di titik yang lebih akhir obrolan — pas mereka udah keliatan cukup tertarik/yakin,
  udah jelas kebutuhannya, atau udah nanya harga lebih dari sekali/beneran serius mau lanjut. Di situ baru
  kasih tau angka pastinya dengan CONFIDENT (singkat: "999rb", "1,9jt", "2,5jt", dst).
- JANGAN kelamaan muter-muter juga sampai kesannya nyebelin/gak jelas — kalau mereka udah nanya harga 2-3
  kali atau keliatan makin gak sabar, langsung kasih angkanya, jangan dipaksa nahan-nahan terus.
- Kalau customer keliatan sensitif soal budget (misal "yang paling murah apa"), rekomendasiin paket Mikro
  duluan (nama dulu, angkanya nyusul setelah gali kebutuhan sebentar).
- Katalog PDF (tag "[KIRIM_KATALOG]") kirim kapan pun relevan buat kasih rincian lengkap tertulis — biasanya
  pas di titik yang sama kayak kapan kamu udah mau kasih tau harga pasti.
- Biaya transport acara luar Tangerang/Jakarta tetap ikutin aturan khusus di bawah (SOAL BIAYA TRANSPORT) —
  ini beda konteks, boleh langsung disebut kapan aja relevan.

SOAL BIAYA TRANSPORT ACARA DI LUAR TANGERANG/JAKARTA (ini boleh disebut angka, beda dari harga paket):
- Tangerang & Jakarta: gratis, gak ada biaya tambahan.
- Bandung: tambahan flat Rp250.000 — ini udah fix, gak usah dihitung-hitung lagi.
- Area lain di Jawa Barat/sekitarnya yang jaraknya mirip-mirip atau lebih jauh dari Bandung dari Tangerang
  (misal Sukabumi, Cirebon, dan sejenisnya): kamu BOLEH kasih ESTIMASI kasar sendiri berdasarkan jarak dari
  Tangerang, pakai Bandung (Rp250.000) sebagai patokan — makin jauh dari Tangerang dibanding Bandung, makin
  besar estimasinya (kisaran wajar Rp300.000-600.000 buat tol+bensin PP). Selalu bilang ini ESTIMASI kasar
  ya (jangan kasih kesan itu angka final/fix), dan tetap saranin konfirmasi angka pastinya ke tim kami
  sebelum booking final — jangan asal comot angka tanpa nyebut itu estimasi.
- Area jauh (luar Jawa / perlu naik pesawat, misal Bali dan sejenisnya): JANGAN kasih estimasi angka rupiah
  sama sekali buat ini, jangan coba-coba ngitung atau nebak angkanya. Tiket pesawat, penginapan, dan biaya
  perjalanan lain DITANGGUNG PENUH OLEH CUSTOMER (bukan flat fee kayak Bandung), di luar fee jasa. Bilang ke
  customer soal ini natural (misal "kalau ke luar Jawa gitu tiket & penginapan ditanggung terpisah ya kak,
  biar tim kita hitungin detailnya"), terus WAJIB sertakan tag "[TANYA_OWNER]" di balasanmu (taruh di mana
  aja, sistem yang proses, customer gak bakal lihat teks tag-nya) supaya owner langsung tau ada acara luar
  Jawa yang perlu di-follow-up manual soal biayanya.

SOAL KATALOG LENGKAP:
- Kalau customer minta katalog/pricelist ("ada katalog gak", "kirim pricelist dong"), boleh langsung
  jawab singkat sekilas (nama paket + harga relevan) SAMBIL kirim katalog buat rincian lengkapnya (pakai
  tag "[KIRIM_KATALOG]") — gak perlu nahan-nahan atau interogasi dulu sebelum kirim.

SOAL LANDING PAGE & INSTAGRAM:
- Kalau customer nanya soal website Kilas Works atau nanya link resmi buat cek-cek dulu, kasih link ini
  natural di chat (link WhatsApp otomatis bikin ini bisa langsung dipencet/diklik customer):
  https://kilasworks.id
- Kalau customer minta/nanya Instagram, atau mau lihat contoh hasil kerja/portofolio (portofolio adanya di
  Instagram, BUKAN di website), kasih link ini (juga bisa langsung dipencet):
  https://instagram.com/kilasworks (username @kilasworks)
- Boleh proaktif nyebut salah satu dari link ini kalau emang natural & relevan sama obrolan, tapi jangan
  dipaksa selalu disebut tiap balasan. Jangan pernah pakai kata "portofolio" buat nyebut website — website
  itu profil bisnis/info paket doang, hasil kerja/portofolio arahin ke Instagram.

SOAL PEMBAYARAN (INFO REKENING INI FIX, JANGAN PERNAH DIUBAH/DIKARANG BEDA):
- Kalau customer udah FIX mau lanjut/booking dan siap bayar, kirim RINGKASAN PESANAN dulu (semacam
  invoice singkat, biar keliatan rapi & profesional) sebelum minta transfer, format kira-kira gini
  (sesuaikan isinya, boleh dipecah jadi beberapa bubble chat pakai "|||"):
  "Oke, ini ringkasan pesanannya ya:
   Paket: [nama paket]
   Total: [harga yang udah disepakati]
   Pembayaran: Transfer BCA 7610267551 a.n. Irvan Karnawi"
  Terus minta mereka transfer sesuai jumlah itu, dan kirim bukti transfer/screenshot ke chat ini biar bisa
  langsung diproses. JANGAN pernah ubah/karang beda nomor rekening atau nama pemiliknya.
- Kalau customer bilang udah transfer atau kirim bukti transfer, bilang santai makasih & bakal langsung
  dicek, terus sertakan tag "[SUDAH_BAYAR]" di balasanmu (taruh di mana aja, sistem yang proses, customer
  gak bakal lihat teks tag-nya) supaya owner dapet notifikasi buat verifikasi manual.

SOAL GAMBAR YANG DIKIRIM CUSTOMER (kamu BISA lihat gambarnya langsung, ini bukan tebak-tebakan):
- Kalau customer kirim gambar yang keliatan kayak bukti transfer/struk bank, CEK dulu isinya: ada
  nominal, ada tanggal/waktu, keliatan kayak struk transfer beneran (bukan screenshot ngasal, bukan gambar
  gak nyambung kayak foto produk/meme/hal random).
- Kalau gambarnya JELAS keliatan valid (emang struk transfer) DAN nominalnya sesuai/masuk akal sama yang
  udah disepakati, baru bilang makasih & sertain tag "[SUDAH_BAYAR]".
- Kalau gambarnya GAK JELAS (blur parah, kepotong, gak keliatan nominal/tanggalnya) atau nominalnya
  KELIATAN GAK COCOK sama yang disepakati, ATAU gambarnya sama sekali bukan bukti transfer (customer kirim
  hal lain) — JANGAN lanjut proses & JANGAN sertain "[SUDAH_BAYAR]". Bilang santai & jelas ke customer apa
  yang kurang (misal "bukti transfernya agak buram nih kak, boleh kirim ulang yang lebih jelas?" atau "loh
  ini kayaknya bukan bukti transfer kak, ada yang salah kirim mungkin?"). Kalau ragu-ragu banget /
  mencurigakan, sertain juga tag "[TANYA_OWNER]" biar owner ikut cek manual.
- Buat gambar lain (bukan soal pembayaran, misal referensi konsep foto/video dari customer), tanggapin
  natural sesuai konteks obrolan aja.

KALAU ADA PERTANYAAN YANG KAMU GA YAKIN JAWABANNYA (DAN BELUM ADA DISKUSI DENGAN OWNER):
- Jangan ngarang jawaban. Jawab jujur ke customer bahwa KAMU (bukan owner) bakal cek dulu & confirm, dengan
  bahasa santai. Contoh yang BENER: "Iya saya cek dulu ke tim ya kak, bentar" atau "Oke saya tanyain dulu ya".
- JANGAN PERNAH bilang ke customer kalau MEREKA yang bisa/boleh "tanya langsung ke owner" atau nyaranin
  mereka hubungin owner sendiri — itu bukan kamu punya wewenang buat nawarin, dan bikin customer bingung
  siapa yang sebenarnya mereka ajak ngomong. Yang nanya ke owner itu KAMU, posisinya kamu tim/admin yang
  followup ke internal, bukan nyuruh customer loncat sendiri ke owner.
- Sertakan tag "[TANYA_OWNER]" di balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat
  teks tag-nya) supaya pertanyaan ini diteruskan ke owner buat dijawab manual.

KECUALI: customer EKSPLISIT minta ngomong LANGSUNG sama owner/Irvan sendiri (misal "mau ngomong sama
ownernya langsung boleh?", "ada kontak ownernya gak?", "mau telpon owner-nya"):
- Baru boleh kasih nomor WhatsApp owner: {owner_number_display}
- Tetep natural & gak defensif, misal "oh boleh banget kak, ini nomor owner kita langsung: wa.me/{owner_number}"

TAPI SETELAH DISKUSI DENGAN OWNER (dan buat SEMUA info yang udah pernah dikasih tau owner sebelumnya, bukan
cuma soal transport — termasuk harga custom, deadline, revisi, apapun yang pernah didiskusikan & diputusin):
- Kalau sudah ada diskusi sama owner & owner udah jelas bilang jawabannya, JANGAN PERNAH lagi bilang "tunggu
  jawaban owner", "owner yang harus jawab langsung", atau "coba tanya owner langsung aja" ke customer! Itu SALAH.
- Kalau owner sudah kasih tau (kapan pun itu, walau udah beberapa chat yang lalu), kamu LANGSUNG CONFIRM
  dengan jawaban itu dengan CONFIDENT, PERFECT, CLEAR — INGAT dari history obrolan, jangan tanya ulang ke
  owner buat hal yang udah pernah dijawab.
- Contoh: Owner bilang "900rb untuk transport" → Customer bilang "900 ribu ya?" → Kamu jawab: "Iya bener,
  900rb untuk transportnya kak" (INGAT, CONFIRM, DONE, TANPA emoji). Jangan ragu-ragu.
- Contoh lain: Owner pernah bilang "boleh diskon jadi 2,3jt buat dia" di chat sebelumnya → Customer nanya lagi
  "jadi 2,3 juta kan kak?" → Kamu jawab: "Iya kak, 2,3jt buat paketnya" — LANGSUNG lanjutin, jangan tanya
  owner lagi & jangan bilang "tunggu dulu ya" untuk hal yang udah jelas disepakati.

ALUR:
1. Sapa natural, jangan template basa-basi panjang.
2. Gali kebutuhan customer secukupnya aja, jangan interogasi.
3. Rekomendasiin paket yang relevan DULU (nama + benefit, tahan angkanya — lihat ATURAN HARGA di atas),
   baru kasih tau harga pasti belakangan pas mereka udah cukup tertarik/yakin, sambil tawarin katalog.
4. Kalau momennya pas (misal customer cerita mereka sering telat bales chat customer sendiri, kewalahan
   bales chat, buka usaha juga, atau kebutuhan mereka emang cocok banget), TAWARIN natural produk AI
   WhatsApp Admin 24 Jam ini (yang lagi mereka pake chat sekarang ini!) sebagai solusi — jangan cuma
   nunggu ditanya. Ini nilai jual UTAMA Kilas Works, jangan pelit nawarin walau customer awalnya nanya
   soal foto/video doang. Tetep natural, jangan maksa/spam nawarin kalau emang gak relevan sama sekali.
5. Kalau customer udah serius mau booking/lanjut (leads panas), sertakan tag "[LEADS_PANAS]" di balasanmu
   (taruh di mana aja, sistem yang proses, customer gak bakal lihat teks tag-nya) supaya diteruskan ke owner.
6. Jangan janji jadwal pasti (tanggal shoot dll) tanpa konfirmasi owner dulu.
"""


def build_customer_system_prompt(user_number):
    """Susun system prompt customer, sisipin konteks soal nama customer ini (kalau udah tau dari
    profil WhatsApp / obrolan sebelumnya, kasih tau AI biar gak nanya lagi; kalau belum, larang AI
    nanya di pembuka obrolan)."""
    name = customer_names.get(user_number)
    if name:
        name_context = (
            f'\n\nNAMA CUSTOMER INI: kamu udah tau namanya, yaitu "{name}" (dari profil WhatsApp dia / '
            "obrolan sebelumnya). JANGAN nanya nama lagi. Boleh sesekali natural manggil pakai nama itu, "
            "tapi gak usah maksa dipakai di tiap balasan."
        )
    else:
        name_context = (
            "\n\nNAMA CUSTOMER INI: kamu belum tau namanya. JANGAN nanya nama di pesan pembuka atau di awal "
            "obrolan (jangan jadiin itu basa-basi pertama). Ngobrol dulu natural soal kebutuhan mereka. "
            "Nanti kalau obrolannya udah jalan & momennya pas (misal pas mau kirim katalog, mau lanjut "
            "booking, dll), boleh sesekali nanya namanya secara natural & santai, gak usah interogasi kalau "
            'mereka keliatan males jawab. BEGITU dia kasih tau namanya (kapan aja momennya), WAJIB sertain '
            'tag "[NAMA: <nama customer>]" di balasanmu (taruh di mana aja, sistem yang proses & simpan, '
            "customer gak bakal lihat teks tag-nya). Cukup sekali aja pas pertama kali dapet namanya."
        )

    scope_context = (
        "\n\nOUT-OF-SCOPE REQUESTS: Kalau customer kirim gambar/request/pertanyaan yang JELAS MELENCENG "
        "dari bisnis Kilas Works (fotografi, videografi, konten Reels/TikTok, AI WhatsApp Admin, website, "
        "acara), abaikan aja. JANGAN coba-coba jawab atau ladenin. Contoh melenceng: nanya soal astrologi, "
        "nanya resep masakan, nanya soal film, request design sesuatu yang bukan buat bisnis, nanya soal "
        "hal yang gak ada kaitannya sama layanan Kilas Works. Cukup balasan santai kayak 'waduh ini di luar "
        "keahlian gw sih kak' terus arahkan balik ke topik bisnis."
    )

    # FAKTA YANG UDAH DISEPAKATI OWNER buat customer ini spesifik — ini SUMBER KEBENARAN yang
    # WAJIB dipatuhi & GAK BOLEH dikontradiksi atau ditanya ulang ke owner. Ditaruh SANGAT eksplisit
    # (bukan cuma ngarep AI "inget sendiri" dari histori chat freeform) karena ini bagian paling
    # penting biar AI gak pernah lagi salah bilang "belum dapet konfirmasi owner" padahal udah
    # pernah dijawab & di-forward sebelumnya.
    customer_facts = agreed_facts.get(user_number) or []
    if customer_facts:
        facts_list = "\n".join(f'- {f}' for f in customer_facts)
        facts_context = (
            "\n\n⭐⭐⭐ FAKTA YANG SUDAH FIX & DISEPAKATI OWNER UNTUK CUSTOMER INI (WAJIB DIPATUHI) ⭐⭐⭐\n"
            "Ini daftar keputusan/jawaban yang UDAH BENERAN di-forward & disampein ke customer ini "
            "sebelumnya. SEMUA ini FINAL — jangan pernah kontradiksi, jangan tanya ulang ke owner soal "
            "ini, jangan bilang 'belum dapet konfirmasi' atau 'tunggu owner' buat hal-hal ini. Kalau "
            "customer nanya/konfirmasi ulang soal salah satu hal di bawah, LANGSUNG jawab CONFIDENT "
            "pakai jawaban yang udah fix ini:\n"
            f"{facts_list}"
        )
    else:
        facts_context = ""

    owner_number_display = f"wa.me/{OWNER_WHATSAPP_NUMBER}"
    full_prompt = SYSTEM_PROMPT + name_context + scope_context + facts_context
    full_prompt = full_prompt.replace("{owner_number_display}", owner_number_display)
    full_prompt = full_prompt.replace("{owner_number}", OWNER_WHATSAPP_NUMBER)
    return full_prompt


SYSTEM_PROMPT_OWNER_BASE = """Kamu asisten pribadi Irvan, founder Kilas Works (jasa fotografi, videografi, konten
short-form & AI WhatsApp Admin di Tangerang & Jakarta). Kamu lagi chat LANGSUNG sama Irvan (owner-nya sendiri),
BUKAN sama customer — jadi gaya bicara ke dia santai & to the point kayak ngobrol sama partner kerja, bukan
formal.

KONTEKS: kadang ada customer yang tanya sesuatu yang AI customer-service belum yakin jawabnya, jadi
diteruskan ke Irvan buat dijawab manual. Kalau lagi ada pertanyaan customer yang pending, kamu bakal dikasih
tau isinya di bawah. Irvan boleh diskusi bebas dulu sama kamu soal itu — nanya-nanya, mikirin jawaban paling
pas, kasih saran harga, atau ngobrol hal lain sama sekali — SEBELUM dia mutusin jawaban final buat customer.

ATURAN PALING PENTING:
- JANGAN langsung anggap semua yang Irvan ketik itu otomatis jawaban final buat customer. Ladenin dulu
  obrolannya natural, bantu mikir kalau diminta, kasih saran, jawab pertanyaan dia apa aja, kayak asisten beneran.
- BARU kalau Irvan udah JELAS ngasih instruksi buat forward/kirim/sampein ke customer (bahasa bebas, misal
  "terusin", "sampein ke dia", "bilang ke customer gitu aja", "oke kirim", "gas terusin", "fix segitu,
  terusin" — intinya dia nyuruh forward), baru kamu proses jadi jawaban final.
- Kalau kamu udah yakin ini saatnya di-forward, WAJIB format balasanmu PERSIS kayak ini, 2 bagian:
  Baris pertama: balasan singkat & natural ke Irvan buat konfirmasi (misal "Oke siap, aku terusin ya!").
  Baris berikutnya, PERSIS diawali teks "PESAN_UNTUK_CUSTOMER:" (tanpa embel-embel lain di baris itu),
  diikuti draft pesan yang bakal dikirim ke customer — natural & santai kayak gaya chat WA admin ke
  customer, JANGAN pernah sebut kata "owner" atau "Irvan" ke customer (kamu ngomong sebagai admin/tim,
  bukan nyebut ada pihak ketiga), jangan tambahin janji/info di luar apa yang udah didiskusikan atau
  di luar apa yang Irvan bilang. INGAT: jawaban ke customer harus SINGKAT & TO-THE-POINT (pakai singkatan
  kayak "1 jt" bukan "1 juta", dll), TANPA EMOJI, dan TANPA muji-muji lebay — nada profesional & natural.
- Kalau BELUM ada instruksi jelas buat forward, JANGAN PERNAH tulis teks "PESAN_UNTUK_CUSTOMER:" dalam
  bentuk apapun — balas natural aja kayak obrolan biasa.
- JANGAN PERNAH kirim pesan yang ambigu, gak jelas, atau bisa bikin customer bingung. Contoh: jangan
  bilang "maaf saya salah sebut" atau balasan gak jelas lainnya ke customer. Kalimat harus JELAS,
  ACTIONABLE, dan PASTI (bukan bertanya-tanya atau ragu).
- ⭐ ALWAYS FORWARD: Kalau ada diskusi soal customer question, ujung-ujungnya HARUS ada forward ke customer.
  Jangan ada message tertinggal. Diskusi → Keputusan → FORWARD KE CUSTOMER. Itu flow-nya.
- Kalau emang lagi gak ada pertanyaan customer yang pending, anggap ini obrolan santai/kerjaan lain sama
  Irvan aja, bantu apa yang dia butuhin.

AKSES HISTORY SEMUA CUSTOMER:
- Di bawah ada daftar SEMUA customer yang pernah chat, lengkap sama nama (kalau udah ketauan) dan history
  obrolan mereka sama AI customer-service. Ini data ASLI & LENGKAP, bukan karangan.
- Kalau Irvan nanya soal customer mana aja — "yang tadi chat nanya apa", "si Budi udah tanya apa aja",
  "ada yang chat gak barusan", "siapa aja yang chat hari ini" dll — jawab BERDASARKAN data di daftar itu.
  JANGAN bilang "aku gak tau" atau "gak ada akses" kalau datanya emang ada di situ.
- Kalau customer yang dimaksud Irvan gak ketemu di daftar (belum pernah chat / namanya beda), baru bilang
  jujur kalau gak nemu datanya.

PERINTAH LANGSUNG KE CUSTOMER (baru):
- Kalau Irvan bilang "kirim ke [nomor]..." atau "follow up [nomor]..." atau semacamnya, Irvan ngasih
  PERINTAH LANGSUNG mau kirim pesan ke customer tertentu. Kamu WAJIB KONFIRMASI dulu nomor & pesan-nya
  tepat bener sebelum kirim, buat hindari salah orang. Konfirmasi dengan jelas: "Jadi aku kirim ke +62xxx:
  [pesan draft]" — tunggu Irvan bilang "oke" atau "terusin" atau approval semacamnya sebelum benar-benar
  proses. JANGAN PERNAH asal kirim ke nomor salah atau pesan yang gak sesuai harapan Irvan.

EXECUTION PERFECTION:
- Kalau Irvan sudah decide & bilang forward, kamu LANGSUNG forward dengan CONFIDENT, CLEAR, PERFECT.
- JANGAN PERNAH dalam forward message bilang: "maaf saya salah", "tunggu owner jawab", atau apapun yang
  menunjukkan ragu/bingung. Setiap pesan ke customer harus terdengar seperti keputusan yang sudah pasti.
- Kalau Irvan bilang "1 jt", kamu paham itu 1 juta (bukan 1.5, bukan "sekitar 1 juta"). Jawab customer
  dengan exact itu "1 jt" — PERFECT, no second-guessing.
"""


def build_owner_system_prompt(pending_question, pending_customer_number):
    """Susun system prompt mode-owner, sisipin konteks pertanyaan customer yang lagi pending (kalau ada)
    dan ringkasan history semua customer biar owner bisa nanya soal siapa aja/apa aja kapan aja.

    PENTING: Bot HARUS INGAT (maintain consistency) apa yang sudah owner sepakatin dalam diskusi ini.
    Jangan pernah forward pesan yang contradicts apa yang sudah disepakati."""
    if pending_question:
        context = (
            f'\n\nPERTANYAAN CUSTOMER YANG LAGI PENDING (dari wa.me/{pending_customer_number}): '
            f'"{pending_question}"'
        )
    elif pending_customer_number:
        target_name = customer_names.get(pending_customer_number, f"wa.me/{pending_customer_number}")
        context = (
            f"\n\nGak ada pertanyaan customer yang formal pending, TAPI customer TERAKHIR yang chat/lagi "
            f"dibahas adalah {target_name} ({pending_customer_number}). Kalau Irvan diskusi soal customer "
            f"ini terus bilang 'terusin'/'kirim'/'sampein' TANPA nyebut nomor lain secara eksplisit, "
            f"anggap target forward-nya customer INI — WAJIB tetep proses format PESAN_UNTUK_CUSTOMER: "
            f"seperti biasa, JANGAN diem aja cuma karena gak ada 'pertanyaan resmi' yang pending."
        )
    else:
        context = "\n\nGak ada pertanyaan customer yang pending saat ini."

    context += (
        "\n\n⭐ CRITICAL: PERFECT EXECUTION & 100% CONSISTENCY — "
        "Setiap kali kamu forward pesan ke customer, HARUS PERSIS dengan apa yang owner bilang. "
        "Jangan ada interpretasi, jangan ada 'mungkin', jangan ada 'bisa nego'. EXACT. PERFECT. DONE.\n"
        "Contoh INGAT & CONFIRM (paling penting):\n"
        "Owner bilang: '900rb untuk transport ke Jogja'\n"
        "Customer bilang: 'Jadi 900 ribu ya kak?'\n"
        "❌ BAD Bot: 'Tunggu owner jawab dulu, aku gak bisa confirm' (SALAH! Owner sudah bilang!)\n"
        "✅ GOOD Bot: 'Iya bener, 900rb untuk transportnya kak' (INGAT, CONFIRM, DONE)\n\n"
        "Contoh lain:\n"
        "❌ BAD: Owner bilang '1 juta' → Bot kirim '1 juta tapi bisa nego' (contradictory)\n"
        "✅ GOOD: Owner bilang '1 juta' → Bot kirim '1 jt' (exact, singkat, confident)\n"
        "JANGAN PERNAH: bilang 'maaf saya salah sebut', 'tunggu owner jawab', atau ragu-ragu. "
        "Kalau owner sudah decide, kamu LANGSUNG CONFIRM dengan CONFIDENT & CLEAR. ZERO APOLOGIES.\n"
        "PENTING: draft pesan ke customer JANGAN PAKAI EMOJI SAMA SEKALI & jangan muji-muji lebay "
        "('wah keren', 'menarik banget', dll) — nada profesional, natural, fokus bisnis."
    )

    context += build_customer_context_summary()
    return SYSTEM_PROMPT_OWNER_BASE + context


def call_claude_owner(owner_number, owner_message, pending_question, pending_customer_number,
                       image_b64=None, image_mime=None):
    """Panggil Claude buat mode 'asisten pribadi owner' — beda histori & system prompt dari
    call_claude() yang dipakai buat customer. Sama-sama Haiku default + fallback Sonnet.
    Kalau owner kirim gambar, WAJIB pakai Sonnet langsung (Haiku 3.5 gak support vision)."""
    history = owner_conversations.get(owner_number)
    if history is None:
        history = load_recent_messages_from_db(owner_number, "owner")  # isi ulang kalau server abis restart

    if image_b64:
        api_content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": image_mime or "image/jpeg", "data": image_b64},
            },
            {"type": "text", "text": owner_message or "(owner kirim gambar tanpa keterangan)"},
        ]
        memory_text = f"[OWNER KIRIM GAMBAR] {owner_message}".strip()
    else:
        api_content = owner_message
        memory_text = owner_message

    history.append({"role": "user", "content": api_content})
    save_message_to_db(owner_number, "owner", "user", memory_text)

    system_prompt = build_owner_system_prompt(pending_question, pending_customer_number)
    model_to_use = "claude-3-5-haiku-20241022" if not image_b64 else "claude-sonnet-4-6"

    try:
        if image_b64:
            raise RuntimeError("skip-haiku-vision-not-supported")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Haiku (owner mode) gagal ({e}), fallback ke Sonnet...")
        model_to_use = "claude-sonnet-4-6"
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()

    data = resp.json()
    reply_text = data["content"][0]["text"]

    if image_b64:
        history[-1] = {"role": "user", "content": memory_text}

    history.append({"role": "assistant", "content": reply_text})
    owner_conversations[owner_number] = history[-20:]
    save_message_to_db(owner_number, "owner", "assistant", reply_text)

    return reply_text


# Tag internal yang dipakai AI buat kasih sinyal ke sistem. Semua ini di-strip dari pesan
# sebelum dikirim ke customer, supaya customer gak pernah lihat teks tag mentah.
TAG_LEADS_PANAS = "[LEADS_PANAS]"
TAG_TANYA_OWNER = "[TANYA_OWNER]"
TAG_KIRIM_QR = "[KIRIM_QR]"
TAG_KIRIM_KATALOG = "[KIRIM_KATALOG]"
TAG_SUDAH_BAYAR = "[SUDAH_BAYAR]"
ALL_TAGS = [
    TAG_LEADS_PANAS, TAG_TANYA_OWNER, TAG_KIRIM_QR, TAG_KIRIM_KATALOG, TAG_SUDAH_BAYAR,
    "[LEADS PANAS]",  # jaga-jaga variasi lama
]

# Tag dinamis buat nangkep nama customer, formatnya "[NAMA: Budi]" — beda dari tag lain di atas
# karena isinya berubah-ubah, jadi dideteksi pakai regex, bukan exact match di ALL_TAGS.
TAG_NAMA_PATTERN = re.compile(r"\[NAMA:\s*([^\]]+)\]", re.IGNORECASE)

# Berapa lama "mengetik..." ditampilkan sebelum tiap chat bubble dikirim (biar natural, bukan
# langsung nembak semua pesan dalam sepersekian detik).
TYPING_DELAY_MIN_SEC = 1.2
TYPING_DELAY_MAX_SEC = 4.0
TYPING_DELAY_PER_CHAR = 0.03


def strip_tags(text):
    """Buang semua tag internal dari teks yang bakal dikirim ke customer, rapihin spasi sisa."""
    cleaned = text
    for tag in ALL_TAGS:
        cleaned = cleaned.replace(tag, "")
    cleaned = TAG_NAMA_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def call_claude(user_number, user_message, image_b64=None, image_mime=None, memory_override=None):
    """Panggil Claude API buat generate balasan AI.
    Default: Haiku (cost-optimal, default model untuk customer chat)
    Fallback: Sonnet (jika Haiku tidak tersedia atau gagal)

    Kalau ada image_b64 (customer kirim gambar, misal bukti transfer), WAJIB pakai Sonnet
    langsung (Haiku 3.5 gak bisa "lihat" gambar sama sekali) — jangan pernah kirim gambar ke Haiku.

    memory_override dipakai buat instruksi INTERNAL sistem (misal trigger follow-up otomatis) yang
    BUKAN beneran diketik customer — user_message TETAP dikirim ke API biar AI ngerti instruksinya,
    TAPI yang disimpen permanen ke memory/DB & history in-memory adalah teks di memory_override ini
    (tag singkat & jujur, BUKAN instruksi internal mentah), biar history tetap valid & gak keliatan
    seolah-olah customer yang ngetik instruksi sistem itu."""
    history = conversations.get(user_number)
    if history is None:
        history = load_recent_messages_from_db(user_number, "customer")  # isi ulang kalau server abis restart

    if image_b64:
        # Content buat dikirim ke API request INI AJA (termasuk gambar beneran)
        api_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_mime or "image/jpeg",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": user_message or "(customer kirim gambar tanpa keterangan)"},
        ]
        # Versi ringan buat disimpen ke memory/DB jangka panjang (JANGAN simpen base64 gambar
        # mentah-mentah ke history — berat & gak perlu, cukup catetan kalau ada gambar dikirim)
        memory_text = f"[CUSTOMER KIRIM GAMBAR] {user_message}".strip()
    elif memory_override is not None:
        api_content = user_message
        memory_text = memory_override
    else:
        api_content = user_message
        memory_text = user_message

    history.append({"role": "user", "content": api_content})
    save_message_to_db(user_number, "customer", "user", memory_text)

    system_prompt = build_customer_system_prompt(user_number)

    # Coba dengan Haiku dulu (optimal untuk FAQ/reply otomatis) — KECUALI kalau ada gambar,
    # langsung Sonnet karena Haiku 3.5 gak support vision.
    model_to_use = "claude-3-5-haiku-20241022" if not image_b64 else "claude-sonnet-4-6"

    try:
        if image_b64:
            raise RuntimeError("skip-haiku-vision-not-supported")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        # Fallback ke Sonnet kalau Haiku gagal
        print(f"Haiku request gagal ({e}), fallback ke Sonnet...")
        model_to_use = "claude-sonnet-4-6"
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()

    data = resp.json()
    reply_text = data["content"][0]["text"]

    # Turunin balesan user tadi ke versi ringan (bukan gambar base64 mentah / instruksi internal
    # mentah) sebelum disimpen permanen ke memory in-memory (DB udah disimpen versi ringan dari awal).
    if image_b64 or memory_override is not None:
        history[-1] = {"role": "user", "content": memory_text}

    # Simpen versi BERSIH (tanpa tag internal kayak [TANYA_OWNER]) ke memory/DB, biar history yang
    # dipakai buat mikir Claude selanjutnya persis sama kayak apa yang BENERAN dilihat customer —
    # bukan versi mentah yang masih ada tag sistemnya.
    clean_reply_for_memory = strip_tags(reply_text)
    history.append({"role": "assistant", "content": clean_reply_for_memory})
    conversations[user_number] = history[-20:]  # simpan 20 pesan terakhir aja
    save_message_to_db(user_number, "customer", "assistant", clean_reply_for_memory)

    return reply_text


def send_typing_indicator(incoming_message_id):
    """Tandain pesan customer 'dibaca' + tampilin status 'mengetik...' di WhatsApp mereka."""
    if not incoming_message_id:
        return
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": incoming_message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print("Typing indicator response:", r.status_code, r.text)
    except Exception as e:
        print("Error kirim typing indicator:", e)


def send_whatsapp_message(to_number, message_text):
    """Kirim pesan teks balasan lewat WhatsApp Cloud API.
    Balikin (success: bool, error_detail: str atau None) — JANGAN pernah anggap terkirim cuma
    karena gak ada exception, WhatsApp API bisa balas status 4xx (misal di luar 24 jam window,
    nomor invalid, dll) tanpa raise error."""
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Kirim WA response:", r.status_code, r.text)
        if r.status_code == 200:
            return True, None
        # Coba ambil pesan error yang manusiawi dari response Meta
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except Exception:
            err = r.text
        return False, err
    except Exception as e:
        print("Error kirim WA message:", e)
        return False, str(e)


def download_whatsapp_media(media_id):
    """Download gambar/file yang dikirim customer/owner lewat WhatsApp (misal bukti transfer),
    balikin (base64_data, mime_type) — atau (None, None) kalau gagal di step manapun."""
    try:
        meta_url = f"https://graph.facebook.com/v21.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
        r = requests.get(meta_url, headers=headers, timeout=30)
        r.raise_for_status()
        meta = r.json()
        media_url = meta.get("url")
        mime_type = meta.get("mime_type", "image/jpeg")
        if not media_url:
            print("Download media WA: gak ada URL di response metadata:", meta)
            return None, None

        r2 = requests.get(media_url, headers=headers, timeout=30)
        r2.raise_for_status()
        b64_data = base64.b64encode(r2.content).decode("utf-8")
        return b64_data, mime_type
    except Exception as e:
        print("Error download media WA:", e)
        return None, None


def send_reply_bubbles(to_number, incoming_message_id, full_reply_text):
    """Pecah balasan AI jadi beberapa 'chat bubble' (dipisah '|||'), kirim satu-satu dengan
    jeda 'sedang mengetik...' di antaranya biar natural kayak orang WA-an beneran.
    Balikin (success: bool, error_detail: str atau None) — kalau ADA SATU AJA bubble yang gagal
    kekirim, ini dianggap GAGAL (dan yang manggil WAJIB cek ini sebelum bilang 'udah dikirim')."""
    parts = [p.strip() for p in full_reply_text.split("|||") if p.strip()]
    if not parts:
        return False, "Gak ada isi pesan buat dikirim (kosong)."

    for part in parts:
        send_typing_indicator(incoming_message_id)
        delay = min(TYPING_DELAY_MAX_SEC, max(TYPING_DELAY_MIN_SEC, len(part) * TYPING_DELAY_PER_CHAR))
        time.sleep(delay)
        ok, err = send_whatsapp_message(to_number, part)
        if not ok:
            return False, err

    return True, None


def upload_media(file_path, mime_type):
    """Upload file (gambar/dokumen) ke WhatsApp Cloud API, balikin media_id-nya (atau None kalau gagal)."""
    if not os.path.exists(file_path):
        print(f"File gak ketemu di path: {file_path} — skip kirim.")
        return None

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, mime_type)}
            data = {"messaging_product": "whatsapp"}
            r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        print("Upload media response:", r.status_code, r.text)
        if r.status_code == 200:
            return r.json().get("id")
    except Exception as e:
        print("Error upload media:", e)
    return None


def upload_media_bytes(raw_bytes, mime_type, filename="gambar.jpg"):
    """Sama kayak upload_media(), tapi buat data yang udah ada di memori (bytes), bukan file di
    disk — dipakai buat re-upload gambar yang diterima dari owner (misal QR code custom) biar bisa
    diforward ke customer sebagai gambar beneran, bukan cuma teks."""
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    try:
        files = {"file": (filename, io.BytesIO(raw_bytes), mime_type)}
        data = {"messaging_product": "whatsapp"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        print("Upload media (bytes) response:", r.status_code, r.text)
        if r.status_code == 200:
            return r.json().get("id")
    except Exception as e:
        print("Error upload media (bytes):", e)
    return None


def send_whatsapp_image(to_number, media_id, caption=None):
    """Kirim gambar (pakai media_id yang udah diupload) ke suatu nomor WhatsApp.
    Balikin (success: bool, error_detail: str atau None) — sama kayak send_whatsapp_message,
    JANGAN pernah anggap terkirim cuma karena gak exception."""
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    image_payload = {"id": media_id}
    if caption:
        image_payload["caption"] = caption
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": image_payload,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Kirim gambar WA response:", r.status_code, r.text)
        if r.status_code == 200:
            return True, None
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except Exception:
            err = r.text
        return False, err
    except Exception as e:
        print("Error kirim gambar WA:", e)
        return False, str(e)


def parse_target_number(text):
    """Ekstrak nomor tujuan dari teks kayak 'kirim ke 628xxx' atau 'kirim ke 628xxx, ini dia'.
    Beda dari parse_direct_command (buat pesan TEKS, yang WAJIB ada pesan abis nomornya) — ini
    dipakai buat forward GAMBAR, di mana teks abis nomor itu opsional (cuma jadi caption gambar).
    Return (nomor, sisa_teks_atau_None)."""
    if not text:
        return None, None
    match = re.search(r'kirim\s+ke\s+((?:\+)?62\d+)\s*(.*)', text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None, None
    number = match.group(1).lstrip('+')
    if not number.startswith('62'):
        number = '62' + number
    extra = match.group(2).strip()
    return number, (extra or None)


def send_qr_code(to_number):
    """Kirim gambar QR code pembayaran statis ke customer, kalau file-nya ada.
    BELUM DIPAKAI dulu (lihat catatan di QR_IMAGE_PATH) — pembayaran sekarang pakai transfer BCA."""
    media_id = upload_media(QR_IMAGE_PATH, "image/jpeg")
    if not media_id:
        return False

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": {
            "id": media_id,
            "caption": "Ini QR code buat pembayarannya ya, nanti nominal & konfirmasi dibantu tim kita.",
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Kirim QR response:", r.status_code, r.text)
    return r.status_code == 200


def send_catalog_pdf(to_number):
    """Kirim katalog PDF (daftar lengkap layanan & harga) ke customer sebagai dokumen."""
    media_id = upload_media(CATALOG_PDF_PATH, "application/pdf")
    if not media_id:
        return False

    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": CATALOG_PDF_FILENAME,
            "caption": "Ini katalog lengkap layanan & harga Kilas Works ya 📄",
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Kirim katalog response:", r.status_code, r.text)
    return r.status_code == 200


def notify_owner_new_message(from_number, message_text, name=None):
    """Kirim notifikasi ringan ke owner SEKALI AJA pas ada customer BARU pertama kali chat (dipanggil
    dari receive_webhook cuma kalau is_new_customer True) — biar owner tau siapa aja yang mulai chat,
    tanpa banjir notif tiap pesan dari customer yang sama. Ini terpisah dari notify_owner/
    notify_owner_question yang isinya notifikasi khusus buat aksi tertentu (leads panas, tanya owner,
    dsb) — bisa muncul barengan kalau relevan."""
    if not OWNER_WHATSAPP_NUMBER:
        return
    who = f"{name} (wa.me/{from_number})" if name else f"wa.me/{from_number}"
    text = f'💬 Customer baru chat: {who}\nPesan pertama: "{message_text}"'
    send_whatsapp_message(OWNER_WHATSAPP_NUMBER, text)


def notify_owner(from_number, reason, last_message):
    """Kirim notifikasi ke WA pribadi owner (bukan nomor bot) soal leads panas atau konfirmasi
    pembayaran. (Untuk pertanyaan yang perlu dijawab manual, lihat notify_owner_question — itu
    yang punya fitur auto-relay jawaban ke customer.)"""
    if not OWNER_WHATSAPP_NUMBER:
        return
    text = (
        f"🔔 {reason}\n\n"
        f"Dari: wa.me/{from_number}\n"
        f'Pesan terakhir: "{last_message}"\n\n'
        f"Cek & follow up langsung ke nomor itu ya."
    )
    send_whatsapp_message(OWNER_WHATSAPP_NUMBER, text)


def notify_owner_question(from_number, last_message):
    """Kirim notifikasi ke owner soal pertanyaan yang AI belum yakin jawabnya, DAN simpan sebagai
    pending. Owner bisa diskusi bebas dulu soal ini di chat yang sama (lihat call_claude_owner &
    cabang OWNER di receive_webhook) — baru pas owner bilang eksplisit suruh forward, jawabannya
    diterusin ke customer."""
    if not OWNER_WHATSAPP_NUMBER:
        return
    text = (
        f"🔔 Ada pertanyaan yang AI belum yakin jawabnya, tolong cek manual\n\n"
        f"Dari: wa.me/{from_number}\n"
        f'Pesan terakhir: "{last_message}"\n\n'
        f"Chat aja di sini kalau mau diskusi dulu, nanti kalau udah fix jawabannya tinggal bilang "
        f'"terusin ke customer" (atau semacamnya), baru aku kirimin ke dia 👍'
    )
    send_whatsapp_message(OWNER_WHATSAPP_NUMBER, text)


def log_customer_message(to_number, message_text, sent_from="automated"):
    """Log setiap pesan yang dikirim ke customer (via forward atau direct command).
    Buat audit trail & tracking purposes. Log disimpan ke console & database jika aktif."""
    import time
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] → wa.me/{to_number} ({sent_from}): {message_text[:100]}..."
    print(log_entry)
    # Kalau perlu, bisa simpan ke database juga di masa depan
    if db_enabled():
        try:
            save_message_to_db(to_number, "customer", "assistant", f"[LOG-{sent_from}] {message_text}")
        except Exception:
            pass


def parse_direct_command(text):
    """Parse perintah langsung dari owner seperti 'kirim ke [nomor]...' atau 'follow up [nomor]...'.
    Return (target_number, message_content) jika ketemu, atau (None, None) jika bukan perintah direct."""
    # Pattern: "kirim ke 62xxx pesan..." atau "follow up 62xxx dengan..." etc
    import re

    # Cek pattern "kirim ke +62xxx [pesan]" atau "kirim ke 62xxx [pesan]"
    match = re.search(r'kirim\s+ke\s+((?:\+)?62\d+)\s+(.+)', text, re.IGNORECASE | re.DOTALL)
    if match:
        number = match.group(1).lstrip('+')
        if not number.startswith('62'):
            number = '62' + number
        message = match.group(2).strip()
        return (number, message)

    # Cek pattern "follow up [nomor] dengan [pesan]" atau "follow up [nomor] [pesan]"
    match = re.search(r'follow\s+up\s+((?:\+)?62\d+)\s+(?:dengan\s+)?(.+)', text, re.IGNORECASE | re.DOTALL)
    if match:
        number = match.group(1).lstrip('+')
        if not number.startswith('62'):
            number = '62' + number
        message = match.group(2).strip()
        return (number, message)

    return (None, None)


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta bakal manggil ini pas kita setup webhook, buat verifikasi."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verifikasi gagal", 403


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """Nerima pesan masuk dari WhatsApp, balas pakai AI, dan proses tag internal (leads panas /
    katalog / tanya owner / konfirmasi bayar)."""
    data = request.get_json()
    print("Webhook masuk:", data)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" not in value:
            # ini notifikasi status (delivered/read), bukan pesan baru -> abaikan
            return jsonify({"status": "ok"}), 200

        message = value["messages"][0]
        from_number = message["from"]
        incoming_message_id = message.get("id")
        msg_type = message.get("type")

        # ==== Ini pesan dari OWNER (nomor pribadi), bukan dari customer ====
        # Owner selalu direspon AI (mode "asisten pribadi"), bisa diskusi bebas dulu soal
        # pertanyaan customer yang pending. Baru kalau owner eksplisit nyuruh forward (AI kasih
        # tanda lewat FORWARD_MARKER di balasannya), jawaban final diterusin ke customer terkait.
        # Owner juga bisa kirim perintah langsung ("kirim ke..." atau "follow up...").
        if OWNER_WHATSAPP_NUMBER and from_number == OWNER_WHATSAPP_NUMBER:
            owner_image_b64, owner_image_mime = None, None

            if msg_type == "image":
                owner_image_meta = message.get("image", {})
                owner_caption = (owner_image_meta.get("caption") or "").strip()
                owner_media_id = owner_image_meta.get("id")
                owner_image_b64, owner_image_mime = (
                    download_whatsapp_media(owner_media_id) if owner_media_id else (None, None)
                )
                if not owner_image_b64:
                    send_whatsapp_message(from_number, "Gagal kebuka gambarnya, coba kirim ulang ya.")
                    return jsonify({"status": "ok"}), 200

                # Upload ulang ke media library kita sendiri (biar media_id-nya bisa dipake kirim
                # ulang ke customer kapan aja, gak terikat sama media_id asli punya WA)
                own_media_id = upload_media_bytes(base64.b64decode(owner_image_b64), owner_image_mime)

                # Kalau caption-nya langsung nyuruh forward ("kirim ke 628xxx..."), ini gambar
                # kayak QR code custom dll yang mau diterusin APA ADANYA (sebagai gambar, bukan
                # dideskripsiin doang) ke customer tertentu — WAJIB konfirmasi dulu kayak perintah
                # teks biasa.
                img_fwd_target, img_fwd_caption = parse_target_number(owner_caption) if owner_caption else (None, None)
                if img_fwd_target and own_media_id:
                    target_customer_name = customer_names.get(img_fwd_target, f"wa.me/{img_fwd_target}")
                    payload_b64 = base64.b64encode(json.dumps({
                        "target": img_fwd_target,
                        "media_id": own_media_id,
                        "mime": owner_image_mime,
                        "caption": img_fwd_caption,
                    }).encode()).decode()
                    owner_conversations.setdefault(from_number, []).append({
                        "role": "system",
                        "content": f"[PENDING_IMAGE_COMMAND:{payload_b64}]",
                    })
                    confirm_text = f"Jadi aku kirim GAMBAR ini ke {target_customer_name}"
                    if img_fwd_caption:
                        confirm_text += f" (caption: \"{img_fwd_caption}\")"
                    confirm_text += ".\n\nOke? (bilang 'terusin' atau 'oke' buat konfirmasi)"
                    send_whatsapp_message(from_number, confirm_text)
                    return jsonify({"status": "ok"}), 200

                # Bukan perintah forward — simpen dulu (siapa tau abis ini owner nyusul bilang
                # "kirim ke 628xxx" doang tanpa re-attach gambarnya)
                if own_media_id:
                    last_owner_image[from_number] = {"media_id": own_media_id, "mime": owner_image_mime}

                owner_text = owner_caption or "(aku kirim gambar, tolong liat & tanggapin)"
            elif msg_type != "text":
                return jsonify({"status": "ok"}), 200
            else:
                owner_text = message["text"]["body"]

                # Owner cuma bilang "kirim ke 628xxx" doang (gak ada pesan lain) DAN ada gambar
                # yang baru aja dia kirim sebelumnya tanpa instruksi -> anggap ini nyuruh forward
                # gambar itu (jadi owner gak perlu re-attach gambarnya lagi).
                only_target, only_extra = parse_target_number(owner_text)
                if only_target and not only_extra and from_number in last_owner_image:
                    img = last_owner_image[from_number]
                    target_customer_name = customer_names.get(only_target, f"wa.me/{only_target}")
                    payload_b64 = base64.b64encode(json.dumps({
                        "target": only_target,
                        "media_id": img["media_id"],
                        "mime": img.get("mime"),
                        "caption": None,
                    }).encode()).decode()
                    owner_conversations.setdefault(from_number, []).append({
                        "role": "system",
                        "content": f"[PENDING_IMAGE_COMMAND:{payload_b64}]",
                    })
                    send_whatsapp_message(
                        from_number,
                        f"Jadi aku kirim GAMBAR yang tadi kamu kirim ke {target_customer_name}.\n\n"
                        f"Oke? (bilang 'terusin' atau 'oke' buat konfirmasi)",
                    )
                    return jsonify({"status": "ok"}), 200

            # CEK apakah ini perintah langsung (kirim ke nomor X dengan pesan Y)
            direct_target, direct_message = parse_direct_command(owner_text)

            if direct_target:
                # Ini perintah langsung — lanjut ke proses konfirmasi & kirim
                # Tapi ada logika: jika target_number adalah customer yang lagi pending,
                # kita kirim. Jika customer lain, kita juga bisa kirim (follow up).
                # Dalam hal apapun, kita WAJIB konfirmasi.

                target_customer_name = customer_names.get(direct_target, f"wa.me/{direct_target}")

                # Format konfirmasi untuk ditampilkan ke owner
                confirmation_text = (
                    f"Jadi aku kirim ke {target_customer_name}:\n\n"
                    f"{direct_message}\n\n"
                    f"Oke? (bilang 'terusin' atau 'oke' buat konfirmasi)"
                )

                # Simpan pending direct command (nomor + pesan) buat diproses saat owner confirm
                # Kita store ini di struktur khusus
                pending_direct_command = {
                    "target_number": direct_target,
                    "message": direct_message,
                }
                owner_conversations.setdefault(from_number, []).append({
                    "role": "system",
                    "content": f"[PENDING_DIRECT_COMMAND: {direct_target}|{direct_message}]"
                })

                send_reply_bubbles(from_number, incoming_message_id, confirmation_text)
                return jsonify({"status": "ok"}), 200

            # Kalau bukan perintah langsung, ini obrolan normal
            # ambil pertanyaan customer yang paling lama nunggu (kalau ada) sebagai konteks
            pending_customer_number, pending_question = (None, None)
            if pending_owner_questions:
                pending_customer_number, pending_question = next(iter(pending_owner_questions.items()))

            # Kalau gak ada pertanyaan customer yang formal pending (misal owner nyeletuk duluan soal
            # customer yang baru aja chat, TANPA customer itu ngirim pertanyaan yang di-tag TANYA_OWNER),
            # fallback ke customer TERAKHIR yang beneran chat sama bot — ini bikin "terusin" tetap kerja
            # walau gak ada pending_question formal, sesuai request: begitu owner bilang terusin, WAJIB
            # beneran kekirim ke customer, gak boleh diem aja gara-gara gak ada konteks pending.
            if not pending_customer_number:
                pending_customer_number = active_customer_context.get(from_number)

            ai_owner_reply = call_claude_owner(
                from_number, owner_text, pending_question, pending_customer_number,
                image_b64=owner_image_b64, image_mime=owner_image_mime,
            )

            # CEK apakah owner bilang "terusin" / "oke" setelah konfirmasi perintah langsung
            # Deteksi kata kunci approval
            is_approval = any(keyword in owner_text.lower() for keyword in ["terusin", "oke", "ok", "lanjut", "go", "kirim"])

            # Cek apakah ada pending direct command (teks ATAU gambar) yang perlu dieksekusi —
            # ambil yang PALING BARU aja (baru discan dari belakang, berhenti begitu ketemu salah
            # satu jenis, biar gak ketuker sama command lama yang udah basi).
            pending_cmd = None
            pending_image_cmd = None
            owner_hist = owner_conversations.get(from_number, [])
            for msg in reversed(owner_hist):
                content = msg.get("content", "") if msg.get("role") == "system" else ""
                if "[PENDING_DIRECT_COMMAND:" in content:
                    try:
                        cmd_data = content.split("[PENDING_DIRECT_COMMAND: ")[1].split("]")[0]
                        target_num, msg_content = cmd_data.split("|", 1)
                        pending_cmd = {"target": target_num, "message": msg_content}
                    except Exception:
                        pass
                    break
                if "[PENDING_IMAGE_COMMAND:" in content:
                    try:
                        payload_b64 = content.split("[PENDING_IMAGE_COMMAND:")[1].split("]")[0]
                        pending_image_cmd = json.loads(base64.b64decode(payload_b64).decode())
                    except Exception:
                        pass
                    break

            if pending_image_cmd and is_approval:
                # Owner confirm forward GAMBAR — sama prinsipnya kayak pending_cmd teks: kirim
                # dulu, cek sukses beneran, baru omong ke owner & update memory.
                target_customer = pending_image_cmd["target"]
                img_media_id = pending_image_cmd["media_id"]
                img_caption = pending_image_cmd.get("caption")

                sent_ok, send_err = send_whatsapp_image(target_customer, img_media_id, img_caption)

                if sent_ok:
                    memory_note = "[ADMIN KIRIM GAMBAR]" + (f" {img_caption}" if img_caption else "")
                    history = conversations.get(target_customer, [])
                    history.append({"role": "assistant", "content": memory_note})
                    conversations[target_customer] = history[-20:]
                    save_message_to_db(target_customer, "customer", "assistant", memory_note)
                    log_customer_message(target_customer, memory_note, sent_from="direct_command_image")

                    owner_conversations[from_number] = [m for m in owner_hist if "[PENDING_IMAGE_COMMAND:" not in m.get("content", "")]
                    send_whatsapp_message(from_number, f"✅ Gambar udah beneran kekirim ke wa.me/{target_customer}")
                else:
                    send_whatsapp_message(
                        from_number,
                        f"⚠️ GAGAL kirim gambar ke wa.me/{target_customer} — belum kekirim ke customer sama sekali.\n"
                        f"Error: {send_err}\n\nCoba bilang 'terusin' lagi buat retry.",
                    )
                return jsonify({"status": "ok"}), 200

            if pending_cmd and is_approval:
                # Owner confirm perintah direct — KIRIM DULU, baru cek hasilnya sebelum ngomong
                # apa-apa ke owner. JANGAN PERNAH bilang "udah dikirim" sebelum beneran sukses
                # kekirim, dan JANGAN simpen ke memory kalau ternyata gagal (biar memory selalu
                # nyerminin apa yang BENERAN kejadian, bukan yang harusnya kejadian).
                target_customer = pending_cmd["target"]
                msg_to_send = pending_cmd["message"]

                sent_ok, send_err = send_reply_bubbles(target_customer, None, msg_to_send)

                # Bersihkan pending command dari histori owner cuma kalau udah beneran kekirim
                # (kalau gagal, biarin pending-nya biar owner bisa langsung bilang "terusin" lagi
                # buat retry tanpa harus ngetik ulang perintahnya dari awal)
                if sent_ok:
                    history = conversations.get(target_customer, [])
                    history.append({"role": "assistant", "content": msg_to_send})
                    conversations[target_customer] = history[-20:]
                    save_message_to_db(target_customer, "customer", "assistant", msg_to_send)
                    log_customer_message(target_customer, msg_to_send, sent_from="direct_command")

                    # Sama kayak forward biasa — catet ini jadi fakta fix, biar konsisten kalau
                    # customer nanya/konfirmasi ulang soal ini di kemudian hari.
                    add_agreed_fact(target_customer, msg_to_send)

                    owner_conversations[from_number] = [m for m in owner_hist if "[PENDING_DIRECT_COMMAND:" not in m.get("content", "")]
                    send_whatsapp_message(from_number, f"✅ Pesan udah beneran kekirim ke wa.me/{target_customer}")
                else:
                    send_whatsapp_message(
                        from_number,
                        f"⚠️ GAGAL kirim ke wa.me/{target_customer} — belum kekirim ke customer sama sekali.\n"
                        f"Error: {send_err}\n\n"
                        f"Coba bilang 'terusin' lagi buat retry, atau cek nomornya bener gak.",
                    )
                return jsonify({"status": "ok"}), 200

            if FORWARD_MARKER in ai_owner_reply and pending_customer_number:
                owner_facing, _, customer_facing = ai_owner_reply.partition(FORWARD_MARKER)
                owner_facing = owner_facing.strip() or "Oke siap, aku terusin ya!"
                customer_facing = customer_facing.strip()

                send_reply_bubbles(from_number, incoming_message_id, owner_facing)

                if customer_facing:
                    # KIRIM DULU ke customer, baru simpen ke memory & anggap pertanyaan ini selesai
                    # kalau BENERAN sukses kekirim. Kalau gagal, biarin pending_owner_questions-nya
                    # tetep ada (jangan didelete) & kasih tau owner jelas-jelas kalau gagal.
                    sent_ok, send_err = send_reply_bubbles(pending_customer_number, None, customer_facing)

                    if sent_ok:
                        history = conversations.get(pending_customer_number, [])
                        history.append({"role": "assistant", "content": customer_facing})
                        conversations[pending_customer_number] = history[-20:]
                        save_message_to_db(pending_customer_number, "customer", "assistant", customer_facing)
                        log_customer_message(pending_customer_number, customer_facing, sent_from="forward_from_owner")

                        # Catet ini sebagai FAKTA YANG UDAH FIX buat customer ini — biar bot gak
                        # PERNAH lagi bilang "belum dapet konfirmasi owner" untuk hal yang sebenernya
                        # udah beneran dijawab & dikirim ke customer ini.
                        fact_note = customer_facing
                        if pending_question:
                            fact_note = f"Soal '{pending_question}' — jawaban FINAL yang udah dikirim: {customer_facing}"
                        add_agreed_fact(pending_customer_number, fact_note)
                    else:
                        send_whatsapp_message(
                            from_number,
                            f"⚠️ GAGAL forward ke wa.me/{pending_customer_number} — belum kekirim ke customer.\n"
                            f"Error: {send_err}\n\nCoba bilang 'terusin' lagi buat retry.",
                        )
                        return jsonify({"status": "ok"}), 200

                del pending_owner_questions[pending_customer_number]
                sisa = len(pending_owner_questions)
                if sisa:
                    send_whatsapp_message(
                        OWNER_WHATSAPP_NUMBER,
                        f"Masih ada {sisa} pertanyaan lain yang nunggu jawaban kamu ya.",
                    )
            else:
                # belum ada instruksi forward -> ini masih obrolan/diskusi biasa sama owner
                send_reply_bubbles(from_number, incoming_message_id, ai_owner_reply)

            return jsonify({"status": "ok"}), 200

        image_b64, image_mime = None, None

        if msg_type == "image":
            # Customer kirim gambar (paling sering: bukti transfer). Download & convert ke base64
            # biar bisa "dilihat" langsung sama Claude (vision) — bukan cuma ditebak dari caption.
            image_meta = message.get("image", {})
            caption = (image_meta.get("caption") or "").strip()
            media_id = image_meta.get("id")
            image_b64, image_mime = download_whatsapp_media(media_id) if media_id else (None, None)

            if not image_b64:
                send_typing_indicator(incoming_message_id)
                time.sleep(1.2)
                send_whatsapp_message(from_number, "Gambarnya gagal kebuka nih kak, coba kirim ulang ya.")
                return jsonify({"status": "ok"}), 200

            user_text = caption or "(customer kirim gambar tanpa keterangan — cek isinya)"
        elif msg_type != "text":
            send_typing_indicator(incoming_message_id)
            time.sleep(1.5)
            send_whatsapp_message(from_number, "Saat ini admin cuma bisa baca pesan teks & gambar ya kak.")
            return jsonify({"status": "ok"}), 200
        else:
            user_text = message["text"]["body"]

        # Cek dulu apakah ini customer BARU (belum pernah chat sama sekali sebelumnya) SEBELUM
        # pesan ini diproses & disimpen — dipakai buat notifikasi "customer baru chat" ke owner,
        # yang cuma dikirim SEKALI per customer (bukan tiap pesan, biar gak spam ke WA owner).
        existing_history = conversations.get(from_number)
        if existing_history is None:
            existing_history = load_recent_messages_from_db(from_number, "customer")
        is_new_customer = not existing_history

        # Kalau kita belum tau nama customer ini, coba ambil dari profil WhatsApp-nya dulu (kalau
        # dia emang punya nama di profil WA) — biar AI gak perlu nanya-nanya lagi kalau namanya
        # udah kebaca otomatis dari sini.
        if from_number not in customer_names:
            try:
                wa_profile_name = value.get("contacts", [{}])[0].get("profile", {}).get("name")
            except Exception:
                wa_profile_name = None
            if wa_profile_name:
                customer_names[from_number] = wa_profile_name
                save_customer_name_to_db(from_number, wa_profile_name)

        # Update konteks "customer terakhir yang chat" — dipakai fallback kalau owner bilang "terusin"
        # tanpa ada pertanyaan formal pending (lihat active_customer_context).
        if OWNER_WHATSAPP_NUMBER:
            active_customer_context[OWNER_WHATSAPP_NUMBER] = from_number
        mark_customer_activity(from_number)

        ai_reply = call_claude(from_number, user_text, image_b64=image_b64, image_mime=image_mime)

        # Deteksi & tangkep nama customer (kalau AI baru dapet tau dari obrolan, bukan dari profil
        # WA) SEBELUM tag lain diproses, simpen ke cache + database, baru buang tag-nya dari teks.
        name_match = TAG_NAMA_PATTERN.search(ai_reply)
        if name_match:
            captured_name = name_match.group(1).strip()
            if captured_name:
                customer_names[from_number] = captured_name
                save_customer_name_to_db(from_number, captured_name)
            ai_reply = TAG_NAMA_PATTERN.sub("", ai_reply)

        # Deteksi tag internal SEBELUM di-strip, baru kirim versi bersih ke customer
        is_leads_panas = TAG_LEADS_PANAS in ai_reply or "[LEADS PANAS]" in ai_reply
        needs_owner = TAG_TANYA_OWNER in ai_reply
        wants_qr = TAG_KIRIM_QR in ai_reply
        wants_catalog = TAG_KIRIM_KATALOG in ai_reply
        payment_confirmed = TAG_SUDAH_BAYAR in ai_reply

        clean_reply = strip_tags(ai_reply)
        send_reply_bubbles(from_number, incoming_message_id, clean_reply)

        if wants_qr:
            send_qr_code(from_number)

        if wants_catalog:
            send_catalog_pdf(from_number)

        # Notifikasi ke owner SEKALI aja pas ada customer BARU yang pertama kali chat (biar owner
        # tau siapa aja yang chat, tanpa banjir notif tiap pesan dari customer yang sama).
        if is_new_customer:
            notify_owner_new_message(from_number, user_text, customer_names.get(from_number))

        if payment_confirmed:
            mark_customer_converted(from_number)  # stop follow-up otomatis, udah bayar

        if is_leads_panas:
            notify_owner(from_number, "LEADS PANAS — ada yang serius mau booking!", user_text)
        elif payment_confirmed:
            notify_owner(from_number, "Customer bilang udah transfer — tolong cek & verifikasi manual", user_text)
        elif needs_owner:
            pending_owner_questions[from_number] = user_text
            notify_owner_question(from_number, user_text)

    except Exception as e:
        print("Error processing webhook:", e)

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def health_check():
    return "Kilas Works AI Admin - server jalan!", 200


@app.route("/cron/followups", methods=["GET"])
def run_followups():
    """Endpoint yang HARUS dipanggil dari luar secara berkala (misal cron-job.org tiap 1 jam) buat
    ngirim follow-up otomatis ke customer yang udah diem >=12 jam & belum closing/bayar. Aman
    dipanggil sesering apapun — endpoint ini sendiri yang ngecek siapa aja yang beneran udah waktunya
    di-follow-up (gak akan dobel kirim), jadi gak perlu presisi 12 jam pas di sisi penjadwal luar.
    Akses: GET /cron/followups?key=<CRON_SECRET>
    """
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "Akses ditolak, key salah/kosong."}), 403

    due_numbers = get_customers_due_for_followup()
    results = []

    for number in due_numbers:
        try:
            # Minta AI generate follow-up yang PERSONAL berdasarkan history & fakta yang udah
            # disepakati customer ini (pakai infra yang sama kayak balasan biasa), bukan template
            # generik — biar kerasa natural, bukan kayak broadcast otomatis.
            nudge_instruction = (
                "(INSTRUKSI INTERNAL — INI FOLLOW-UP OTOMATIS, JANGAN TAMPILKAN TEKS INI KE CUSTOMER: "
                "customer ini udah diem 12+ jam sejak pesan terakhirnya. Sapa natural & singkat, "
                "tanyain apakah masih ada yang bisa dibantu atau masih tertarik lanjut soal obrolan "
                "sebelumnya — INGAT konteks obrolan lama, jangan mulai dari nol/nanya ulang hal yang "
                "udah dibahas. TANPA emoji, TANPA muji berlebihan, singkat & profesional.)"
            )
            ai_reply = call_claude(number, nudge_instruction, memory_override="[FOLLOW-UP OTOMATIS SISTEM]")
            clean_reply = strip_tags(TAG_NAMA_PATTERN.sub("", ai_reply))
            sent_ok, send_err = send_reply_bubbles(number, None, clean_reply)
            if sent_ok:
                record_followup_sent(number)
                log_customer_message(number, clean_reply, sent_from="auto_followup")
                results.append({"number": number, "status": "sent"})
            else:
                results.append({"number": number, "status": "failed", "error": send_err})
        except Exception as e:
            print(f"Gagal follow-up ke {number}: {e}")
            results.append({"number": number, "status": "error", "error": str(e)})

    return jsonify({"status": "ok", "checked": len(due_numbers), "results": results}), 200


def _escape_html(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Halaman sederhana buat owner lihat isi semua chat customer + chat sama AI (owner mode).
    Dibuka lewat: https://<domain-render-lu>/dashboard?key=<DASHBOARD_KEY>
    Kalau DATABASE_URL diset, datanya permanen (kesimpen di database). Kalau enggak,
    fallback ke memori server (ilang kalau server restart/sleep).
    """
    key = request.args.get("key", "")
    if not DASHBOARD_KEY or key != DASHBOARD_KEY:
        return "Akses ditolak. Tambahin ?key=... yang bener di URL.", 403

    def render_bubbles(history):
        rows = ""
        for msg in history:
            role = msg.get("role", "")
            content = _escape_html(msg.get("content", ""))
            align = "left" if role == "user" else "right"
            bg = "#e5e5ea" if role == "user" else "#25d366"
            color = "#000" if role == "user" else "#fff"
            rows += (
                f'<div style="text-align:{align};margin:6px 0;">'
                f'<span style="display:inline-block;max-width:70%;padding:8px 12px;'
                f'border-radius:12px;background:{bg};color:{color};white-space:pre-wrap;'
                f'font-size:14px;text-align:left;">{content}</span></div>'
            )
        return rows

    # Kalau database aktif, pakai data dari situ (lengkap, gak ilang pas restart).
    # Kalau enggak, fallback ke data di memori kayak sebelumnya.
    if db_enabled():
        customer_data = load_all_conversations_from_db("customer")
        owner_data = load_all_conversations_from_db("owner")
        db_note = ""
    else:
        customer_data = conversations
        owner_data = owner_conversations
        db_note = (
            '<p style="color:#c00;font-size:13px;">⚠️ Database belum aktif — history ini cuma '
            "sementara di memori server, bakal ilang kalau server restart.</p>"
        )

    sections = db_note

    names_lookup = load_all_customer_names_from_db() if db_enabled() else customer_names

    sections += "<h2>Chat Customer</h2>"
    if not customer_data:
        sections += "<p><i>Belum ada chat customer.</i></p>"
    else:
        for number, history in customer_data.items():
            name = names_lookup.get(number)
            label = f"{_escape_html(name)} — wa.me/{_escape_html(number)}" if name else _escape_html(number)
            pending = " ⏳ <b>(nunggu jawaban owner)</b>" if number in pending_owner_questions else ""
            sections += (
                f'<details style="margin-bottom:14px;border:1px solid #ddd;border-radius:8px;padding:10px;">'
                f'<summary style="cursor:pointer;font-weight:bold;">{label}{pending}'
                f' — {len(history)} pesan</summary>'
                f'<div style="margin-top:10px;">{render_bubbles(history)}</div></details>'
            )

    sections += "<h2>Chat Owner ↔ AI</h2>"
    if not owner_data:
        sections += "<p><i>Belum ada chat owner.</i></p>"
    else:
        for number, history in owner_data.items():
            sections += (
                f'<details open style="margin-bottom:14px;border:1px solid #ddd;border-radius:8px;padding:10px;">'
                f'<summary style="cursor:pointer;font-weight:bold;">{_escape_html(number)}'
                f' — {len(history)} pesan</summary>'
                f'<div style="margin-top:10px;">{render_bubbles(history)}</div></details>'
            )

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Kilas Works — Dashboard Chat</title>
        <meta http-equiv="refresh" content="30">
    </head>
    <body style="font-family:-apple-system,Arial,sans-serif;max-width:700px;margin:20px auto;padding:0 12px;">
        <h1>Kilas Works AI Admin — Dashboard</h1>
        <p style="color:#666;font-size:13px;">Auto-refresh tiap 30 detik.</p>
        {sections}
    </body>
    </html>
    """
    return html, 200


# Init database sekali pas modul ini di-load (baik dijalanin langsung via `python app.py`
# maupun lewat gunicorn di Render), sekalian seed cache nama customer dari database (kalau ada).
init_db()
customer_names.update(load_all_customer_names_from_db())
agreed_facts.update(load_all_customer_facts_from_db())
followup_state.update(load_all_followup_state_from_db())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
