"""Deterministic operational Jobs. No model, Finance, legacy Order or channel sends.

Callers authenticate/authorize the actor and tenant before using this boundary.
The service independently validates tenant references, payload, retries and versions.
All writes use a short transaction and tenant-row lock (SQLite: BEGIN IMMEDIATE).
"""
import hashlib
import json
import math
import os
import re
import time
import uuid

import db
from kilas_core.customers import transaction

STATUS_LABELS = {
    'NEW': 'Baru', 'NEEDS_INFORMATION': 'Butuh informasi',
    'READY_FOR_QUOTE': 'Siap ditawarkan', 'QUOTED': 'Sudah ditawarkan',
    'APPROVED': 'Disetujui', 'IN_PROGRESS': 'Dikerjakan',
    'COMPLETED': 'Selesai', 'CANCELLED': 'Dibatalkan',
}
TRANSITIONS = {
    'NEW': ('NEEDS_INFORMATION', 'READY_FOR_QUOTE', 'CANCELLED'),
    'NEEDS_INFORMATION': ('READY_FOR_QUOTE', 'CANCELLED'),
    'READY_FOR_QUOTE': ('QUOTED', 'CANCELLED'),
    'QUOTED': ('APPROVED', 'CANCELLED'),
    'APPROVED': ('IN_PROGRESS', 'CANCELLED'),
    'IN_PROGRESS': ('COMPLETED', 'CANCELLED'),
    'COMPLETED': (), 'CANCELLED': (),
}
KINDS = {'ORDER': 'Pesanan', 'BOOKING': 'Booking', 'SHIPMENT': 'Pengiriman',
         'PROJECT': 'Project', 'SERVICE': 'Service', 'GENERIC': 'Pekerjaan'}
# Explicit future-compatible operational keys only. No arbitrary metadata/secrets.
FIELD_LABELS = {'details': 'Rincian', 'quantity': 'Jumlah', 'unit': 'Satuan',
                'origin': 'Asal', 'destination': 'Tujuan',
                'scheduled_at': 'Jadwal', 'reference': 'Referensi',
                'missing_information': 'Informasi yang masih dibutuhkan'}


class JobError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def enabled():
    return os.environ.get('KILAS_JOBS_V2_ENABLED', '').strip().lower() == 'true'


def presentation(category):
    words = set(re.findall(r'[a-z]+', str(category or '').lower()))
    groups = (
        ('ORDER', {'restaurant', 'restoran', 'retail', 'toko', 'warung', 'cafe', 'kafe', 'kuliner', 'food'}),
        ('BOOKING', {'salon', 'appointment', 'spa', 'barbershop', 'klinik'}),
        ('SHIPMENT', {'logistics', 'logistik', 'freight', 'ekspedisi', 'pengiriman'}),
        ('PROJECT', {'agency', 'agensi', 'videography', 'videografi', 'fotografi'}),
        ('SERVICE', {'workshop', 'repair', 'bengkel', 'servis'}),
    )
    kind = next((kind for kind, aliases in groups if words & aliases), 'GENERIC')
    # Indonesian noun labels do not require English plural suffixes.
    return {'kind': kind, 'singular': KINDS[kind], 'plural': KINDS[kind]}


def _positive(value):
    if type(value) is not int or value <= 0:
        raise JobError('invalid_scope')
    return value


def _text(value, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise JobError('invalid_text')
    value = value.strip()
    if required and not value:
        raise JobError('invalid_text')
    return value


def validate_fields(fields):
    if not isinstance(fields, dict) or set(fields) - FIELD_LABELS.keys():
        raise JobError('invalid_fields')
    clean = {}
    for key, value in fields.items():
        if key == 'quantity':
            if type(value) not in (int,float) or not 0 < value <= 1_000_000_000 or not math.isfinite(value):
                raise JobError('invalid_fields')
            clean[key] = value
        else:
            clean[key] = _text(value, 1000)
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > 8192:
        raise JobError('fields_too_large')
    return encoded


def _row(row):
    if not row:
        raise JobError('not_found', 404)
    item = dict(row)
    item['fields'] = json.loads(item.pop('fields_json'))
    item['status_label'] = STATUS_LABELS[item['status']]
    item['label'] = KINDS[item['kind']]
    return item


def _get(tx, bid, jid):
    return tx.one('SELECT * FROM kw_core_jobs WHERE business_id=? AND id=?', (bid, jid))


def _references(tx, bid, customer_id, conversation_id):
    if not tx.one('SELECT id FROM kw_core_customers WHERE business_id=? AND id=?', (bid, customer_id)):
        raise JobError('not_found', 404)
    if conversation_id is not None and not tx.one(
            'SELECT customer_id FROM kw_web_customer_links WHERE business_id=? AND conversation_id=? AND customer_id=?',
            (bid, conversation_id, customer_id)):
        raise JobError('not_found', 404)


def _lock(tx, bid):
    suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
    if not tx.one('SELECT id FROM businesses WHERE id=?' + suffix, (bid,)):
        raise JobError('not_found', 404)


def _operation(bid, actor_id, operation_key, payload):
    _positive(bid)
    _positive(actor_id)
    if not isinstance(operation_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', operation_key):
        raise JobError('invalid_operation')
    data = json.dumps([actor_id, payload], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode()).hexdigest()


def _replay(tx, bid, operation_key, request_hash):
    op = tx.one('SELECT * FROM kw_core_job_operations WHERE business_id=? AND operation_key=?', (bid, operation_key))
    if not op:
        return None
    if op['request_hash'] != request_hash:
        raise JobError('operation_conflict', 409)
    # Return authoritative current state, never rewind a newer edit on replay.
    return _row(_get(tx, bid, op['job_id']))


def _record(tx, bid, jid, actor_id, operation_key, request_hash, version, action, now):
    tx.execute('INSERT INTO kw_core_job_operations(business_id,operation_key,request_hash,job_id,result_version,created_at) '
               'VALUES (?,?,?,?,?,?)', (bid, operation_key, request_hash, jid, version, now))
    tx.execute('INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)',
               (actor_id, bid, action, json.dumps({'job_id': jid, 'version': version})))


def create_job(business_id, customer_id, *, title, actor_id, operation_key,
               conversation_id=None, kind='GENERIC', summary='', fields=None):
    title = _text(title, 160, True)
    summary = _text(summary, 2000)
    encoded = validate_fields({} if fields is None else fields)
    if not isinstance(kind,str) or kind not in KINDS:
        raise JobError('invalid_kind')
    customer_id = _text(customer_id, 128, True)
    if conversation_id is not None:
        conversation_id = _text(conversation_id, 128, True)
    digest = _operation(business_id, actor_id, operation_key,
                        ['create', customer_id, conversation_id, kind, title, summary, encoded])
    with transaction() as tx:
        _lock(tx, business_id)
        _references(tx, business_id, customer_id, conversation_id)
        replay = _replay(tx, business_id, operation_key, digest)
        if replay:
            return replay
        jid, now = uuid.uuid4().hex, int(time.time())
        tx.execute('INSERT INTO kw_core_jobs(business_id,id,customer_id,conversation_id,kind,title,summary,fields_json,created_at,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (business_id,jid,customer_id,conversation_id,kind,title,summary,encoded,now,now))
        _record(tx,business_id,jid,actor_id,operation_key,digest,1,'JOB_CREATED',now)
        return _row(_get(tx,business_id,jid))


def update_job(business_id, job_id, *, expected_version, actor_id, operation_key,
               title=None, summary=None, fields=None, status=None):
    _positive(expected_version)
    if title is not None:
        title = _text(title,160,True)
    if summary is not None:
        summary = _text(summary,2000)
    encoded = validate_fields(fields) if fields is not None else None
    if status is not None and (not isinstance(status,str) or status not in STATUS_LABELS):
        raise JobError('invalid_status')
    digest = _operation(business_id,actor_id,operation_key,
                        ['update',job_id,expected_version,title,summary,encoded,status])
    with transaction() as tx:
        _lock(tx,business_id)
        current = _get(tx,business_id,job_id)
        _row(current)  # Fail closed before replay lookup for a forged job.
        _references(tx,business_id,current['customer_id'],current['conversation_id'])
        replay = _replay(tx,business_id,operation_key,digest)
        if replay:
            return replay
        if current['version'] != expected_version:
            raise JobError('stale_version',409)
        target = current['status'] if status is None else status
        if target != current['status'] and target not in TRANSITIONS[current['status']]:
            raise JobError('invalid_transition',409)
        now = int(time.time())
        result = tx.one('UPDATE kw_core_jobs SET title=?,summary=?,fields_json=?,status=?,version=version+1,updated_at=? '
                        'WHERE business_id=? AND id=? AND version=? RETURNING *',
                        (current['title'] if title is None else title,
                         current['summary'] if summary is None else summary,
                         current['fields_json'] if encoded is None else encoded,
                         target,now,business_id,job_id,expected_version))
        if not result:
            raise JobError('stale_version',409)
        _record(tx,business_id,job_id,actor_id,operation_key,digest,result['version'],'JOB_UPDATED',now)
        return _row(result)


def transition_job(business_id, job_id, status, **kwargs):
    return update_job(business_id,job_id,status=status,**kwargs)


def get_job(business_id, job_id):
    _positive(business_id)
    with transaction() as tx:
        return _row(_get(tx,business_id,job_id))


def list_jobs(business_id, *, search='', status='', page=1, customer_id=None, conversation_id=None):
    _positive(business_id)
    if status and status not in STATUS_LABELS:
        raise JobError('invalid_status')
    search = _text(search,120)
    where, args = 'business_id=?', [business_id]
    for column, value in (('status',status),('customer_id',customer_id),('conversation_id',conversation_id)):
        if value:
            where += ' AND ' + column + '=?'
            args.append(value)
    if search:
        where += ' AND (LOWER(title) LIKE LOWER(?) OR LOWER(summary) LIKE LOWER(?))'
        args += ['%'+search+'%']*2
    with transaction() as tx:
        total = tx.one('SELECT COUNT(*) AS n FROM kw_core_jobs WHERE '+where,tuple(args))['n']
        pages = max(1,(total+9)//10)
        try:
            page = min(max(1,int(page)),pages)
        except (TypeError,ValueError):
            raise JobError('invalid_page')
        rows = tx.execute('SELECT * FROM kw_core_jobs WHERE '+where+' ORDER BY updated_at DESC,id LIMIT 10 OFFSET ?',
                          tuple(args+[(page-1)*10]))
        return [_row(row) for row in rows],total,page,pages


def jobs_for_customer(business_id, customer_id):
    with transaction() as tx:
        _references(tx,business_id,customer_id,None)
    return list_jobs(business_id,customer_id=customer_id)[0]
