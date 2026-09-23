"""Persistence helpers for Kilas Order customer requests."""
import json
import math
import uuid

import db

STATUS_LABELS = {
    'SEARCH_REQUESTED': 'Menunggu pencarian',
    'SEARCHING': 'Sedang mencari',
    'RESULTS_READY': 'Sedang diverifikasi Kilas',
    'SELECTED': 'Pilihan dipilih',
    'VERIFYING': 'Sedang diverifikasi',
    'AWAITING_PAYMENT': 'Menunggu pembayaran',
    'PAID': 'Sudah dibayar',
    'PURCHASING': 'Sedang dibeli',
    'PURCHASED': 'Sudah dibeli',
    'SHIPPED': 'Dikirim',
    'DELIVERED': 'Selesai',
    'CANCELLED': 'Dibatalkan',
    'ISSUE': 'Perlu bantuan',
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _decode(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _coordinate(value, minimum, maximum):
    if value in (None, ''):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < minimum or number > maximum:
        return None
    # Nearby search does not need sub-meter precision persisted.
    return round(number, 4)


def _row(row):
    if not row:
        return None
    item = dict(row)
    item['ai_summary'] = _decode(item.pop('ai_summary_json', None), {})
    item['conversation'] = _decode(item.pop('conversation_json', None), [])
    item['is_whatsapp_handoff'] = item['ai_summary'].get('handoff') == 'WHATSAPP'
    item['status_label'] = (
        'Menunggu tim Kilas di WhatsApp'
        if item['is_whatsapp_handoff']
        else STATUS_LABELS.get(item.get('status'), item.get('status') or 'Menunggu')
    )
    return item


def create_request(user_id, draft):
    if type(user_id) is not int or user_id <= 0:
        raise ValueError('invalid_user')
    if not isinstance(draft, dict):
        raise ValueError('invalid_draft')
    text = str(draft.get('request_text') or '').strip()
    state = draft.get('ai_state') or {}
    if len(text) < 3 or not state.get('ready') or draft.get('ai_error'):
        raise ValueError('request_not_ready')

    token = str(draft.get('draft_token') or '').strip()
    if not token:
        token = uuid.uuid4().hex
        draft['draft_token'] = token

    existing = db.query_one(
        'SELECT * FROM kilas_order_requests WHERE user_id=? AND draft_token=? LIMIT 1',
        (user_id, token),
    )
    if existing:
        return _row(existing)

    location_source = str(draft.get('location_source') or '').strip()
    if location_source not in ('gps', 'manual'):
        location_source = ''
    location_label = str(draft.get('location_label') or '').strip()[:120] or None
    lat = _coordinate(draft.get('latitude'), -90, 90)
    lng = _coordinate(draft.get('longitude'), -180, 180)
    summary = state.get('summary') if isinstance(state.get('summary'), dict) else {}
    conversation = draft.get('conversation') if isinstance(draft.get('conversation'), list) else []

    for _ in range(3):
        request_code = 'KOR-' + uuid.uuid4().hex[:8].upper()
        try:
            request_id = db.insert_returning_id(
                'INSERT INTO kilas_order_requests '
                '(request_code,draft_token,user_id,request_text,ai_summary_json,conversation_json,'
                'location_source,location_label,latitude,longitude,status) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (
                    request_code, token, user_id, text[:800], _json(summary), _json(conversation[-6:]),
                    location_source, location_label, lat, lng, 'SEARCH_REQUESTED',
                ),
            )
            return _row(db.query_one(
                'SELECT * FROM kilas_order_requests WHERE id=? AND user_id=?',
                (request_id, user_id),
            ))
        except Exception:
            existing = db.query_one(
                'SELECT * FROM kilas_order_requests WHERE user_id=? AND draft_token=? LIMIT 1',
                (user_id, token),
            )
            if existing:
                return _row(existing)
    raise RuntimeError('order_request_create_failed')


def create_whatsapp_request(user_id, draft):
    """Persist a raw Kilas Order request for asynchronous human follow-up on WhatsApp."""
    if not isinstance(draft, dict):
        raise ValueError('invalid_draft')
    text = str(draft.get('request_text') or '').strip()
    if len(text) < 3:
        raise ValueError('request_not_ready')

    prepared = dict(draft)
    prepared['ai_error'] = False
    prepared['ai_state'] = {
        'ready': True,
        'summary': {
            'item': text[:160],
            'priority': 'Dibantu tim Kilas via WhatsApp',
            'handoff': 'WHATSAPP',
        },
    }
    return create_request(user_id, prepared)


def get_user_request(user_id, request_code):
    if type(user_id) is not int or user_id <= 0:
        return None
    code = str(request_code or '').strip().upper()
    if not code:
        return None
    return _row(db.query_one(
        'SELECT * FROM kilas_order_requests WHERE user_id=? AND request_code=? LIMIT 1',
        (user_id, code),
    ))


def list_user_requests(user_id, limit=30):
    if type(user_id) is not int or user_id <= 0:
        return []
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 30
    return [_row(row) for row in db.query_all(
        'SELECT * FROM kilas_order_requests WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ?',
        (user_id, limit),
    )]


def update_request_status(request_id, status):
    if status not in STATUS_LABELS:
        raise ValueError('invalid_status')
    db.execute(
        "UPDATE kilas_order_requests SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, request_id),
    )


def get_request_by_code(request_code):
    code = str(request_code or '').strip().upper()
    if not code:
        return None
    return _row(db.query_one(
        'SELECT * FROM kilas_order_requests WHERE request_code=? LIMIT 1',
        (code,),
    ))


def list_admin_requests(limit=100):
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 100
    rows = db.query_all(
        "SELECT r.*,u.full_name AS customer_name,u.email AS customer_email "
        "FROM kilas_order_requests r JOIN users u ON u.id=r.user_id "
        "ORDER BY CASE r.status "
        "WHEN 'SEARCH_REQUESTED' THEN 0 WHEN 'SEARCHING' THEN 1 "
        "WHEN 'RESULTS_READY' THEN 2 WHEN 'ISSUE' THEN 3 ELSE 4 END, "
        "r.created_at DESC,r.id DESC LIMIT ?",
        (limit,),
    )
    return [_row(row) for row in rows]


def _candidate_row(row):
    if not row:
        return None
    item = dict(row)
    item['risk_flags'] = _decode(item.pop('risk_flags_json', None), [])
    return item


def replace_candidates(request_id, candidates):
    if type(request_id) is not int or request_id <= 0:
        raise ValueError('invalid_request')
    if not isinstance(candidates, list):
        raise ValueError('invalid_candidates')
    db.execute('DELETE FROM kilas_order_candidates WHERE request_id=?', (request_id,))
    for index, candidate in enumerate(candidates[:20], start=1):
        db.execute(
            'INSERT INTO kilas_order_candidates '
            '(request_id,rank_no,product_name,price_text,currency,condition_text,seller_name,'
            'source_url,source_domain,source_title,availability,trust_score,trust_level,trust_reason,'
            'match_reason,risk_flags_json,evidence_text,status) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                request_id, index, candidate.get('product_name') or 'Produk',
                candidate.get('price_text') or None, candidate.get('currency') or None,
                candidate.get('condition') or None, candidate.get('seller_name') or None,
                candidate['source_url'], candidate['source_domain'],
                candidate.get('source_title') or None, candidate.get('availability') or None,
                int(candidate.get('trust_score') or 0), candidate.get('trust_level') or 'REVIEW',
                candidate.get('trust_reason') or None, candidate.get('match_reason') or None,
                _json(candidate.get('risk_flags') or []), candidate.get('evidence_text') or None,
                'DISCOVERED',
            ),
        )


def list_candidates(request_id):
    return [_candidate_row(row) for row in db.query_all(
        'SELECT * FROM kilas_order_candidates WHERE request_id=? '
        'ORDER BY CASE status WHEN \'VERIFIED\' THEN 0 WHEN \'DISCOVERED\' THEN 1 ELSE 2 END, '
        'rank_no ASC,id ASC',
        (request_id,),
    )]


def update_candidate_status(candidate_id, status):
    if status not in ('VERIFIED','REJECTED','DISCOVERED'):
        raise ValueError('invalid_candidate_status')
    db.execute(
        'UPDATE kilas_order_candidates SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (status, candidate_id),
    )


def get_candidate(request_id, candidate_id):
    return _candidate_row(db.query_one(
        'SELECT * FROM kilas_order_candidates WHERE request_id=? AND id=? LIMIT 1',
        (request_id, candidate_id),
    ))
