"""Pure, bounded link intent selection. Callers supply their own authorized links."""
import re
from urllib.parse import urlsplit

PATTERNS = (
    ('demo', r'\bdemo\b|\b(?:coba|test|trial) kilas brain\b'),
    ('instagram', r'\b(?:ig|instagram)(?:nya)?\b'),
    ('catalog', r'\b(?:katalog|pricelist)(?:nya)?\b'),
    ('app', r'\bclient hub\b|\bapp\b|\blogin\b'),
    ('landing_page', r'\b(?:website|web)(?:nya)?\b|\blanding page\b'),
)


def classify_official_link_intent(text, recent_history=None, role='customer'):
    text = re.sub(r'[^\w\s]', ' ', (text or '').lower()).strip()
    text = re.sub(r'\s+', ' ', text)
    if len(text) > 240:
        return None
    if text in ('link daftar', 'link pembayaran', 'link checkout'):
        return 'app'  # Preserve existing explicit app-link aliases.
    if text in ('daftar layanan', 'layanan kilas works apa aja', 'lihat paket di mana', 'kirim semua harga'):
        return 'catalog'
    # Never consume a purchase or an outbound command addressed to somebody else.
    if re.search(r'\b(?:beli|pesan|order|checkout|bayar|berlangganan|daftar|harga|berapa|brp)\b', text):
        return None
    if role == 'owner' and re.search(r'\b(?:customer|pelanggan|dia)\b|\d{5}|\bke\s+(?!sini\b|saya\b|aku\b|gw\b|gue\b)\w+', text):
        return None
    generic = text in ('ada linknya', 'linknya mana', 'ada link', 'boleh minta linknya', 'minta linknya')
    trial = text in ('bisa dicoba', 'mau lihat botnya', 'gimana cara kerja kilas brain')
    if generic or trial:
        if trial and ('kilas brain' in text or text == 'mau lihat botnya'):
            return 'demo'
        for row in reversed((recent_history or [])[-6:]):
            content = row.get('content', '')
            if not isinstance(content, str):
                continue
            content = content[-600:].lower()
            if trial:
                if re.search(r'content|foto|photo|video|landing page|meta ads', content):
                    return None
                if re.search(r'kilas brain|\bbot\b|ai admin', content):
                    return 'demo'
            else:
                found = [key for key, pattern in PATTERNS if re.search(pattern, content)]
                if len(found) == 1:
                    return found[0]
        return 'landing_page' if generic else None
    if re.search(r'\b(?:portfolio|portofolio|project|proyek)(?:nya)?\b', text) and re.search(r'\b(?:link|url|lihat|contoh)\b', text):
        return 'landing_page'
    if text in ('kilas works bisa apa aja', 'kilas works ada layanan apa aja', 'ada layanan apa aja',
                'mau lihat lihat dulu', 'ada info lengkap', 'profil kilas works ada', 'mau lihat semua layanan'):
        return 'landing_page'
    resources = [key for key, pattern in PATTERNS if re.search(pattern, text)]
    if not resources and re.search(r'\blink kilas\s*works\b', text):
        resources = ['landing_page']
    if len(resources) != 1:
        return None
    # A small request grammar avoids eating analytical questions or service briefs.
    remainder = text
    for _, pattern in PATTERNS:
        remainder = re.sub(pattern, ' ', remainder)
    remainder = re.sub(r'\bkilas\s*works\b|\bkilas brain\b|\bai admin\b', ' ', remainder)
    allowed = {'kita','kalian','resmi','link','url','buat','coba','kirim','kirimin','minta','boleh',
               'ada','apa','mana','di','nya','dong','kak','ya','mau','lihat','kesini','ke','sini','saya','aku','gw','gue'}
    if any(word not in allowed for word in remainder.split()):
        return None
    return resources[0]


def link_reply(intent, links, *, tenant=False, owner=False):
    """No implicit platform defaults, even when a tenant's requested resource is absent."""
    value = (links or {}).get(intent)
    try:
        parsed = urlsplit(value or '')
        valid = parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username and not parsed.password
        valid = valid and not any(c.isspace() or ord(c)<32 for c in value)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        return ('Link tersebut belum tersedia di profil bisnis ini. Silakan hubungi tim bisnis.' if tenant
                else 'Link resmi belum bisa diambil. Coba lagi sebentar ya.')
    labels = {'landing_page':'Website resmi', 'demo':'Demo', 'instagram':'Instagram', 'catalog':'Katalog resmi', 'app':'Client Hub'}
    brand = '' if tenant else (' Kilas Brain' if intent == 'demo' else ' Kilas Works')
    return f'{labels[intent]}{brand}: {value}'
