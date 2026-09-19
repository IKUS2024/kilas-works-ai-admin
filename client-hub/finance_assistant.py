"""Pure workflow proposals only. No database, provider, file bytes, tokens or writes."""
import re

WORKFLOWS = frozenset(('READ_ONLY_ANALYSIS', 'TEXT_OPERATOR', 'RECEIPT',
                       'BANK_STATEMENT', 'HANDWRITTEN_NOTE', 'RECURRING_DRAFT', 'NEEDS_CLARIFICATION', 'UNSUPPORTED'))
MODES = {'auto': None, 'ask': 'READ_ONLY_ANALYSIS', 'record': 'TEXT_OPERATOR',
         'receipt': 'RECEIPT', 'bank': 'BANK_STATEMENT',
         'notes': 'HANDWRITTEN_NOTE', 'recurring': 'RECURRING_DRAFT'}
EXTENSIONS = frozenset(('csv', 'pdf', 'jpg', 'jpeg', 'png', 'webp'))


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'text', 'mode', 'files'}:
        raise ValueError('invalid_request')
    text, mode, files = payload['text'], payload['mode'], payload['files']
    if (not isinstance(text, str) or len(text) > 2000 or '\x00' in text
            or not isinstance(mode, str) or mode not in MODES
            or not isinstance(files, list) or len(files) > 10):
        raise ValueError('invalid_request')
    for item in files:
        if (not isinstance(item, dict) or set(item) != {'name'}
                or not isinstance(item['name'], str) or not 1 <= len(item['name']) <= 255
                or any(ord(c) < 32 for c in item['name'])):
            raise ValueError('invalid_metadata')
    return text.strip(), mode, files


def classify(text, mode, files):
    # Metadata is a routing hint only. The selected engine validates actual bytes later.
    extensions = [item['name'].rsplit('.', 1)[-1].lower() for item in files]
    if any(ext not in EXTENSIONS for ext in extensions):
        return 'UNSUPPORTED'
    if MODES[mode]:
        return MODES[mode]
    words = text.casefold()
    has = lambda pattern: bool(re.search(pattern, words))
    if files:
        if extensions == ['csv']:
            return 'BANK_STATEMENT'
        if has(r'\b(tulisan tangan|catatan|handwritten|notes?)\b'):
            return 'HANDWRITTEN_NOTE'
        bank = has(r'\b(mutasi|rekening|bank|statement|rekonsiliasi)\b')
        receipt = has(r'\b(struk|receipt|pengeluaran|expense)\b')
        if bank and not receipt:
            return 'BANK_STATEMENT'
        if receipt and not bank:
            return 'RECEIPT'
        return 'NEEDS_CLARIFICATION'
    if has(r'\b(hapus|delete|transfer|kirim uang|bayarkan|ubah transaksi)\b'):
        return 'UNSUPPORTED'
    recording = has(r'\b(catat|catatkan|rekam|record|beli|bayar|terima|pemasukan|penjualan)\b|\b(siapkan|buat) draft\b')
    question = has(r'\b(apa|berapa|bagaimana|kenapa|mengapa|laporan|analisis|ringkas|bandingkan|summary|report)\b|\?')
    recurring = has(r'\b(rutin|berulang|mingguan|bulanan|recurring|tiap minggu|tiap bulan|setiap minggu|setiap bulan)\b')
    if recurring and not question:
        return 'RECURRING_DRAFT'
    if recording and question:
        return 'NEEDS_CLARIFICATION'
    if recording:
        return 'TEXT_OPERATOR'
    if question:
        return 'READ_ONLY_ANALYSIS'
    return 'NEEDS_CLARIFICATION'


def propose(payload):
    text, mode, files = validate(payload)
    try:
        workflow = classify(text, mode, files)
        if workflow not in WORKFLOWS:
            workflow = 'NEEDS_CLARIFICATION'
    except Exception:
        workflow = 'NEEDS_CLARIFICATION'
    # No financial fields or inferred identifiers are returned by the router.
    return {'workflow': workflow}


def operator_action(text):
    """Optional action suggestion; account/category/invoice choices remain blank."""
    words = text.casefold()
    if re.search(r'\binvoice\b', words):
        return 'record_invoice_payment'
    expense = bool(re.search(r'\b(pengeluaran|expense|bensin|beli|biaya|ongkos|bayar|sewa|makan|belanja|listrik)\b', words))
    income = bool(re.search(r'\b(pemasukan|income|pendapatan|penjualan|terima)\b', words))
    if expense == income:
        return ''
    return 'create_expense' if expense else 'create_income'
