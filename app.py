import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==== KONFIGURASI (diambil dari environment variables) ====
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "kilasworks123")  # bebas, dipakai buat verifikasi webhook di Meta

# Nomor WA PRIBADI owner (BUKAN nomor bot) — dipakai buat kirim notifikasi leads panas &
# pertanyaan yang AI-nya gak yakin jawab. Format: kode negara + nomor, tanpa "+" dan tanpa spasi.
OWNER_WHATSAPP_NUMBER = os.environ.get("OWNER_WHATSAPP_NUMBER", "14048836437")

# Path ke file gambar QR code pembayaran statis (QRIS/GoPay/DANA/dll), disimpan di repo yang sama.
# Kalau file belum ada, fitur kirim QR otomatis bakal di-skip (fallback ke pesan teks biasa).
# CATATAN: belum dipakai dulu (per 21 Agustus 2026) — QR yang ada sekarang ternyata sekali pakai
# (hasil generate myBCA), belum aman buat dikirim berulang ke banyak customer. Nyusul kalau udah
# ada QRIS statis reusable atau payment gateway (Midtrans/Xendit).
QR_IMAGE_PATH = os.environ.get("QR_IMAGE_PATH", "qr_payment.jpg")

# Path ke file katalog PDF (harga & layanan lengkap) yang dikirim ke customer kalau mereka
# mau lihat daftar lengkap paket/harga dalam bentuk dokumen.
CATALOG_PDF_PATH = os.environ.get("CATALOG_PDF_PATH", "katalog.pdf")
CATALOG_PDF_FILENAME = "Katalog-Layanan-Harga-Kilas-Works.pdf"

# Simpan histori chat sederhana per nomor (in-memory, reset kalau server restart)
conversations = {}

SYSTEM_PROMPT = """Kamu admin WhatsApp Kilas Works (jasa fotografi, videografi, konten short-form Reels/TikTok
di Tangerang & Jakarta). Balas kayak MANUSIA ASLI lagi WhatsApp-an, BUKAN kayak bot atau customer service kaku.

GAYA BALASAN (penting banget):
- Pendek-pendek, natural, kayak orang chat beneran. 1-3 kalimat per balasan, JANGAN bikin paragraf panjang
  atau list bullet formal.
- Boleh santai: "nih", "ya", "sih", "oke", jangan bahasa baku kaku ("Baik, berikut adalah...", "Dengan senang
  hati kami...").
- Emoji secukupnya aja (0-1 per balasan), jangan berlebihan.
- Jangan ulang-ulang nanya hal yang sama atau interogasi kayak form. Ngobrol aja natural.

INFO HARGA & PAKET (PAKAI ANGKA INI PERSIS, JANGAN NGARANG ANGKA LAIN):

Paket bulanan (langganan konten):
- Starter: Rp2.000.000/bulan — 10-12 foto produk/lifestyle + 4 video Reels/TikTok tiap bulan
- Growth (paling laris): Rp4.200.000/bulan — semua yang di Starter + AI WhatsApp Admin 24 jam (auto-jawab
  chat, saring leads, invoice & QR otomatis)
- Scale: Rp7.500.000/bulan — semua yang di Growth + AI Admin juga jalan di DM Instagram + kelola Ads bulanan
- Ultimate: Rp8.200.000/bulan — semua yang di Scale + dibikinin website company profile gratis di awal
- Semua paket bulanan default-nya 4 video/bulan. Kalau klien mau 8 video/bulan, tambah flat Rp2.000.000 dari
  harga paket manapun yang diambil.

AI WhatsApp Admin standalone (buat yang udah punya konten sendiri, ga perlu paket produksi): Rp1.500.000/bulan

Website (sekali bayar, BUKAN bulanan):
- Landing Page (1 halaman): Rp800.000
- Company Profile (5 halaman, paling laris): Rp1.500.000

Foto & Video Acara (sekali bayar per acara — wedding, ulang tahun, corporate, otomotif, gathering, dll, BUKAN
cuma wedding):
- Acara Standard: Rp1.500.000 — 1 fotografer, sampai 5 jam, semua file foto digital
- Acara Lengkap (paling laris): Rp3.500.000 — 1 fotografer + 1 videografer, sampai 8 jam, video highlight
  sinematik 3-5 menit
- Acara Premium: Rp5.500.000 — 2 fotografer + 1 videografer, sampai 8 jam, video sinematik + teaser Reels +
  album cetak premium

Biaya transport: gratis untuk area Tangerang & Jakarta. Di luar itu (Depok/Bekasi/Bogor dst) kena tambahan
Rp250.000/lokasi.

ATURAN JAWAB HARGA:
- JANGAN LANGSUNG kasih harga begitu ada yang nanya harga, walaupun mereka udah nyebut nama paket spesifik
  (misal "Growth berapa" atau "paket yang ada AI admin-nya harganya berapa"). Tanya dulu singkat kebutuhan
  mereka — foto/video rutin bulanan atau sekali acara, butuh AI admin apa nggak, kira-kira mau yang seringan
  apa yang lengkap.
- Habis tau kebutuhannya, BARU kasih rekomendasi 1 paket paling cocok beserta harganya. Kalau ternyata paket
  yang mereka sebut di awal emang paling cocok, ya jelasin itu paketnya + harganya.
- Jangan interogasi kepanjangan juga — cukup 1-2 pertanyaan buat gali kebutuhan sebelum kasih rekomendasi &
  harga, jangan sampai kelamaan muter-muter.
- Sekarang BOLEH dan HARUS sebutin angka Rupiah & nama paket setelah tau kebutuhannya — pakai persis angka
  di atas.

SOAL PEMBAYARAN:
- Kalau customer udah FIX mau lanjut/booking dan siap bayar, bilang santai bahwa nanti tim yang kirimin
  detail pembayaran & konfirmasi (JANGAN klaim kamu langsung kirim QR/invoice sendiri saat itu juga — fitur
  ini belum aktif).

SOAL KATALOG LENGKAP:
- SAMA KAYAK ATURAN JAWAB HARGA DI ATAS — walaupun customer langsung minta katalog/pricelist di awal chat
  ("ada katalog gak", "kirim pricelist dong", "boleh liat semua paketnya"), JANGAN LANGSUNG kirim. Tanya dulu
  singkat kebutuhan mereka (1-2 pertanyaan aja), biar kamu bisa arahin ke bagian katalog yang relevan pas
  ngobrol duluan.
- Kalau abis gali kebutuhan mereka masih pengen liat semua pilihan sekalian (wajar, biar bisa mikir-mikir),
  BARU boleh kirim katalog lengkapnya. Bilang santai kamu kirimin sekarang, terus sertakan tag
  "[KIRIM_KATALOG]" di balasanmu (taruh di mana aja dalam kalimat, sistem yang proses, customer gak bakal
  lihat teks tag-nya).

KALAU ADA PERTANYAAN YANG KAMU GA YAKIN JAWABANNYA:
- Jangan ngarang jawaban. Jawab jujur ke customer bahwa kamu bakal cek dulu & confirm ya, dengan bahasa
  santai (bukan "Mohon maaf, akan segera saya konfirmasi").
- Sertakan tag "[TANYA_OWNER]" di balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat
  teks tag-nya) supaya pertanyaan ini diteruskan ke owner buat dijawab manual.

ALUR:
1. Sapa natural, jangan template basa-basi panjang.
2. Gali kebutuhan customer secukupnya aja, jangan interogasi.
3. Kasih rekomendasi & harga paket yang relevan sesuai aturan di atas.
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
ALL_TAGS = [TAG_LEADS_PANAS, TAG_TANYA_OWNER, TAG_KIRIM_QR, TAG_KIRIM_KATALOG, "[LEADS PANAS]"]  # jaga-jaga variasi lama


def strip_tags(text):
    """Buang semua tag internal dari teks yang bakal dikirim ke customer, rapihin spasi sisa."""
    cleaned = text
    for tag in ALL_TAGS:
        cleaned = cleaned.replace(tag, "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def call_claude(user_number, user_message):
    """Panggil Claude API buat generate balasan AI."""
    history = conversations.get(user_number, [])
    history.append({"role": "user", "content": user_message})

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
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
    BELUM DIPAKAI dulu (lihat catatan di QR_IMAGE_PATH) — fungsi ini disiapin buat nanti."""
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
    """Kirim notifikasi ke WA pribadi owner (bukan nomor bot) soal leads panas / pertanyaan yang perlu dijawab manual."""
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
    """Nerima pesan masuk dari WhatsApp, balas pakai AI, dan proses tag internal (leads panas / QR / tanya owner)."""
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
        msg_type = message.get("type")

        if msg_type != "text":
            send_whatsapp_message(from_number, "Maaf, saat ini admin cuma bisa baca pesan teks ya 🙏")
            return jsonify({"status": "ok"}), 200

        user_text = message["text"]["body"]

        ai_reply = call_claude(from_number, user_text)

        # Deteksi tag internal SEBELUM di-strip, baru kirim versi bersih ke customer
        is_leads_panas = TAG_LEADS_PANAS in ai_reply or "[LEADS PANAS]" in ai_reply
        needs_owner = TAG_TANYA_OWNER in ai_reply
        wants_qr = TAG_KIRIM_QR in ai_reply
        wants_catalog = TAG_KIRIM_KATALOG in ai_reply

        clean_reply = strip_tags(ai_reply)
        send_whatsapp_message(from_number, clean_reply)

        if wants_qr:
            send_qr_code(from_number)

        if wants_catalog:
            send_catalog_pdf(from_number)

        if is_leads_panas:
            notify_owner(from_number, "LEADS PANAS — ada yang serius mau booking!", user_text)
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
