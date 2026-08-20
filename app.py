import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==== KONFIGURASI (diambil dari environment variables) ====
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "kilasworks123")  # bebas, dipakai buat verifikasi webhook di Meta

# Simpan histori chat sederhana per nomor (in-memory, reset kalau server restart)
conversations = {}

SYSTEM_PROMPT = """Kamu adalah Admin Kilas Works, admin WhatsApp untuk bisnis jasa fotografi, videografi, dan
short-form content (Reels/TikTok) di Tangerang & Jakarta, Indonesia. Balas dengan gaya WhatsApp yang santai,
ramah, profesional, bahasa Indonesia sehari-hari. Jawaban singkat, maksimal 3-4 kalimat per balasan.

INFO BISNIS:
- Layanan: Fotografi, videografi, short-form content (Reels/TikTok), foto produk, produksi konten brand
- Lokasi: Tangerang & Jakarta (bisa didiskusikan kalau di luar itu)
- Paket:
  - Starter (konten only): Rp1.500.000 - Rp2.500.000/bulan
  - Growth (konten + AI admin): Rp3.500.000 - Rp5.000.000/bulan
  - Scale (all-in-one, konten + AI WA/IG + ads): Rp6.000.000 - Rp10.000.000/bulan
- Proses kerja: diskusi kebutuhan -> jadwal shoot/produksi -> editing -> revisi -> hasil akhir dikirim

ALUR:
1. Sapa ramah, tanya kebutuhan customer.
2. Jawab pertanyaan pakai info di atas. Kalau ga yakin, bilang "nanti dicek & di-confirm ya" (jangan ngarang).
3. Gali kebutuhan: jenis bisnis, kebutuhan konten (sekali produksi/rutin), budget, kapan mau mulai.
4. Kalau customer udah serius mau booking/lanjut, bilang bahwa nanti akan diteruskan ke tim (owner) untuk
   follow up lebih lanjut, dan sertakan "[LEADS PANAS]" di awal balasanmu supaya sistem tahu ini leads serius.
5. Jangan kasih harga final di luar range paket. Jangan janji jadwal pasti tanpa konfirmasi owner.
"""


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
    """Kirim pesan balasan lewat WhatsApp Cloud API."""
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
    """Nerima pesan masuk dari WhatsApp, balas pakai AI."""
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
        send_whatsapp_message(from_number, ai_reply)

    except Exception as e:
        print("Error processing webhook:", e)

    return jsonify({"status": "ok"}), 200


@app.route("/privacy", methods=["GET"])
def privacy_policy():
    return """
    <html>
    <head><title>Kebijakan Privasi - Kilas Works</title></head>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; line-height: 1.6;">
    <h1>Kebijakan Privasi Kilas Works</h1>
    <p>Terakhir diperbarui: 20 Agustus 2026</p>
    <p>Kilas Works ("kami") menghargai privasi Anda. Kebijakan ini menjelaskan bagaimana kami mengumpulkan, menggunakan, dan melindungi informasi Anda saat menggunakan layanan WhatsApp Admin AI kami.</p>
    <h2>Informasi yang Kami Kumpulkan</h2>
    <p>Kami mengumpulkan nomor WhatsApp dan isi percakapan yang Anda kirim ke Admin Kilas Works untuk keperluan menjawab pertanyaan, memberikan informasi layanan, dan menindaklanjuti kebutuhan Anda.</p>
    <h2>Penggunaan Informasi</h2>
    <p>Informasi yang dikumpulkan hanya digunakan untuk merespons pertanyaan Anda, memproses permintaan layanan, dan komunikasi terkait bisnis Kilas Works. Kami tidak menjual atau membagikan data Anda ke pihak ketiga untuk tujuan pemasaran.</p>
    <h2>Keamanan Data</h2>
    <p>Kami berupaya menjaga keamanan data Anda dengan langkah-langkah teknis yang wajar.</p>
    <h2>Kontak</h2>
    <p>Jika ada pertanyaan mengenai kebijakan privasi ini, hubungi kami di karnawiirvan2@gmail.com.</p>
    </body>
    </html>
    """, 200


@app.route("/", methods=["GET"])
def health_check():
    return "Kilas Works AI Admin - server jalan!", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
