"""Customer-only, evidence-backed incremental CRM facts. Never receives tenant knowledge."""
import hashlib
import re

VERSION = 2
SCALARS = ('name', 'business_name', 'business_type', 'location', 'budget', 'schedule')
LISTS = ('interests', 'needs')


def canonical(text):
    return ' '.join(re.findall(r'\w+', str(text or '').casefold()))


def trusted_previous(previous):
    return previous if isinstance(previous, dict) and previous.get('_provenance_version') == VERSION else {}


def ground(value, messages, previous=None):
    """Only exact customer quotes may establish facts; absent deltas retain verified facts.

    Each quote is checked against individual customer messages, never a concatenation,
    assistant reply, tenant profile, or a previous unverified insight. Values must appear
    inside their quote. This deliberately favors unknown over an inferred identity.
    """
    previous = trusted_previous(previous)
    result = dict(value)
    evidence = value.get('fact_evidence') or {}
    if not isinstance(evidence, dict):
        evidence = {}
    texts = [m for m in messages if isinstance(m, str) and m.strip()]
    provenance = dict(previous.get('fact_evidence') or {})
    def supported(field, item):
        field_evidence = evidence.get(field)
        if field in LISTS and not isinstance(field_evidence, dict):
            return False
        quote = field_evidence.get(item) if isinstance(field_evidence, dict) else field_evidence
        return (isinstance(quote, str) and quote.strip() and any(quote in text for text in texts)
                and canonical(item) and canonical(item) in canonical(quote))
    for field in SCALARS:
        item = value.get(field)
        if isinstance(item, str) and supported(field, item):
            result[field] = item
            provenance[field] = evidence[field]
        else:
            result[field] = previous.get(field)
    for field in LISTS:
        items = list(previous.get(field) or [])
        quotes = dict(provenance.get(field) or {})
        for item in value.get(field) or []:
            if isinstance(item, str) and supported(field, item):
                if item not in items:
                    items.append(item)
                quotes[item] = evidence[field][item]
        # Explicit quoted corrections replace conflicting older list entries, not all facts.
        replacements = value.get('replaces') or {}
        if isinstance(replacements, dict) and isinstance(replacements.get(field), dict):
            for old, new in replacements[field].items():
                if new in items and supported(field, new):
                    items = [item for item in items if item != old]
                    quotes.pop(old, None)
        result[field] = items[-12:]
        provenance[field] = quotes
    result['fact_evidence'] = provenance
    result['_provenance_version'] = VERSION
    # Narrative is assembled from verified facts below after action evidence is checked.
    return result


def continue_request(insight, previous, text, evidence, *, actionable):
    previous = trusted_previous(previous)
    quote_ok = isinstance(evidence, str) and evidence.strip() and evidence in text
    old_action = previous.get('action')
    old_key = previous.get('_request_key')
    relation = insight.get('request_relation')
    separate = bool(actionable and quote_ok and old_key and (relation == 'NEW' or previous.get('_request_closed')))
    # A separate request must be a new explicit request, not an answer supplying details.
    separate = separate and bool(re.search(
        r'\b(mau|ingin|tolong|buatkan|jadwalkan|pesan|booking|order|need|want|please|book|schedule)\b',
        evidence, re.I)) and (previous.get('_request_closed') or canonical(insight.get('action')) != canonical(old_action))
    if actionable and quote_ok:
        # A factual title cannot add tenant identity/location to the customer's request.
        allowed_text = text + ' ' + ' '.join(str(previous.get(k) or '') for k in ('action', 'needs', 'budget', 'schedule'))
        ignored = {'saya','aku','kami','mau','ingin','tolong','untuk','customer','pelanggan',
                   'jadwalkan','jadwal','booking','book','kirim','kirimkan','buat','buatkan',
                   'bantu','mencari','cari','memesan','pesan','permintaan','lanjutkan','lanjut'}
        extra = set(canonical(insight.get('action')).split()) - set(canonical(allowed_text).split()) - ignored
        if extra or canonical(insight.get('action')) in ('tindakan customer','kebutuhan project','pekerjaan'):
            title = re.sub(r'^(?:saya|aku|kami)\s+(?:(?:mau|ingin|butuh)\s+)?', '', evidence.strip(), flags=re.I)
            insight['action'] = title[:1].upper() + title[1:160]
        insight['_action_evidence'] = evidence
        insight['_request_key'] = (hashlib.sha256((text + '\n' + evidence + ('\n' + old_key if separate else '')).encode()).hexdigest()[:24]
                                   if not old_key or separate else old_key)
        # Payment is a stage of the request; keep its operational title.
        if old_action and not separate and insight.get('job_status') == 'DIKERJAKAN':
            insight['action'] = old_action
    elif old_action:
        insight['action'] = old_action
        insight['_action_evidence'] = previous.get('_action_evidence', '')
        insight['_request_key'] = old_key
        # Do not reapply a stale cancellation/payment transition to another request.
        if insight.get('job_status') not in ('DIKERJAKAN', 'BATAL'):
            insight['job_status'] = None
    else:
        insight['action'] = None
    insight['_separate_request'] = bool(separate)
    if separate:
        # Contact identity survives; request-specific facts must not cross requests.
        for field in ('needs', 'budget', 'schedule'):
            if insight.get('fact_evidence', {}).get(field) == previous.get('fact_evidence', {}).get(field):
                insight[field] = [] if field == 'needs' else None
    parts = []
    for item in [insight.get('action'), *(insight.get('needs') or []),
                 insight.get('budget'), insight.get('schedule')]:
        if item and item.casefold() not in ' · '.join(parts).casefold():
            parts.append(item)
    if not parts:
        parts = list(insight.get('interests') or [])
    insight['summary'] = ' · '.join(parts)[:900] or 'Kontak masih mencari informasi.'
    return insight
