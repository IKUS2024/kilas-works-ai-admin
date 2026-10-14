"""Chat lookup evidence and deterministic conversion; no transport or quota policy."""
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

UNVERIFIED = ('Informasi terbaru belum dapat diperiksa dan belum terverifikasi. '
              'Saya tidak akan menebak kurs, harga, atau fakta terbaru.')
NO_SEARCH = ('Saya tidak melakukan pencarian web sesuai permintaanmu. '
             'Informasi terkini belum terverifikasi. Berikan data atau kurs yang ingin dipakai '
             'agar saya dapat membantu tanpa menebak.')


def search_failure_message(error):
    code = getattr(error, 'code', 'search_internal_error')
    if code == 'provider_timeout':
        detail = 'Pencarian melewati batas waktu. Coba lagi sebentar.'
    elif code == 'provider_rate_limited':
        detail = 'Layanan pencarian sedang membatasi permintaan. Coba lagi sebentar.'
    elif code in {'provider_http_error','provider_connection','provider_invalid_response'}:
        detail = 'Layanan pencarian sedang bermasalah. Coba lagi sebentar.'
    elif code in {'configuration_missing','configuration_rejected'}:
        detail = 'Layanan pencarian belum tersedia karena konfigurasi layanan.'
    elif code == 'provider_request_rejected':
        detail = 'Layanan pencarian belum dapat memproses permintaan ini.'
    elif code == 'currency_query_ambiguous':
        detail = 'Permintaan pencarian belum dapat diproses. Perjelas pertanyaannya.'
    elif code in {'search_incomplete','search_not_completed','search_empty_answer'}:
        detail = 'Layanan pencarian belum mengembalikan hasil yang selesai.'
    else:
        detail = 'Pencarian belum menghasilkan bukti bersumber yang cukup untuk pertanyaan ini.'
    return detail + ' ' + UNVERIFIED


ALIASES = {'rmb': 'CNY', 'cny': 'CNY', 'yuan': 'CNY', 'renminbi': 'CNY',
           'idr': 'IDR', 'rupiah': 'IDR', 'usd': 'USD', 'dolar': 'USD', 'dollar': 'USD',
           'eur': 'EUR', 'euro': 'EUR', 'gbp': 'GBP', 'jpy': 'JPY', 'yen': 'JPY',
           'sgd': 'SGD', 'myr': 'MYR', 'ringgit': 'MYR', 'aud': 'AUD', 'hkd': 'HKD'}
CURRENCIES = r'(?<![a-z])(?:' + '|'.join(ALIASES) + r')(?![a-z])'


def _currency_text(text):
    names = '|'.join(ALIASES)
    return re.sub(r'(?i)(\d(?:[.,]\d+)*)\s*(' + names + r')(?:to|ke)(' + names + r')(?![a-z])',
                  r'\1 \2 to \3', text)


def conversion_requested(text):
    text = _currency_text(text)
    codes = {ALIASES[m.group()] for m in re.finditer(CURRENCIES, text.lower())}
    return len(codes) >= 2 and bool(re.search(r'(?i)\d|\b(?:kurs|konversi|convert|berapa|to|ke)\b', text))


def supplied_rate(text):
    """An explicitly supplied hypothetical rate is arithmetic, not a live quote."""
    spec = conversion(text)
    if not spec or re.search(r'\b(?:sekarang|terbaru|terkini|hari ini|saat ini|today|current|latest)\b', text):
        return False
    if not re.search(r'\b(?:gunakan|pakai|dengan|use|assuming)\s+(?:kurs|rate|exchange rate)\b', text):
        return False
    match = re.search(r'\b1\s*(' + '|'.join(ALIASES) + r')\s*=\s*\d+(?:[.,]\d+)*\s*('
                      + '|'.join(ALIASES) + r')\b', text)
    return bool(match and {ALIASES[match[1]], ALIASES[match[2]]} == {spec['base'], spec['quote']})


def conversion(text):
    """Only parse an unambiguous amount followed by source and target currencies."""
    text = _currency_text(text)
    match = re.search(r'(?i)(?<![a-z0-9.,+\-−])(\d+(?:[.,]\d+)*)\s*(' + '|'.join(ALIASES)
                      + r')\b.{0,80}?(' + '|'.join(ALIASES) + r')\b', text)
    prefix = False
    if not match:
        match = re.search(r'(?i)\b(' + '|'.join(ALIASES) + r')\s*(\d+(?:[.,]\d+)*)\b.{0,80}?('
                          + '|'.join(ALIASES) + r')\b', text)
        prefix = True
    if not match:
        return None
    raw, base, quote = match.groups() if not prefix else (match[2], match[1], match[3])
    base, quote = ALIASES[base.lower()], ALIASES[quote.lower()]
    if base == quote:
        return None
    if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+', raw):
        raw = re.sub(r'[.,]', '', raw)
    elif re.fullmatch(r'\d+(?:[.,]\d{1,2})?', raw):
        raw = raw.replace(',', '.')
    else:
        return None
    return {'amount': Decimal(raw), 'base': base, 'quote': quote}


def conversion_instructions(spec):
    return (' For this currency conversion, verify a current published rate through web search. '
            'Return ONLY a JSON object with base, quote, rate, as_of, source_url. '
            f'base must be {spec["base"]}, quote must be {spec["quote"]}; '
            'rate is a decimal string for ONE base unit in quote units, taken from the cited source, '
            'never a remembered or assumed rate. as_of must be the source rate date/time in ISO 8601 '
            '(include timezone when a time is available). source_url must match a returned URL citation. '
            'If the source does not establish the rate and its date/time, return null. '
            'Do not calculate the converted amount; the application will calculate it.')


def conversion_followup(text, previous_request):
    """Carry the same pair only for an explicit, unambiguous numeric follow-up."""
    previous = conversion(previous_request)
    match = re.fullmatch(r'(?i)(?:kalau|untuk|what about|how about|and)\s+(\d+(?:[.,]\d+)*)\s*[?!.]*', text.strip())
    if not previous or not match:
        return None
    return conversion(f'{match[1]} {previous["base"]} ke {previous["quote"]}')


def conversion_answer(spec, raw, citations, normalize_url, now=None):
    """Require published-rate metadata and cited provenance before any arithmetic."""
    now = now or datetime.now(timezone.utc)
    # Accept one complete JSON code block; no prose scraping or invented defaults.
    wrapped = re.fullmatch(r'\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*', raw, flags=re.I)
    data = json.loads(wrapped[1] if wrapped else raw)
    if not isinstance(data, dict) or (data.get('base'), data.get('quote')) != (spec['base'], spec['quote']):
        raise ValueError('currency_pair_missing')
    raw_rate = str(data.get('rate', ''))
    if not re.fullmatch(r'\d{1,13}(?:\.\d{1,12})?', raw_rate):
        raise ValueError('rate_invalid')
    rate = Decimal(raw_rate)
    if not rate.is_finite() or not 0 < rate <= Decimal('1e12'):
        raise ValueError('rate_invalid')
    as_of = str(data.get('as_of', ''))
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2}))?', as_of):
        raise ValueError('rate_time_missing')
    dated = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    if dated.tzinfo is None:
        dated = dated.replace(tzinfo=timezone.utc)
    if dated > now + timedelta(minutes=5) or now - dated > timedelta(days=7):
        raise ValueError('rate_not_current')
    source = normalize_url(data.get('source_url'))
    if not source or source not in {item['url'] for item in citations}:
        raise ValueError('rate_source_missing')
    value = (spec['amount'] * rate).quantize(Decimal('.01'))
    def number(n, digits=2):
        return f'{n:,.{digits}f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    rate_digits = max(2, -rate.as_tuple().exponent)
    total = 'Rp' + number(value) if spec['quote'] == 'IDR' else number(value) + ' ' + spec['quote']
    return (f'{spec["amount"]:f} {spec["base"]} ≈ {total}.\n\n'
            f'Kurs: 1 {spec["base"]} = {number(rate, rate_digits)} {spec["quote"]}. '
            f'Waktu sumber: {as_of}. [Sumber kurs]({source}). '
            f'Diperiksa: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}. '
            'Nilai perkiraan; kurs transaksi dan biaya penukaran dapat berbeda.')
