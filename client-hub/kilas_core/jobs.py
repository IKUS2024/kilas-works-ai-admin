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
from kilas_core.playbook_definitions import FIELD_LABELS as PLAYBOOK_FIELDS, PLAYBOOKS

STATUS_LABELS = {
    'NEW': 'Perlu tindakan', 'NEEDS_INFORMATION': 'Butuh informasi',
    'READY_FOR_QUOTE': 'Siap ditawarkan', 'QUOTED': 'Sudah ditawarkan',
    'APPROVED': 'Disetujui', 'IN_PROGRESS': 'Dikerjakan',
    'COMPLETED': 'Selesai', 'CANCELLED': 'Dibatalkan',
}
# Owner UI exposes only the three business states used by Kilas Jobs.
# Legacy states remain readable for older automation/playbook rows.
OWNER_STATUS_LABELS = {
    'NEW': 'Perlu tindakan',
    'IN_PROGRESS': 'Dikerjakan',
    'CANCELLED': 'Batal',
}
OWNER_STATUS_GROUPS = {
    'NEW': ('NEW', 'NEEDS_INFORMATION', 'READY_FOR_QUOTE', 'QUOTED', 'APPROVED'),
    'IN_PROGRESS': ('IN_PROGRESS', 'COMPLETED'),
    'CANCELLED': ('CANCELLED',),
}
TRANSITIONS = {
    'NEW': ('NEEDS_INFORMATION', 'READY_FOR_QUOTE', 'IN_PROGRESS', 'CANCELLED'),
    'NEEDS_INFORMATION': ('READY_FOR_QUOTE', 'IN_PROGRESS', 'CANCELLED'),
    'READY_FOR_QUOTE': ('QUOTED', 'IN_PROGRESS', 'CANCELLED'),
    'QUOTED': ('APPROVED', 'IN_PROGRESS', 'CANCELLED'),
    'APPROVED': ('IN_PROGRESS', 'CANCELLED'),
    'IN_PROGRESS': ('COMPLETED', 'CANCELLED'),
    'COMPLETED': (), 'CANCELLED': (),
}


def owner_status(status):
    for key, values in OWNER_STATUS_GROUPS.items():
        if status in values:
            return key
    raise JobError('invalid_status')


def owner_transitions(status):
    current = owner_status(status)
    if current == 'NEW':
        return ('IN_PROGRESS', 'CANCELLED')
    if current == 'IN_PROGRESS' and status != 'COMPLETED':
        return ('CANCELLED',)
    return ()
KINDS = {'ORDER': 'Pesanan', 'BOOKING': 'Booking', 'SHIPMENT': 'Pengiriman',
         'PROJECT': 'Project', 'SERVICE': 'Service', 'GENERIC': 'Pekerjaan'}
# Explicit future-compatible operational keys only. No arbitrary metadata/secrets.
FIELD_LABELS = {'details': 'Rincian', 'quantity': 'Jumlah', 'unit': 'Satuan',
                'origin': 'Asal', 'destination': 'Tujuan',
                'scheduled_at': 'Jadwal', 'reference': 'Referensi',
                'missing_information': 'Informasi yang masih dibutuhkan'}

# Server-only workflow metadata is not accepted by owner form routes.
WORKFLOW_METADATA = {'playbook', 'uncertain_fields',
                     'action', 'intent', 'priority', 'source', 'source_key',
                     'payment_step_reached'}
LEGACY_FIELD_LABELS = dict(FIELD_LABELS)
FIELD_LABELS.update({k: v for k, v in PLAYBOOK_FIELDS.items() if k not in FIELD_LABELS})
_WEB_PLAYBOOK_ACTOR = object()
_WHATSAPP_PLAYBOOK_ACTOR = object()
_CUSTOMER_INSIGHT_ACTOR = object()
_PLAYBOOK_ACTORS = (_WEB_PLAYBOOK_ACTOR, _WHATSAPP_PLAYBOOK_ACTOR, _CUSTOMER_INSIGHT_ACTOR)


def _internal_actor_name(actor_id):
    if actor_id is _WEB_PLAYBOOK_ACTOR:
        return 'WEB_PLAYBOOK'
    if actor_id is _WHATSAPP_PLAYBOOK_ACTOR:
        return 'WHATSAPP_PLAYBOOK'
    if actor_id is _CUSTOMER_INSIGHT_ACTOR:
        return 'CUSTOMER_INSIGHT'
    return None


class JobError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def enabled():
    return os.environ.get('KILAS_JOBS_V2_ENABLED', '').strip().lower() == 'true'


def presentation(category):
    words = set(re.findall(r'[a-z]+', str(category or '').lower()))
    groups = (
        ('ORDER', {'restaurant', 'restoran', 'retail', 'toko', 'warung', 'cafe', 'kafe', 'kuliner', 'food', 'coffee', 'makanan', 'minuman'}),
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
    if not isinstance(fields, dict) or set(fields) - (FIELD_LABELS.keys() | WORKFLOW_METADATA):
        raise JobError('invalid_fields')
    if 'playbook' in fields and (not isinstance(fields['playbook'], str) or fields['playbook'] not in PLAYBOOKS):
        raise JobError('invalid_fields')
    if 'uncertain_fields' in fields:
        pending = fields['uncertain_fields']
        if not isinstance(pending, str) or set(filter(None, pending.split(','))) - PLAYBOOK_FIELDS.keys():
            raise JobError('invalid_fields')
    if 'fulfillment' in fields and fields['fulfillment'] not in ('pickup', 'delivery', 'dine_in'):
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
    item['owner_status'] = owner_status(item['status'])
    item['owner_status_label'] = OWNER_STATUS_LABELS[item['owner_status']]
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
    internal_actor = _internal_actor_name(actor_id)
    if internal_actor:
        actor_id = internal_actor
    else:
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
    origin = _internal_actor_name(actor_id)
    tx.execute('INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)',
               (None if origin else actor_id, bid, action,
                json.dumps({'job_id': jid, 'version': version, **({'origin': origin} if origin else {})})))


def create_job(business_id, customer_id, *, title, actor_id, operation_key,
               conversation_id=None, kind='GENERIC', summary='', fields=None):
    _positive(actor_id)
    with transaction() as tx:
        return _create_job(tx,business_id,customer_id,title=title,actor_id=actor_id,operation_key=operation_key,
                           conversation_id=conversation_id,kind=kind,summary=summary,fields=fields)


def update_job(business_id, job_id, *, expected_version, actor_id, operation_key,
               title=None, summary=None, fields=None, status=None, kind=None):
    _positive(actor_id)
    with transaction() as tx:
        return _update_job(tx,business_id,job_id,expected_version=expected_version,actor_id=actor_id,
                           operation_key=operation_key,title=title,summary=summary,fields=fields,
                           status=status,kind=kind)


def _create_job(tx, business_id, customer_id, *, title, actor_id, operation_key,
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
    _lock(tx, business_id)
    _references(tx, business_id, customer_id, conversation_id)
    stage = tx.one('SELECT stage FROM kw_core_customer_stages WHERE business_id=? AND customer_id=?',
                   (business_id, customer_id))
    if stage and stage['stage'] != 'CUSTOMER':
        raise JobError('not_found', 404)
    replay = _replay(tx, business_id, operation_key, digest)
    if replay:
        return replay
    jid, now = uuid.uuid4().hex, int(time.time())
    tx.execute('INSERT INTO kw_core_jobs(business_id,id,customer_id,conversation_id,kind,title,summary,fields_json,created_at,updated_at) '
               'VALUES (?,?,?,?,?,?,?,?,?,?)',
               (business_id,jid,customer_id,conversation_id,kind,title,summary,encoded,now,now))
    _record(tx,business_id,jid,actor_id,operation_key,digest,1,'JOB_CREATED',now)
    return _row(_get(tx,business_id,jid))


def _update_job(tx, business_id, job_id, *, expected_version, actor_id, operation_key,
               title=None, summary=None, fields=None, status=None, kind=None):
    _positive(expected_version)
    if title is not None:
        title = _text(title,160,True)
    if summary is not None:
        summary = _text(summary,2000)
    encoded = validate_fields(fields) if fields is not None else None
    if status is not None and (not isinstance(status,str) or status not in STATUS_LABELS):
        raise JobError('invalid_status')
    if kind is not None and (not isinstance(kind,str) or kind not in KINDS):
        raise JobError('invalid_kind')
    digest = _operation(business_id,actor_id,operation_key,
                        ['update',job_id,expected_version,title,summary,encoded,status,kind])
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
        # Customer Insight may repair a historical false-positive "Dikerjakan" back to
        # "Perlu tindakan". This exception is intentionally unavailable to owner/manual
        # actors and only applies to AI-generated Customer Insight Jobs.
        insight_reclassification = False
        if (actor_id is _CUSTOMER_INSIGHT_ACTOR
                and current['status'] == 'IN_PROGRESS' and target == 'NEW'):
            try:
                current_fields = json.loads(current['fields_json'])
            except (TypeError, ValueError):
                current_fields = {}
            insight_reclassification = current_fields.get('source') == 'Customer Insight'
        if not insight_reclassification:
            raise JobError('invalid_transition',409)
    if fields is not None and actor_id not in _PLAYBOOK_ACTORS:
        previous = json.loads(current['fields_json'])
        if previous.get('source') == 'Customer Insight':
            preserved = dict(fields)
            for key in ('action','intent','priority','source','source_key','payment_step_reached'):
                if key in previous:
                    preserved[key] = previous[key]
            encoded = validate_fields(preserved)
        if previous.get('playbook') in PLAYBOOKS:
            from .playbooks import missing_fields, labels
            book = PLAYBOOKS[previous['playbook']]
            # Manual form cannot erase or replace trusted workflow metadata.
            preserved = dict(fields, playbook=book.code)
            uncertain = tuple(k for k in previous.get('uncertain_fields', '').split(',')
                              if k and k in fields and fields[k] == previous.get(k))
            preserved['uncertain_fields'] = ','.join(uncertain)
            preserved['missing_information'] = labels(missing_fields(book, preserved) + uncertain)
            encoded = validate_fields(preserved)
    now = int(time.time())
    result = tx.one('UPDATE kw_core_jobs SET kind=?,title=?,summary=?,fields_json=?,status=?,version=version+1,updated_at=? '
                    'WHERE business_id=? AND id=? AND version=? RETURNING *',
                    (current['kind'] if kind is None else kind,
                     current['title'] if title is None else title,
                     current['summary'] if summary is None else summary,
                     current['fields_json'] if encoded is None else encoded,
                     target,now,business_id,job_id,expected_version))
    if not result:
        raise JobError('stale_version',409)
    _record(tx,business_id,job_id,actor_id,operation_key,digest,result['version'],'JOB_UPDATED',now)
    from . import operation_access
    if operation_access.enabled():
        from .automations import observe_job
        observe_job(tx,result)
    return _row(result)

def transition_job(business_id, job_id, status, **kwargs):
    return update_job(business_id,job_id,status=status,**kwargs)


def get_job(business_id, job_id):
    _positive(business_id)
    with transaction() as tx:
        return _row(_get(tx,business_id,job_id))


def list_jobs(business_id, *, search='', status='', page=1, customer_id=None, conversation_id=None,
              customer_stage=None, statuses=None):
    _positive(business_id)
    if status and status not in STATUS_LABELS:
        raise JobError('invalid_status')
    if customer_stage is not None and customer_stage not in ('LEAD', 'CUSTOMER'):
        raise JobError('invalid_scope')
    if statuses is not None:
        if not isinstance(statuses, (tuple, list)) or not statuses or any(s not in STATUS_LABELS for s in statuses):
            raise JobError('invalid_status')
        if status:
            raise JobError('invalid_status')
    search = _text(search,120)
    where, args = 'business_id=?', [business_id]
    if statuses:
        marks = ','.join('?' for _ in statuses)
        where += ' AND status IN (' + marks + ')'
        args += list(statuses)
    if customer_stage:
        where += (
            ' AND customer_id IN (SELECT customer_id FROM kw_core_customer_stages '
            'WHERE business_id=? AND stage=?)'
        )
        args += [business_id, customer_stage]
    for column, value in (('status',status),('customer_id',customer_id),('conversation_id',conversation_id)):
        if value:
            where += ' AND ' + column + '=?'
            args.append(value)
    if search:
        like = '%'+search+'%'
        where += (
            ' AND (LOWER(title) LIKE LOWER(?) OR LOWER(summary) LIKE LOWER(?) '
            'OR LOWER(fields_json) LIKE LOWER(?) OR customer_id IN '
            '(SELECT id FROM kw_core_customers WHERE business_id=? AND LOWER(display_name) LIKE LOWER(?)))'
        )
        args += [like, like, like, business_id, like]
    with transaction() as tx:
        total = tx.one('SELECT COUNT(*) AS n FROM kw_core_jobs WHERE '+where,tuple(args))['n']
        pages = max(1,(total+9)//10)
        try:
            page = min(max(1,int(page)),pages)
        except (TypeError,ValueError):
            raise JobError('invalid_page')
        rows = tx.execute(
            'SELECT * FROM kw_core_jobs WHERE '+where+' ORDER BY updated_at DESC,id LIMIT 10 OFFSET ?',
            tuple(args+[(page-1)*10]))
        return [_row(row) for row in rows],total,page,pages


def jobs_for_customer(business_id, customer_id):
    with transaction() as tx:
        _references(tx,business_id,customer_id,None)
    return list_jobs(business_id,customer_id=customer_id)[0]
