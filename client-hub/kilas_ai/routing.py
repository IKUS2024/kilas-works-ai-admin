"""Small deterministic intent routing for the customer-facing composer."""
import re


def mode_for(content, attachments=()):
    text = content.lower()
    difficult = (
        r"\b(?:debug|refactor|optimasi|architecture|arsitektur|implementasi|analisis mendalam|"
        r"rencana strategis|multi.?step|langkah demi langkah yang kompleks)\b",
        r"\b(?:bandingkan|compare|perbandingan)\b.*\b(?:dua|2|beberapa|multiple)\b.*\b(?:dokumen|file|laporan)\b",
        r"\b(?:mending|lebih baik|sebaiknya|menurut (?:lu|lo|kamu|anda)|saran|rekomendasi)\b"
        r".{0,140}\b(?:atau|apa|vs|pilih|modal|budget|hari|bulan|usaha|kerja|beli|trip|liburan)\b",
        r"\b(?:strategi|rencana|analisis|pertimbangkan|risiko)\b.{0,120}"
        r"\b(?:bisnis|usaha|karier|karir|keuangan|marketing|proyek|project)\b",
    )
    documents = sum(bool(item.get("extracted_text")) for item in attachments)
    if documents >= 2 and re.search(r"\b(?:bandingkan|compare|analisis|sintesis)\b", text):
        return "SMART"
    return "SMART" if any(re.search(pattern, text) for pattern in difficult) else "FAST"


def _normalize(content):
    text = " ".join((content or "").lower().split())
    text = re.sub(r"\b(?:buatkan|buatin|bikinkan|bikinin|bikin|bkin)\b", "buat", text)
    text = re.sub(r"\b(?:jadiin|jadikan)\b", "ubah", text)
    text = re.sub(r"\b(?:gambarinn|gambarin)\b", "buat gambar", text)
    text = re.sub(r"\b(?:gambarkan|gambarin|gamabar|gmbar|gmbaar|gambarr)\b", "gambar", text)
    text = re.sub(r"\bgambarnya\b", "gambar", text)
    text = re.sub(r"\bpdf(?:-?nya)\b", "pdf", text)
    return text


def _discussion(text):
    if re.search(r'\b(?:buat|kasih|beri|susun|create|give|write)\s+(?:ide|konsep|concept|idea)\b', text) and not re.search(r'\b(?:gambarnya|visualnya|jadi gambar|buat gambar)\b', text):
        return True
    if re.match(r'^(?:menurut|kasih ide|beri ide|jelaskan|explain)\b', text):
        return True
    return bool(re.search(
        r"^(?:apa (?:itu|arti)|what is|jelaskan cara|bagaimana cara|cara |how (?:to|do)|"
        r"kenapa|mengapa|why |model |perbedaan |berapa harga |"
        r"tolong (?:jelaskan|terangkan) cara)\b", text))


def _edit_intent(text, has_image):
    action = r"(?:edit|ubah|ganti|hapus|hilangkan|remove|change|crop|retouch|rapihin|rapikan|terangkan|cerahkan)"
    if has_image:
        return bool(re.search(r"\b" + action + r"\b|\bbackground\s+(?:putih|polos|transparan)\b|\b(?:lebih\s+(?:terang|premium|simple|simpel)|warna orange|jadi\s+kartun)\b", text))
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
             has_previous_content=False, previous_answer=""):
    text = _normalize(content)
    # A general capability question is discussion, never authorization to execute.
    if re.fullmatch(r"(?:kamu |lu |lo |anda )?bisa (?:buat|bikin|generate|membuat) (?:pdf|gambar(?: logo)?|logo|file|video)(?: (?:ga|gak|nggak|tidak|ngga))?[?!.]*", text):
        return "CHAT"
    if re.fullmatch(r"can you (?:make|create|generate) (?:a |an )?(?:pdf|image|logo|file|video)[?!.]*", text):
        return "CHAT"
    if re.search(r"\b(?:benerin typo|perbaiki typo|ubah kalimat|tulis ulang|rewrite|translate|terjemahkan)\b", text):
        return "CHAT"
    if work_requested(text):
        return "WORK"
    if explicit_code(content):
        return "CHAT"
    if search:
        return "WEB"
    if fresh_information(text):
        return "WEB"
    if _discussion(text):
        return "CHAT"
    if re.search(r'\b(?:buat|create|export|ekspor|ubah)\b',text) and re.search(r'\b(?:docx|xlsx|pptx|file word|file excel)\b',text):
        return "FILE"
    has_image = any(item.get("mime_type", "").startswith("image/") for item in attachments)
    if not has_image and not previous_answer and re.fullmatch(r'(?:buat|tolong buat|buat dong|ubah ini)[.!?]*',text):
        return "CLARIFY"
    if has_image and not (pdf_request or _pdf_intent(text, has_previous_content)) and _edit_intent(text, True):
        return "IMAGE_EDIT"
    if pdf_request or _pdf_intent(text, has_previous_content):
        return "PDF"
    if _edit_intent(text, False):
        return "IMAGE_EDIT"
    if re.search(r"\b(?:kode|code)\s+(?:svg|vector)|\bsvg\s+(?:code|kode)\b", text):
        return "CHAT"
    visual = r"(?:gambar|foto|ilustrasi|poster|banner|image|picture|photo|visual|logo|logotype|wordmark|brand.?mark|ikon|icon|emblem|maskot|mascot)"
    create = r"(?:buat|create|generate|draw|lukis|gambarkan)"
    if re.search(r"\b" + create + r"\b.{0,75}\b" + visual + r"\b|\b(?:draw|lukis)\s+\S+", text):
        return "IMAGE_GENERATE"
    if not has_image and re.match(r"^gambar\s+(?!ini\b|itu\b|apa\b|yang\b|tersebut\b)\S+", text):
        return "IMAGE_GENERATE"
    if previous_answer and re.search(r'\b(?:logo|poster|banner|ilustrasi|gambar|visual)\b',previous_answer,re.I) and re.search(r'\b(?:buat|gambar|lebih premium|lebih simple|warna orange)\b',text) and len(text)<120:
        return "IMAGE_GENERATE"
    if not previous_answer and re.fullmatch(r'(?:buat|tolong buat|buat dong|ubah ini)[.!?]*',text):
        return "CLARIFY"
    return "CHAT"


def image_prompt(content, previous_answer=""):
    """Carry a nearby visual concept into a short image-creation follow-up."""
    if (previous_answer and len(content) <= 120 and
            re.search(r"\b(?:gambarnya|visualnya|sekarang|tadi|dari konsep|konsep itu|dari ide)\b", content.lower()) and
            re.search(r"\b(?:logo|wordmark|poster|banner|gambar|ilustrasi|desain|visual|image|foto)\b", previous_answer.lower())):
        return "Konsep sebelumnya:\n" + previous_answer[:1800] + "\n\nBuat gambar sesuai permintaan terbaru: " + content
    return content


def enhance_image_prompt(prompt, requested_action_text=None):
    """Keep the user's wording and make a requested visible action unambiguous."""
    text = (requested_action_text or prompt).lower()
    if re.search(r"\b(?:nyanyi|menyanyi|bernyanyi|singing|sing)\b", text):
        return prompt + "\nAksi utama harus tampak jelas: subjek sedang bernyanyi, mulut terbuka saat menyanyi, bukan hanya berpose. Pertahankan subjek, gaya, dan detail yang diminta."
    if re.search(r"\b(?:logo|logotype|wordmark|brand.?mark|ikon|icon|emblem)\b", text):
        return prompt + "\nHasilkan gambar logo final, bukan kode SVG/HTML dan bukan penjelasan. Buat desain original yang bersih, sederhana, profesional, mudah dikenali, dan tetap jelas pada ukuran kecil. Jika nama merek disebut, gunakan nama itu sebagai identitas visual utama dan jangan menambahkan teks atau slogan lain yang tidak diminta. Jangan menyalin logo merek lain, menambahkan watermark atau simbol merek dagang palsu. Jangan gunakan mockup kecuali diminta."
    if re.search(r"\b(?:menari|berlari|memasak|melukis|membaca|menulis|dancing|running|cooking|painting|reading|writing)\b", text):
        return prompt + "\nTampilkan aksi utama yang diminta dengan jelas, bukan pose diam. Pertahankan subjek, gaya, dan detail yang diminta."
    return prompt


def explicit_code(text):
    return bool(re.search(r'(?i)\b(?:kode|code|source|markup|html|css|canvas|ascii|base64)\b|\b(?:svg|vector)\s+(?:code|kode|markup)\b',text))


def work_requested(text):
    if _discussion(text) or re.search(r'\b(?:email|gmail|whatsapp|ingatkan|remind)\b',text):
        return False
    substantial = re.search(r'\b(?:riset|research)\b.{0,75}(?:\b\d{2,}\s+(?:kompetitor|competitors)\b|\bdan buat laporan\b)',text)
    return bool(substantial or (re.search(r'\b(?:pantau|monitor|watch)\b|\b(?:sampai|until)\b.{0,35}\b(?:selesai|berubah|pass|complete)\b|\b(?:setiap|tiap|every)\b.{0,25}\b(?:jam|hari|hour|day)\b',text) and re.search(r'\b(?:riset|research|pantau|monitor|watch|perbaiki|fix|kerjakan|buat)\b',text)))


def fresh_information(text):
    # 'Cari kemungkinan salahnya' asks for diagnosis, not an internet search.
    if re.search(r"\bcari kemungkinan\b", text) and not re.search(r"\b(?:web|internet|terbaru|terkini|hari ini)\b", text):
        return False
    # Current software versions need a source just like current prices/news.
    # Keep creative follow-ups such as 'buat versi lain' on their existing path.
    if (not re.search(r'\b(?:buat|bikin|bikinin|buatin|ubah|create|make)\s+(?:versi|version)\b', text)
            and re.search(r'\b(?:terbaru|terkini|sekarang|saat ini|latest|current|today)\b', text)
            and re.search(r'\b(?:(?:versi|version)\s+(?:[a-z0-9.+-]+\s+){0,3}(?:stabil|stable|terbaru|latest)|(?:rilis|release)\s+(?:terbaru|latest)|(?:latest|current)\s+(?:stable\s+)?version)\b', text)):
        return True
    if re.match(r'^(?:apa itu|what is|jelaskan cara|how to)\b',text):
        return False
    return bool(re.search(r'\b(?:cari|carikan|search|cek internet|cek web|berita terbaru|berita terkini|latest news)\b',text) or
                (re.search(r'\b(?:hari ini|terbaru|sekarang|terkini|latest|today|current)\b',text) and re.search(r'\b(?:harga|berita|news|ceo|presiden|jadwal|kurs|cuaca|price|schedule|weather)\b',text)))


def visual_result_requested(text):
    return not explicit_code(text) and not _discussion(_normalize(text)) and bool(re.search(r'(?i)\b(?:logo|wordmark|poster|banner|gambar|ilustrasi|icon|maskot|visual|pdf|file)\b',text))


def response_safe(request, answer):
    """Last-resort protection: buffered visual/file prose cannot masquerade as an artifact."""
    if not visual_result_requested(request):
        return True
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    ascii_art = len(lines)>=3 and sum(bool(re.fullmatch(r'[+|/\\_#* =.()\-]{2,}',line)) for line in lines)>len(lines)/2
    encoded = bool(re.fullmatch(r'[A-Za-z0-9+/=\s]{128,}',answer.strip())) and not bool(re.search(r'\s',answer.strip()))
    raw_css = bool(re.match(r'\s*(?:[.#][\w-]+|body|svg|canvas)\s*\{',answer))
    return not (ascii_art or encoded or raw_css or bool(re.search(r'(?i)<(?:svg|html|style|script|canvas|\?xml)\b|data:image/[^;]+;base64,|```(?:svg|html|xml|css|ascii|javascript)\b|\b(?:document\.createElement|canvas\.getContext)\b',answer)))
