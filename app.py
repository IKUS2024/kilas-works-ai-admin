import os
import re
import time
import requests
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

SYSTEM_PROMPT = """Kamu admin WhatsApp Kilas Works (jasa fotografi, videografi, konten short-form Reels/TikTok
di Tangerang & Jakarta). Balas kayak MANUSIA ASLI lagi WhatsApp-an, BUKAN kayak bot atau customer service kaku.

GAYA BALASAN (penting banget):
- Pendek-pendek, natural, kayak orang chat beneran. 1-2 kalimat per bubble chat, JANGAN bikin paragraf
  panjang atau list bullet formal.
- Boleh santai: "nih", "ya", "sih", "oke", jangan bahasa baku kaku ("Baik, berikut adalah...", "Dengan senang
  hati kami...").
- Emoji secukupnya aja (0-1 per balasan), jangan berlebihan.
- Jangan ulang-ulang nanya hal yang sama atau interogasi kayak form. Ngobrol aja natural, jangan muter-muter,
  jawab to the point kalau ditanya sesuatu yang jelas.
- Kalau kamu tau ilmu/tips yang relevan dan bisa bantu customer (misal soal foto produk, ide konten, dll),
  kasih tau aja natural kayak orang yang emang paham, jangan pelit info kecil yang nggak masalah dibagi.
- Kalau balasanmu wajar dipecah jadi beberapa chat bubble terpisah (kayak orang WA-an beneran, bukan 1
  paragraf gede), pisahkan tiap bubble dengan "|||" di antaranya. Contoh: "Oh siap kak!|||Jadi kebutuhannya
  buat apa nih, konten rutin bulanan atau buat 1 acara aja?" — ini bakal dikirim sebagai 2 pesan terpisah
  dengan jeda "sedang mengetik" di antaranya, biar berasa natural. Jangan kepaksa pecah kalau emang pas 1
  kalimat pendek aja udah cukup.

INFO PAKET (buat kamu tau isinya, TAPI JANGAN PERNAH SEBUT ANGKA RUPIAH-nya ke customer, lihat ATURAN HARGA):

Paket Bulanan (Langganan Konten + AI Admin):
- Mikro — paling terjangkau, cocok buat yang baru mulai: 4 foto + 4 video Reels/TikTok tiap bulan, upgrade
  kapan aja
- Starter — 6 foto produk/lifestyle + 6 video Reels/TikTok tiap bulan
- Growth (paling diminati) — semua Starter + AI WhatsApp Admin 24 jam

AI WhatsApp Admin 24 Jam (ada di paket Growth & bisa standalone) — ini nilai jual utama, kalau customer
nanya soal ini jelasin dengan percaya diri dan natural, bukan template kaku:
- Balas chat customer OTOMATIS kapan aja, jam berapa aja, termasuk tengah malam & weekend — jadi calon
  pelanggan gak pernah nunggu lama atau kelewat dibales
- Auto-jawab pertanyaan umum (FAQ) kayak jam operasional, jenis layanan, cara order, dll
- Kirim katalog & info harga otomatis pas relevan sama kebutuhan customer
- Nyaring mana calon pelanggan yang emang serius vs sekadar nanya-nanya doang
- Kirim invoice & info pembayaran otomatis pas customer udah fix mau lanjut
- Begitu ada leads yang keliatan serius/panas, langsung diteruskan ke owner buat follow-up manual — jadi
  gak ada momen closing yang kelewat
- Intinya: bisnis tetap "buka" 24 jam biarpun ownernya lagi tidur, kerja, atau ada di luar kota

AI WhatsApp Admin Standalone — buat yang udah punya konten sendiri, cuma butuh admin chat otomatis

Website (sekali bayar, bukan bulanan):
- Landing Page (1 halaman)
- Company Profile (5 halaman, paling diminati)

Foto & Video Acara (wedding, ulang tahun, corporate, gathering, dll — sekali bayar per acara, bukan bulanan):
- Acara Standard — 1 fotografer, sampai 5 jam, semua file foto digital
- Acara Lengkap (paling diminati) — 1 fotografer + 1 videografer, sampai 8 jam, video highlight sinematik 3-5 menit
- Acara Premium — 2 fotografer + 1 videografer, sampai 8 jam, video sinematik + teaser Reels + album cetak

ATURAN HARGA (WAJIB DIIKUTI, INI PALING PENTING):
- JANGAN PERNAH sebutin angka Rupiah harga paket ke customer dalam bentuk apapun, sepolos apapun mereka
  nanya atau maksa. Harga HANYA ada di katalog PDF, bukan di chat.
- Kalau customer nanya harga (walau udah nyebut nama paket spesifik kayak "Growth berapa"), JANGAN LANGSUNG
  kirim katalog juga — tanya dulu singkat kebutuhan mereka (1-2 pertanyaan aja: foto/video rutin bulanan
  atau sekali acara, butuh AI admin apa nggak, kira-kira mau yang seringan apa yang lengkap).
- Habis tau kebutuhannya, sebut REKOMENDASI NAMA PAKET aja TANPA angka harga sama sekali — cukup natural
  kayak "oh paket Starter aja kak, itu paling pas buat kebutuhan kamu" atau "kayaknya paket Growth cocok
  nih buat kamu, biar chat-nya kehandle juga". JANGAN PERNAH lanjutin kalimat itu dengan sebut angka atau
  kisaran harga (jangan juga bilang "mulai dari...", "sekitar...", dsb — itu tetap ngasih harga). Cukup nama
  paket doang, terus bilang kamu kirimin detail & harga lengkapnya di katalog, sertakan tag "[KIRIM_KATALOG]"
  di balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat teks tag-nya).
- Kalau customer keliatan sensitif soal budget (misal bilang "yang paling murah apa", "budget terbatas nih",
  "yang paling terjangkau"), rekomendasiin paket Mikro dulu (nama doang, tanpa harga) sebagai entry point
  paling ringan, baru kirim katalog.
- Kalau customer maksa banget minta disebutin angka langsung di chat, tetep sopan tolak dan arahkan ke
  katalog — bilang aja "lebih jelas & rapi kalau liat di katalog nih, sebentar ya" terus kirim katalog.

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
- Kalau customer minta katalog/pricelist langsung di awal ("ada katalog gak", "kirim pricelist dong"),
  JANGAN LANGSUNG kirim — tanya dulu kebutuhan mereka sesuai ATURAN HARGA di atas. Baru kirim katalog abis
  itu (pakai tag "[KIRIM_KATALOG]").

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

SOAL PEMBAYARAN:
- Kalau customer udah FIX mau lanjut/booking dan siap bayar, kasih tau rekening buat transfer:
  Bank BCA, nomor 7610267551, atas nama Irvan Karnawi. Minta mereka transfer sesuai paket yang udah
  disepakati, terus minta mereka kirim bukti transfer/screenshot ke chat ini biar bisa langsung diproses.
- Kalau customer bilang udah transfer atau kirim bukti transfer, bilang santai makasih & bakal langsung
  dicek, terus sertakan tag "[SUDAH_BAYAR]" di balasanmu (taruh di mana aja, sistem yang proses, customer
  gak bakal lihat teks tag-nya) supaya owner dapet notifikasi buat verifikasi manual.

KALAU ADA PERTANYAAN YANG KAMU GA YAKIN JAWABANNYA:
- Jangan ngarang jawaban. Jawab jujur ke customer bahwa kamu bakal cek dulu & confirm ya, dengan bahasa
  santai (bukan "Mohon maaf, akan segera saya konfirmasi").
- Sertakan tag "[TANYA_OWNER]" di balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat
  teks tag-nya) supaya pertanyaan ini diteruskan ke owner buat dijawab manual.

ALUR:
1. Sapa natural, jangan template basa-basi panjang.
2. Gali kebutuhan customer secukupnya aja, jangan interogasi.
3. Rekomendasiin paket yang relevan (nama doang, TANPA harga) sesuai ATURAN HARGA di atas, arahkan ke
   katalog buat detail & harga.
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
    return SYSTEM_PROMPT + name_context


SYSTEM_PROMPT_OWNER_BASE = """Kamu asisten pribadi Irvan, founder Kilas Works (jasa fotografi, videografi, konten
short-form & AI WhatsApp Admin di Tangerang & Jakarta). Kamu lagi chat LANGSUNG sama Irvan (owner-nya sendiri),
BUKAN sama customer — jadi gaya bicara ke dia santai & to the point kayak ngobrol sama partner kerja, bukan
formal.

KONTEKS: kadang ada customer yang tanya sesuatu yang AI customer-service belum yakin jawabnya, jadi
diteruskan ke Irvan buat dijawab manual. Kalau lagi ada pertanyaan customer yang pending, kamu bakal dikasih
tau isinya di bawah. Irvan boleh diskusi bebas dulu sama kamu soal itu — nanya-nanya, mikirin jawaban paling
pas, atau ngobrol hal lain sama sekali — SEBELUM dia mutusin jawaban final buat customer.

ATURAN PALING PENTING:
- JANGAN langsung anggap semua yang Irvan ketik itu otomatis jawaban final buat customer. Ladenin dulu
  obrolannya natural, bantu mikir kalau diminta, jawab pertanyaan dia apa aja, kayak asisten beneran.
- BARU kalau Irvan udah JELAS ngasih instruksi buat forward/kirim/sampein ke customer (bahasa bebas, misal
  "terusin", "sampein ke dia", "bilang ke customer gitu aja", "oke kirim", "gas terusin", "fix segitu,
  terusin" — intinya dia nyuruh forward), baru kamu proses jadi jawaban final.
- Kalau kamu udah yakin ini saatnya di-forward, WAJIB format balasanmu PERSIS kayak ini, 2 bagian:
  Baris pertama: balasan singkat & natural ke Irvan buat konfirmasi (misal "Oke siap, aku terusin ya!").
  Baris berikutnya, PERSIS diawali teks "PESAN_UNTUK_CUSTOMER:" (tanpa embel-embel lain di baris itu),
  diikuti draft pesan yang bakal dikirim ke customer — natural & santai kayak gaya chat WA admin ke
  customer, JANGAN pernah sebut kata "owner" atau "Irvan" ke customer (kamu ngomong sebagai admin/tim,
  bukan nyebut ada pihak ketiga), jangan tambahin janji/info di luar apa yang udah didiskusikan atau
  di luar apa yang Irvan bilang.
- Kalau BELUM ada instruksi jelas buat forward, JANGAN PERNAH tulis teks "PESAN_UNTUK_CUSTOMER:" dalam
  bentuk apapun — balas natural aja kayak obrolan biasa.
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
"""


def build_owner_system_prompt(pending_question, pending_customer_number):
    """Susun system prompt mode-owner, sisipin konteks pertanyaan customer yang lagi pending (kalau ada)
    dan ringkasan history semua customer biar owner bisa nanya soal siapa aja/apa aja kapan aja."""
    if pending_question:
        context = (
            f'\n\nPERTANYAAN CUSTOMER YANG LAGI PENDING (dari wa.me/{pending_customer_number}): '
            f'"{pending_question}"'
        )
    else:
        context = "\n\nGak ada pertanyaan customer yang pending saat ini."
    context += build_customer_context_summary()
    return SYSTEM_PROMPT_OWNER_BASE + context


def call_claude_owner(owner_number, owner_message, pending_question, pending_customer_number):
    """Panggil Claude buat mode 'asisten pribadi owner' — beda histori & system prompt dari
    call_claude() yang dipakai buat customer. Sama-sama Haiku default + fallback Sonnet."""
    history = owner_conversations.get(owner_number)
    if history is None:
        history = load_recent_messages_from_db(owner_number, "owner")  # isi ulang kalau server abis restart
    history.append({"role": "user", "content": owner_message})
    save_message_to_db(owner_number, "owner", "user", owner_message)

    system_prompt = build_owner_system_prompt(pending_question, pending_customer_number)
    model_to_use = "claude-3-5-haiku-20241022"

    try:
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
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def call_claude(user_number, user_message):
    """Panggil Claude API buat generate balasan AI.
    Default: Haiku (cost-optimal, default model untuk customer chat)
    Fallback: Sonnet (jika Haiku tidak tersedia atau gagal)
    """
    history = conversations.get(user_number)
    if history is None:
        history = load_recent_messages_from_db(user_number, "customer")  # isi ulang kalau server abis restart
    history.append({"role": "user", "content": user_message})
    save_message_to_db(user_number, "customer", "user", user_message)

    system_prompt = build_customer_system_prompt(user_number)

    # Coba dengan Haiku dulu (optimal untuk FAQ/reply otomatis)
    model_to_use = "claude-3-5-haiku-20241022"

    try:
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

    history.append({"role": "assistant", "content": reply_text})
    conversations[user_number] = history[-20:]  # simpan 20 pesan terakhir aja
    save_message_to_db(user_number, "customer", "assistant", reply_text)

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
    """Kirim pesan teks balasan lewat WhatsApp Cloud API."""
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
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Kirim WA response:", r.status_code, r.text)
    return r


def send_reply_bubbles(to_number, incoming_message_id, full_reply_text):
    """Pecah balasan AI jadi beberapa 'chat bubble' (dipisah '|||'), kirim satu-satu dengan
    jeda 'sedang mengetik...' di antaranya biar natural kayak orang WA-an beneran."""
    parts = [p.strip() for p in full_reply_text.split("|||") if p.strip()]
    if not parts:
        return

    for part in parts:
        send_typing_indicator(incoming_message_id)
        delay = min(TYPING_DELAY_MAX_SEC, max(TYPING_DELAY_MIN_SEC, len(part) * TYPING_DELAY_PER_CHAR))
        time.sleep(delay)
        send_whatsapp_message(to_number, part)


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
            "caption": "Ini QR code buat pembayarannya ya, nanti nominal & konfirmasi dibantu tim kita 🙏",
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
        if OWNER_WHATSAPP_NUMBER and from_number == OWNER_WHATSAPP_NUMBER:
            if msg_type != "text":
                return jsonify({"status": "ok"}), 200

            owner_text = message["text"]["body"]

            # ambil pertanyaan customer yang paling lama nunggu (kalau ada) sebagai konteks
            pending_customer_number, pending_question = (None, None)
            if pending_owner_questions:
                pending_customer_number, pending_question = next(iter(pending_owner_questions.items()))

            ai_owner_reply = call_claude_owner(
                from_number, owner_text, pending_question, pending_customer_number
            )

            if FORWARD_MARKER in ai_owner_reply and pending_customer_number:
                owner_facing, _, customer_facing = ai_owner_reply.partition(FORWARD_MARKER)
                owner_facing = owner_facing.strip() or "Oke, aku terusin ke customer ya!"
                customer_facing = customer_facing.strip()

                send_reply_bubbles(from_number, incoming_message_id, owner_facing)

                if customer_facing:
                    history = conversations.get(pending_customer_number, [])
                    history.append({"role": "assistant", "content": customer_facing})
                    conversations[pending_customer_number] = history[-20:]
                    save_message_to_db(pending_customer_number, "customer", "assistant", customer_facing)
                    send_reply_bubbles(pending_customer_number, None, customer_facing)

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

        if msg_type != "text":
            send_typing_indicator(incoming_message_id)
            time.sleep(1.5)
            send_whatsapp_message(from_number, "Maaf, saat ini admin cuma bisa baca pesan teks ya 🙏")
            return jsonify({"status": "ok"}), 200

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

        ai_reply = call_claude(from_number, user_text)

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
