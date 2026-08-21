import os
import re
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==== KONFIGURASI (diambil dari environment variables) ====
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "kilasworks123")  # bebas, dipakai buat verifikasi webhook di Meta

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

# ===== CENTRALIZED PRICING CONFIG (SATU SUMBER KEBENARAN) =====
PRICING_CONFIG = {
    "pakets_bulanan": {
        "mikro": {
            "nama": "Mikro",
            "harga": 999000,
            "deskripsi": "2 foto + 2 video Reels/TikTok per bulan, cocok buat yang baru mulai",
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
- Mikro — paling terjangkau, cocok buat yang baru mulai: 2 foto + 2 video Reels/TikTok tiap bulan, upgrade
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
4. Kalau customer udah serius mau booking/lanjut (leads panas), sertakan tag "[LEADS_PANAS]" di balasanmu
   (taruh di mana aja, sistem yang proses, customer gak bakal lihat teks tag-nya) supaya diteruskan ke owner.
5. Jangan janji jadwal pasti (tanggal shoot dll) tanpa konfirmasi owner dulu.
"""

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
    history = conversations.get(user_number, [])
    history.append({"role": "user", "content": user_message})

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
                "system": SYSTEM_PROMPT,
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
                "system": SYSTEM_PROMPT,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()

    data = resp.json()
    reply_text = data["content"][0]["text"]

    history.append({"role": "assistant", "content": reply_text})
    conversations[user_number] = history[-20:]  # simpan 20 pesan terakhir aja

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


def notify_owner(from_number, reason, last_message):
    """Kirim notifikasi ke WA pribadi owner (bukan nomor bot) soal leads panas, pertanyaan yang
    perlu dijawab manual, atau konfirmasi pembayaran."""
    if not OWNER_WHATSAPP_NUMBER:
        return
    text = (
        f"🔔 {reason}\n\n"
        f"Dari: wa.me/{from_number}\n"
        f'Pesan terakhir: "{last_message}"\n\n'
        f"Cek & follow up langsung ke nomor itu ya."
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

        if msg_type != "text":
            send_typing_indicator(incoming_message_id)
            time.sleep(1.5)
            send_whatsapp_message(from_number, "Maaf, saat ini admin cuma bisa baca pesan teks ya 🙏")
            return jsonify({"status": "ok"}), 200

        user_text = message["text"]["body"]

        ai_reply = call_claude(from_number, user_text)

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

        if is_leads_panas:
            notify_owner(from_number, "LEADS PANAS — ada yang serius mau booking!", user_text)
        elif payment_confirmed:
            notify_owner(from_number, "Customer bilang udah transfer — tolong cek & verifikasi manual", user_text)
        elif needs_owner:
            notify_owner(from_number, "Ada pertanyaan yang AI belum yakin jawabnya, tolong cek manual", user_text)

    except Exception as e:
        print("Error processing webhook:", e)

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def health_check():
    return "Kilas Works AI Admin - server jalan!", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
