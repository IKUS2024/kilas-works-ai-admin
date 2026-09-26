"""Owner-confirmed Core links to the existing authoritative Finance engine.

Finance remains the sole invoice, payment, and ledger authority. This bridge never invents a
second financial ledger: invoice issue/payment reuse Finance service APIs, while customer delivery
uses the official WhatsApp transport and preserves its channel/window/takeover safeguards.
"""
import hashlib
import json
import os
import re
from contextlib import contextmanager
import db
import repo
import finance_service as finance
import finance_branches as branches
import finance_entitlements as entitlements
import finance_invoice_view
from . import customers, jobs, customer_insights, whatsapp_transport
from .flags import enabled_for_business


class BridgeError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def enabled():
    return os.environ.get('KILAS_FINANCE_BRIDGE_ENABLED', '').lower() == 'true'


def _owner(bid, actor):
    if type(bid) is not int or type(actor) is not int or bid <= 0 or actor <= 0:
        raise BridgeError('not_found', 404)
    if not db.query_one("SELECT 1 FROM business_memberships WHERE business_id=? AND user_id=? "
                        "AND role_in_business='OWNER'", (bid, actor)):
        raise BridgeError('not_found', 404)


def _finance_owner(bid, actor):
    _owner(bid, actor)
    # Match existing Finance product visibility as well as service entitlement.
    if not (entitlements.self_service() or entitlements.flag('KILAS_FINANCE_BETA')
            or db.query_one("SELECT 1 FROM users WHERE id=? AND role='KILAS_ADMIN'",(actor,))):
        raise BridgeError('unavailable',404)


def _source(bid, actor):
    _owner(bid, actor)
    if not enabled() or not customers.enabled() or not jobs.enabled() or not enabled_for_business(bid):
        raise BridgeError('unavailable', 404)
    row = db.query_one('SELECT b.package,b.status,s.status AS subscription_status '
                       'FROM businesses b LEFT JOIN subscriptions s ON s.business_id=b.id WHERE b.id=?', (bid,))
    if (not row or row['package'] not in customers.AI_PACKAGES
            or row['status'] in ('ARCHIVED', 'SUSPENDED', 'CANCELLED')
            or row['subscription_status'] not in ('ACTIVE', 'GRACE')):
        raise BridgeError('unavailable', 404)


def _customer(bid, cid):
    if not isinstance(cid, str) or not 1 <= len(cid) <= 64:
        raise BridgeError('not_found', 404)
    row = db.query_one('SELECT * FROM kw_core_customers WHERE business_id=? AND id=?', (bid, cid))
    if not row:
        raise BridgeError('not_found', 404)
    return row


def _job(bid, jid):
    if not isinstance(jid, str) or not 1 <= len(jid) <= 64:
        raise BridgeError('not_found', 404)
    row = db.query_one('SELECT * FROM kw_core_jobs WHERE business_id=? AND id=?', (bid, jid))
    if not row:
        raise BridgeError('not_found', 404)
    return row


def _connection(bid):
    return db.query_one('SELECT * FROM kw_core_finance_connections WHERE source_business_id=? '
                        'ORDER BY version DESC LIMIT 1', (bid,))


def connection(bid, actor):
    _source(bid, actor)
    return _connection(bid)


def _request(bid, actor, key, kind, payload, confirmed):
    _source(bid, actor)
    if confirmed is not True:
        raise BridgeError('confirmation_required')
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{32}', key):
        raise BridgeError('invalid_operation_key')
    try:
        encoded = json.dumps([actor, kind, payload], sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise BridgeError('invalid_request') from None
    if len(encoded.encode()) > 20000:
        raise BridgeError('invalid_request')
    return hashlib.sha256(encoded.encode()).hexdigest()


def _replay(bid, actor, key, digest):
    row = db.query_one('SELECT * FROM kw_core_finance_operations WHERE source_business_id=? AND operation_key=?', (bid, key))
    if row and (row['actor_user_id'] != actor or row['request_hash'] != digest):
        raise BridgeError('operation_conflict', 409)
    return row


def _record(bid, actor, key, digest, kind, reference, mapping, finance_reference=None):
    db.execute('INSERT INTO kw_core_finance_operations '
               '(source_business_id,operation_key,request_hash,kind,actor_user_id,reference,'
               'finance_business_id,connection_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
               (bid,key,digest,kind,actor,str(reference),mapping['finance_business_id'],mapping['version'],repo._now()))
    repo.write_audit(actor,bid,'CORE_FINANCE_'+kind.upper(),json.dumps({
        'operation_key':key,'reference':str(reference),'finance_business_id':mapping['finance_business_id'],
        'finance_branch_id':mapping['finance_branch_id'],'connection_version':mapping['version'],'finance_reference':finance_reference},sort_keys=True))


def _version(value, initial=False):
    if type(value) is not int or value < (0 if initial else 1):
        raise BridgeError('stale_connection', 409)


@contextmanager
def _command(bid, actor, mapping):
    target, branch = mapping['finance_business_id'], mapping['finance_branch_id']
    _finance_owner(target, actor)
    with branches.scope(target, branch, actor):
        with finance._write(target, actor, related_business_ids=(bid,)):
            # Recheck both sides after lock acquisition, before any link/write.
            _source(bid, actor)
            _finance_owner(target, actor)
            if branches.get(target,branch,active=True,actor_user_id=actor)['workspace_type'] != 'BUSINESS':
                raise BridgeError('business_branch_required')
            yield


def configure(bid, actor, *, finance_business_id, finance_branch_id, expected_version,
              enabled_value, operation_key, confirmed=False):
    _version(expected_version, initial=True)
    if type(enabled_value) is not bool:
        raise BridgeError('invalid_request')
    finance._id(finance_business_id); finance._id(finance_branch_id)
    payload = dict(finance_business_id=finance_business_id,finance_branch_id=finance_branch_id,
                   expected_version=expected_version,enabled=enabled_value)
    digest = _request(bid,actor,operation_key,'connection',payload,confirmed)
    prior = _replay(bid,actor,operation_key,digest)
    if prior:
        _finance_owner(prior['finance_business_id'],actor)
        return db.query_one('SELECT * FROM kw_core_finance_connections WHERE source_business_id=? AND version=?',
                            (bid,prior['connection_version']))
    mapping = dict(finance_business_id=finance_business_id,finance_branch_id=finance_branch_id)
    with _command(bid,actor,mapping):
        prior = _replay(bid,actor,operation_key,digest)
        if prior:
            return db.query_one('SELECT * FROM kw_core_finance_connections WHERE source_business_id=? AND version=?',
                                (bid,prior['connection_version']))
        current = _connection(bid)
        if (current['version'] if current else 0) != expected_version:
            raise BridgeError('stale_connection',409)
        mapping['version'] = expected_version + 1
        db.execute('INSERT INTO kw_core_finance_connections '
                   '(source_business_id,version,finance_business_id,finance_branch_id,enabled,actor_user_id,created_at) '
                   'VALUES (?,?,?,?,?,?,?)',
                   (bid,mapping['version'],finance_business_id,finance_branch_id,enabled_value,actor,repo._now()))
        _record(bid,actor,operation_key,digest,'connection',mapping['version'],mapping)
        return _connection(bid)


def _active_mapping(bid, expected_version):
    _version(expected_version)
    mapping = _connection(bid)
    if not mapping or not mapping['enabled']:
        raise BridgeError('not_connected',409)
    if mapping['version'] != expected_version:
        raise BridgeError('stale_connection',409)
    return mapping


def _finance_key(bid, key, kind):
    return hashlib.sha256(f'core-bridge:{bid}:{kind}:{key}'.encode()).hexdigest()[:32]


def _customer_result(bid, cid, target, actor):
    _finance_owner(target,actor)
    link = db.query_one('SELECT * FROM kw_core_finance_customer_links WHERE '
                        'source_business_id=? AND core_customer_id=? AND finance_business_id=?', (bid,cid,target))
    if not link:
        raise BridgeError('link_unavailable',404)
    with branches.scope(target,link['finance_branch_id'],actor):
        customer = finance.get_customer(target,link['finance_customer_id'],actor)
    if not customer:
        raise BridgeError('link_unavailable',404)
    return dict(link=dict(link),customer=dict(customer))


def link_customer(bid, actor, cid, *, expected_version, operation_key, confirmed=False,
                  existing_customer_id=None, new_customer=None):
    payload = dict(cid=cid,expected_version=expected_version,existing_customer_id=existing_customer_id,new_customer=new_customer)
    digest = _request(bid,actor,operation_key,'customer',payload,confirmed)
    _customer(bid,cid)
    prior = _replay(bid,actor,operation_key,digest)
    if prior:
        return _customer_result(bid,cid,prior['finance_business_id'],actor)
    if (existing_customer_id is None) == (new_customer is None):
        raise BridgeError('choose_customer')
    if new_customer is not None and (not isinstance(new_customer,dict)
            or 'name' not in new_customer or set(new_customer)-{'name','phone','email'}):
        raise BridgeError('invalid_customer')
    mapping = _active_mapping(bid,expected_version)
    with _command(bid,actor,mapping):
        prior = _replay(bid,actor,operation_key,digest)
        if prior:
            return _customer_result(bid,cid,prior['finance_business_id'],actor)
        _active_mapping(bid,expected_version); _customer(bid,cid)
        target = mapping['finance_business_id']
        if db.query_one('SELECT 1 FROM kw_core_finance_customer_links WHERE source_business_id=? '
                        'AND core_customer_id=? AND finance_business_id=?',(bid,cid,target)):
            raise BridgeError('customer_already_linked',409)
        if existing_customer_id is not None:
            customer = finance.get_customer(target,existing_customer_id,actor)
            if not customer or not customer['is_active']:
                raise BridgeError('customer_unavailable',404)
            customer_id = customer['id']
        else:
            customer_id = finance.create_customer(target,actor_user_id=actor,
                idempotency_key=_finance_key(bid,operation_key,'customer'),**new_customer)
        db.execute('INSERT INTO kw_core_finance_customer_links '
                   '(source_business_id,core_customer_id,finance_business_id,finance_customer_id,'
                   'finance_branch_id,connection_version,actor_user_id,created_at) VALUES (?,?,?,?,?,?,?,?)',
                   (bid,cid,target,customer_id,mapping['finance_branch_id'],mapping['version'],actor,repo._now()))
        _record(bid,actor,operation_key,digest,'customer',cid,mapping,customer_id)
        return _customer_result(bid,cid,target,actor)


def _invoice_result(bid, jid, actor):
    link = db.query_one('SELECT * FROM kw_core_finance_invoice_links WHERE source_business_id=? AND core_job_id=?',(bid,jid))
    if not link:
        return None
    target = link['finance_business_id']
    _finance_owner(target,actor)
    with branches.scope(target,link['finance_branch_id'],actor):
        # Status and all amounts come from one Finance-authoritative SQL snapshot.
        invoice = finance.get_invoice_totals(target,link['finance_invoice_id'],actor,include_identity=True)
    if invoice['branch_id'] != link['finance_branch_id'] or invoice['customer_id'] != link['finance_customer_id']:
        raise BridgeError('link_unavailable',404)
    return dict(link=dict(link),invoice=invoice)


def read_invoice(bid, actor, jid):
    _source(bid,actor); _job(bid,jid)
    return _invoice_result(bid,jid,actor)


def _deal_job(bid, actor, jid):
    _source(bid, actor)
    job = _job(bid, jid)
    if jobs.owner_status(job['status']) != 'IN_PROGRESS':
        raise BridgeError('job_not_deal', 409)
    return job


def ensure_job_customer_link(bid, actor, jid, *, expected_version, operation_key):
    job = _deal_job(bid, actor, jid)
    mapping = _active_mapping(bid, expected_version)
    existing = db.query_one(
        'SELECT * FROM kw_core_finance_customer_links WHERE source_business_id=? '
        'AND core_customer_id=? AND finance_business_id=?',
        (bid, job['customer_id'], mapping['finance_business_id']),
    )
    if existing:
        if existing['finance_branch_id'] != mapping['finance_branch_id']:
            raise BridgeError('customer_link_wrong_branch', 409)
        return _customer_result(bid, job['customer_id'], mapping['finance_business_id'], actor)
    customer = _customer(bid, job['customer_id'])
    return link_customer(
        bid, actor, job['customer_id'], expected_version=expected_version,
        operation_key=operation_key, confirmed=True,
        new_customer={'name': customer['display_name'], 'phone': customer.get('phone') or '',
                      'email': customer.get('email') or ''},
    )


def invoice_editor_context(bid, actor, jid, *, expected_version, finance_business_id, finance_branch_id,
                           invoice_id=None):
    job = _deal_job(bid, actor, jid)
    mapping = _active_mapping(bid, expected_version)
    if mapping['finance_business_id'] != finance_business_id or mapping['finance_branch_id'] != finance_branch_id:
        raise BridgeError('stale_connection', 409)
    link = db.query_one(
        'SELECT * FROM kw_core_finance_customer_links WHERE source_business_id=? '
        'AND core_customer_id=? AND finance_business_id=?',
        (bid, job['customer_id'], finance_business_id),
    )
    if not link or link['finance_branch_id'] != finance_branch_id:
        raise BridgeError('customer_link_required', 409)
    result = _invoice_result(bid, jid, actor)
    if invoice_id is not None:
        if not result or result['link']['finance_invoice_id'] != invoice_id:
            raise BridgeError('link_unavailable', 404)
    elif result:
        raise BridgeError('invoice_already_linked', 409)
    return dict(job=job, mapping=dict(mapping), link=dict(link), result=result)


def attach_existing_invoice(bid, actor, jid, invoice_id, *, expected_version):
    existing = _invoice_result(bid, jid, actor)
    if existing:
        if existing['link']['finance_invoice_id'] != invoice_id:
            raise BridgeError('invoice_already_linked', 409)
        return existing
    mapping = _active_mapping(bid, expected_version)
    ctx = invoice_editor_context(
        bid, actor, jid, expected_version=expected_version,
        finance_business_id=mapping['finance_business_id'], finance_branch_id=mapping['finance_branch_id'])
    link = ctx['link']; target = mapping['finance_business_id']
    with branches.scope(target, mapping['finance_branch_id'], actor):
        invoice = finance.get_finance_invoice(target, invoice_id, actor)
        if (not invoice or invoice['branch_id'] != mapping['finance_branch_id']
                or invoice['customer_id'] != link['finance_customer_id'] or invoice['status'] == 'VOID'):
            raise BridgeError('link_unavailable', 404)
    db.execute(
        'INSERT INTO kw_core_finance_invoice_links '
        '(source_business_id,core_job_id,core_customer_id,finance_business_id,finance_branch_id,'
        'finance_customer_id,finance_invoice_id,connection_version,actor_user_id,created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?)',
        (bid, jid, ctx['job']['customer_id'], target, mapping['finance_branch_id'],
         link['finance_customer_id'], invoice_id, mapping['version'], actor, repo._now()))
    repo.write_audit(actor, bid, 'CORE_FINANCE_INVOICE_ATTACHED', json.dumps({
        'job_id': jid, 'finance_business_id': target, 'finance_invoice_id': invoice_id,
        'finance_branch_id': mapping['finance_branch_id']}, sort_keys=True))
    return _invoice_result(bid, jid, actor)


def issue_job_invoice(bid, actor, jid):
    _deal_job(bid, actor, jid)
    result = _invoice_result(bid, jid, actor)
    if not result:
        raise BridgeError('invoice_required', 409)
    link = result['link']; target = link['finance_business_id']
    with branches.scope(target, link['finance_branch_id'], actor):
        current = finance.get_finance_invoice(target, link['finance_invoice_id'], actor)
        if not current:
            raise BridgeError('link_unavailable', 404)
        if current['status'] == 'DRAFT':
            finance.issue_finance_invoice(target, current['id'], actor_user_id=actor)
        elif current['status'] not in ('ISSUED', 'PARTIALLY_PAID', 'PAID'):
            raise BridgeError('invoice_unavailable', 409)
    return _invoice_result(bid, jid, actor)


def invoice_delivery_status(bid, finance_invoice_id):
    row = db.query_one(
        "SELECT status,error,event_id FROM kw_core_wa_outbound WHERE business_id=? "
        "AND event_id LIKE ? ORDER BY created_at DESC LIMIT 1",
        (bid, f"invoice:{finance_invoice_id}:%"))
    return dict(row) if row else None


def _job_whatsapp_conversation(bid, job):
    cid = job.get('conversation_id')
    if cid and db.query_one(
        'SELECT 1 FROM kw_core_wa_conversations WHERE business_id=? AND conversation_id=?', (bid, cid)):
        return cid
    rows = customer_insights.whatsapp_conversation_rows(bid, job['customer_id'])
    return rows[0]['id'] if rows else None


def publish_and_send_invoice(bid, actor, jid, operation_key):
    result = issue_job_invoice(bid, actor, jid)
    link, invoice = result['link'], result['invoice']
    sent = db.query_one(
        "SELECT status,error,event_id FROM kw_core_wa_outbound WHERE business_id=? "
        "AND event_id LIKE ? AND status IN ('accepted','sent','delivered','read') "
        "ORDER BY created_at DESC LIMIT 1",
        (bid, f"invoice:{link['finance_invoice_id']}:%"))
    if sent:
        return dict(result=result, delivery=dict(sent), already_sent=True)
    cid = _job_whatsapp_conversation(bid, _job(bid, jid))
    if not cid:
        return dict(result=result, delivery={'status':'conversation_unavailable'}, already_sent=False)
    try:
        base = finance_invoice_view.base_url()
        token = finance_invoice_view.create_token(link['finance_business_id'], link['finance_invoice_id'], actor)
        share_url = base + '/finance/invoice-share/' + token
        message = f"Invoice {invoice['invoice_number']} sudah terbit.\nSilakan lihat detail invoice di:\n{share_url}"
        delivery = whatsapp_transport.system_text(
            bid, cid, f"invoice:{link['finance_invoice_id']}:{operation_key}", message, actor)
    except Exception:
        delivery = {'status':'send_unavailable','error':'transactional_send_failed'}
    if delivery.get('status') in ('accepted','sent','delivered','read'):
        repo.write_audit(actor,bid,'CORE_FINANCE_INVOICE_SENT',json.dumps({
            'job_id':jid,'finance_invoice_id':link['finance_invoice_id'],
            'conversation_id':cid,'status':delivery.get('status')},sort_keys=True))
    return dict(result=_invoice_result(bid,jid,actor),delivery=delivery,already_sent=False)


def payment_options(bid, actor, jid):
    _deal_job(bid, actor, jid)
    result = _invoice_result(bid, jid, actor)
    if not result:
        raise BridgeError('invoice_required', 409)
    link=result['link']; target=link['finance_business_id']
    with branches.scope(target,link['finance_branch_id'],actor):
        return dict(accounts=finance.list_accounts(target,actor_user_id=actor),
                    categories=finance.list_categories(target,'INCOME',actor_user_id=actor),
                    today=finance.business_today(target).isoformat())


def record_full_payment(bid, actor, jid, *, paid_on, account_id, category_id, note, payment_key):
    _deal_job(bid, actor, jid)
    result=_invoice_result(bid,jid,actor)
    if not result:
        raise BridgeError('invoice_required',409)
    link,invoice=result['link'],result['invoice']
    if invoice['status']=='PAID' and invoice['outstanding_minor']==0:
        return result
    if invoice['status'] not in ('ISSUED','PARTIALLY_PAID') or invoice['outstanding_minor']<=0:
        raise BridgeError('invoice_not_payable',409)
    target=link['finance_business_id']
    with branches.scope(target,link['finance_branch_id'],actor):
        finance.record_invoice_payment(
            target,link['finance_invoice_id'],invoice['outstanding_minor'],paid_on,
            account_id,category_id,note=note,actor_user_id=actor,idempotency_key=payment_key)
    repo.write_audit(actor,bid,'CORE_FINANCE_JOB_PAYMENT_RECORDED',json.dumps({
        'job_id':jid,'finance_invoice_id':link['finance_invoice_id'],
        'amount_minor':invoice['outstanding_minor']},sort_keys=True))
    return _invoice_result(bid,jid,actor)


def customer_links(bid, actor, cid):
    _source(bid,actor); _customer(bid,cid)
    links = db.query_all('SELECT * FROM kw_core_finance_customer_links WHERE source_business_id=? AND core_customer_id=?',(bid,cid))
    return [_customer_result(bid,cid,link['finance_business_id'],actor) for link in links]


def create_draft(bid, actor, jid, *, expected_version, operation_key, invoice, confirmed=False):
    if not isinstance(invoice,dict) or set(invoice)-{'items','currency','issue_date','due_date','notes'} or not {'items','currency','issue_date','due_date'} <= set(invoice):
        raise BridgeError('invoice_fields_required')
    payload = dict(jid=jid,expected_version=expected_version,invoice=invoice)
    digest = _request(bid,actor,operation_key,'invoice',payload,confirmed)
    _job(bid,jid)
    prior = _replay(bid,actor,operation_key,digest)
    if prior:
        return _invoice_result(bid,jid,actor)
    mapping = _active_mapping(bid,expected_version)
    with _command(bid,actor,mapping):
        prior = _replay(bid,actor,operation_key,digest)
        if prior:
            return _invoice_result(bid,jid,actor)
        _active_mapping(bid,expected_version)
        job = _job(bid,jid)
        if job['status']=='CANCELLED':
            raise BridgeError('job_unavailable',409)
        if db.query_one('SELECT 1 FROM kw_core_finance_invoice_links WHERE source_business_id=? AND core_job_id=?',(bid,jid)):
            raise BridgeError('invoice_already_linked',409)
        target = mapping['finance_business_id']
        linked = _customer_result(bid,job['customer_id'],target,actor)
        invoice_id = finance.create_finance_invoice(target,linked['customer']['id'],
            actor_user_id=actor,idempotency_key=_finance_key(bid,operation_key,'invoice'),**invoice)
        db.execute('INSERT INTO kw_core_finance_invoice_links '
                   '(source_business_id,core_job_id,core_customer_id,finance_business_id,finance_branch_id,'
                   'finance_customer_id,finance_invoice_id,connection_version,actor_user_id,created_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (bid,jid,job['customer_id'],target,mapping['finance_branch_id'],linked['customer']['id'],
                    invoice_id,mapping['version'],actor,repo._now()))
        _record(bid,actor,operation_key,digest,'invoice',jid,mapping,invoice_id)
        return _invoice_result(bid,jid,actor)
