"""Small deterministic intent routing for the customer-facing composer."""
import re


def mode_for(content, attachments=()):
    text = content.lower()
    difficult = (
        r"\b(?:debug|refactor|optimasi|architecture|arsitektur|implementasi|analisis mendalam|"
        r"rencana strategis|multi.?step|langkah demi langkah yang kompleks)\b",
        r"\b(?:bandingkan|compare|perbandingan)\b.*\b(?:dua|2|beberapa|multiple)\b.*\b(?:dokumen|file|laporan)\b",
    )
    documents = sum(bool(item.get("extracted_text")) for item in attachments)
    if documents >= 2 and re.search(r"\b(?:bandingkan|compare|analisis|sintesis)\b", text):
        return "SMART"
    return "SMART" if any(re.search(pattern, text) for pattern in difficult) else "FAST"


def _normalize(content):
    text = " ".join((content or "").lower().split())
    text = re.sub(r"\b(?:buatkan|bikinkan|bikinin|bikin)\b", "buat", text)
    text = re.sub(r"\b(?:gambarkan|gambarin|gamabar|gmbar|gmbaar|gambarr)\b", "gambar", text)
    text = re.sub(r"\bgambarnya\b", "gambar", text)
    text = re.sub(r"\bpdf(?:-?nya)\b", "pdf", text)
    return text


def _discussion(text):
    return bool(re.search(
        r"^(?:apa (?:itu|arti)|what is|jelaskan cara|bagaimana cara|cara |how (?:to|do)|"
        r"kenapa|mengapa|why |model |berapa harga|berapa biaya|perbedaan |"
        r"tolong (?:jelaskan|terangkan) cara)\b", text))


def _edit_intent(text, has_image):
    action = r"(?:edit|ubah|ganti|hapus|hilangkan|remove|change|crop|retouch|rapihin|rapikan|terangkan|cerahkan)"
    if has_image:
        return bool(re.search(r"\b" + action + r"\b|\bbackground\s+(?:putih|polos|transparan)\b|\b(?:lebih\s+terang|jadi\s+kartun)\b", text))
    return bool(re.search(r"\b" + action + r"\b.{0,60}\b(?:gambar|foto|image|background|latar|warna|baju(?:nya)?|mobil|wajah(?:nya)?|kartun|ini)\b|"
                          r"\b(?:gambar|foto|image)\b.{0,35}\b" + action + r"\b|"
                          r"\bbackground\s+(?:putih|polos|transparan)\b", text))


def may_edit_image(content):
    text = _normalize(content)
    return not _discussion(text) and _edit_intent(text, True)


def _pdf_intent(text, has_previous_content):
    if not re.search(r"\bpdf\b", text):
        return False
    if re.search(r"\b(?:buat|jadikan|ubah|export|ekspor|simpan|download|unduh|kirim|rapikan|cetak|hasilkan|convert|format)\b", text):
        return True
    if re.search(r"\b(?:dalam bentuk|ke format|sebagai|jadi|file)\s+pdf\b", text):
        return True
    return has_previous_content and bool(re.search(r"(?:^|\s)pdf\s*(?:dong|ya|please|saja)?[.!?]*$", text))


def tool_for(content, attachments=(), *, search=False, pdf_request=False,
             has_previous_content=False):
    text = _normalize(content)
    if search:
        return "WEB"
    if _discussion(text):
        return "CHAT"
    has_image = any(item.get("mime_type", "").startswith("image/") for item in attachments)
    if has_image and not (pdf_request or _pdf_intent(text, has_previous_content)) and _edit_intent(text, True):
        return "IMAGE_EDIT"
    if pdf_request or _pdf_intent(text, has_previous_content):
        return "PDF"
    if _edit_intent(text, False):
        return "IMAGE_EDIT"
    visual = r"(?:gambar|foto|ilustrasi|poster|image|picture|photo|visual)"
    create = r"(?:buat|create|generate|draw|lukis|gambarkan)"
    if re.search(r"\b" + create + r"\b.{0,75}\b" + visual + r"\b|\b(?:draw|lukis)\s+\S+", text):
        return "IMAGE_GENERATE"
    if not has_image and re.match(r"^gambar\s+(?!ini\b|itu\b|apa\b|yang\b|tersebut\b)\S+", text):
        return "IMAGE_GENERATE"
    return "CHAT"


def image_prompt(content, previous_answer=""):
    """Carry a nearby visual concept into a short image-creation follow-up."""
    if (previous_answer and len(content) <= 120 and
            re.search(r"\b(?:gambarnya|visualnya|sekarang|tadi|dari konsep|dari ide)\b", content.lower()) and
            re.search(r"\b(?:poster|gambar|ilustrasi|desain|visual|image|foto)\b", previous_answer.lower())):
        return "Konsep sebelumnya:\n" + previous_answer[:1800] + "\n\nBuat gambar sesuai permintaan terbaru: " + content
    return content


def enhance_image_prompt(prompt, requested_action_text=None):
    """Keep the user's wording and make a requested visible action unambiguous."""
    text = (requested_action_text or prompt).lower()
    if re.search(r"\b(?:nyanyi|menyanyi|bernyanyi|singing|sing)\b", text):
        return prompt + "\nAksi utama harus tampak jelas: subjek sedang bernyanyi, mulut terbuka saat menyanyi, bukan hanya berpose. Pertahankan subjek, gaya, dan detail yang diminta."
    if re.search(r"\b(?:menari|berlari|memasak|melukis|membaca|menulis|dancing|running|cooking|painting|reading|writing)\b", text):
        return prompt + "\nTampilkan aksi utama yang diminta dengan jelas, bukan pose diam. Pertahankan subjek, gaya, dan detail yang diminta."
    return prompt
