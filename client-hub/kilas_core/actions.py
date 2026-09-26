"""Trusted WEB action boundary. Caller owns the event-fenced transaction.

No model IDs/actions/status enter this API. Reuses Phase 3 resolver and Phase 4
validation, operation records and lifecycle. All selection is tenant-scoped.
"""
import hashlib
from . import jobs, playbooks


def snapshot(tx, business_id, conversation_id):
    jobs._positive(business_id)
    link = tx.one('SELECT customer_id FROM kw_web_customer_links WHERE business_id=? AND conversation_id=?',
                  (business_id, conversation_id))
    if not link:
        raise jobs.JobError('not_found', 404)
    jobs._references(tx, business_id, link['customer_id'], conversation_id)
    rows = tx.execute('SELECT * FROM kw_core_jobs WHERE business_id=? AND conversation_id=? ORDER BY id LIMIT 3',
                      (business_id, conversation_id))
    active = [row for row in rows if row['status'] not in ('COMPLETED', 'CANCELLED')]
    # Never split an ambiguous conversation or reopen a finished request automatically.
    blocked = len(active) > 1 or (bool(rows) and not active) or len(rows) >= 3
    row = jobs._row(active[0]) if len(active) == 1 else None
    return {'customer_id': link['customer_id'], 'job': row, 'blocked': blocked,
            'versions': tuple((r['id'], r['version']) for r in rows)}


def state(book, snap):
    row = snap['job']
    if snap['blocked'] or (row and (row['kind'] != book.kind or row['fields'].get('playbook', book.code) != book.code)):
        return None
    fields = row['fields'] if row else {}
    return {k: v for k, v in fields.items() if k in book.fields}, tuple(filter(None, fields.get('uncertain_fields', '').split(',')))


def apply(tx, business_id, conversation_id, *, expected, book, interpretation, event_id, channel='web'):
    """Called after acquiring business then conversation lock and verifying WEB lease/mode.

    The snapshot is from before inference; any intervening owner edit, relink or
    new Job causes a safe conflict, not a model-based overwrite.
    """
    if channel not in ('web','whatsapp'): raise jobs.JobError('invalid_channel')
    actor = jobs._WEB_PLAYBOOK_ACTOR if channel=='web' else jobs._WHATSAPP_PLAYBOOK_ACTOR
    jobs._lock(tx, business_id)
    current = snapshot(tx, business_id, conversation_id)
    if (current['customer_id'], current['versions']) != (expected['customer_id'], expected['versions']):
        raise jobs.JobError('stale_version', 409)
    resolved = state(book, current)
    if resolved is None:
        return None, 'Permintaan ini perlu ditinjau tim agar tidak tercatat sebagai pekerjaan ganda.'
    known, uncertain = resolved
    row = current['job']
    decision = playbooks.decide(book, interpretation, known=known, uncertain=uncertain,
                               current_status=row['status'] if row else None, has_job=bool(row))
    stage = tx.one('SELECT stage FROM kw_core_customer_stages WHERE business_id=? AND customer_id=?',
                   (business_id, current['customer_id']))
    if stage and stage['stage'] != 'CUSTOMER':
        return None, playbooks.response(decision)
    if not decision.write:
        return row, playbooks.response(decision)
    # Preserve owner metadata and unrelated bounded fields rather than replace blindly.
    fields = dict(row['fields']) if row else {}
    fields.update(decision.fields)
    fields.update(playbook=book.code, uncertain_fields=','.join(decision.uncertain),
                  missing_information=playbooks.labels(decision.missing + decision.uncertain))
    key = channel + '_playbook_' + hashlib.sha256((conversation_id + ':' + event_id).encode()).hexdigest()
    if row is None:
        title = book.label + ': ' + str(next(iter(decision.fields.values())))[:120]
        row = jobs._create_job(tx,business_id,current['customer_id'],conversation_id=conversation_id,
                               title=title,kind=book.kind,fields=fields,actor_id=actor,
                               operation_key=key+'_create')
    row = jobs._update_job(tx,business_id,row['id'],expected_version=row['version'],fields=fields,
                           status=decision.target_status,actor_id=actor,operation_key=key+'_update')
    return row, playbooks.response(decision, committed=True)
