"""Read intent takes precedence over stale conversational action/target state."""
import re

READ_INTENTS = {'GLOBAL_ANALYZE', 'LOOKUP', 'QUERY'}

def classify(text):
    s = (text or '').strip().lower()
    # A send needs an imperative, not a mention of sending inside a question.
    command = re.sub(r'^(?:tolong|coba|please|bantu)\s+', '', s)
    if re.match(r'^(?:kirim|bilang(?:in)?|sampaikan|kasih tau|beritahu|bales|balas|jawab|terusin|teruskan|tanyain|ingetin)\b', command):
        return 'SEND'
    if re.match(r'^(?:dia|nya|itu|customer itu)\b.*\b(?:coba|tolong)\s+(?:tanyain|ingetin|kirim|bilangin|sampaikan)\s*$', s):
        return 'SEND'
    if re.match(r'^follow[ -]?up\b', command):
        return 'ACTION'
    if re.search(r'\b(siapa|customer mana|pelanggan mana)\b', s) and re.search(r'paling|minat|potensi|potensial|closing|semua|semuanya', s):
        return 'GLOBAL_ANALYZE'
    if re.search(r'\bterakhir\b.*\b(chat|ngomong|bilang|pesan)\b|\b(chat|ngomong|bilang|pesan)\b.*\bterakhir\b', s):
        return 'LOOKUP'
    if re.search(r'\b(siapa|berapa|mana|status|gimana|bagaimana)\b|\?', s):
        return 'QUERY'
    return None

def needs_stronger_reasoning(text):
    # Simple ranking is still fast. Only explicit multi-factor analysis escalates.
    return classify(text) == 'GLOBAL_ANALYZE' and bool(re.search(
        r'risiko|trade.?off|skenario|strategi|bandingkan.*(?:budget|anggaran|deadline)', text, re.I))
