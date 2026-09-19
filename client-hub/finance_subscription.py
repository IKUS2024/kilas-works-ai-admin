"""Manual platform Finance billing, independent of Brain and customer Finance invoices."""
import hashlib
import os
import re
from datetime import timedelta
import db
import repo
import finance_entitlements as entitlement
import finance_service as finance
from pricing_config import FINANCE_PLAN


def payment_details():
    keys=('BANK_NAME','BANK_ACCOUNT','BANK_HOLDER')
    details={key:os.environ.get('KILAS_FINANCE_PAYMENT_'+key,'').strip() for key in keys}
    return details if all(details.values()) else None


def bill(business_id,bill_id,actor_user_id):
    finance._scope(business_id,actor_user_id)
    row=db.query_one('SELECT id,business_id,product_key,amount_minor,currency,status,created_at,applied_until FROM finance_subscription_bills WHERE business_id=? AND id=?',(business_id,bill_id))
    if not row: raise finance.FinanceError('bill_unavailable')
    return row


def create_bill(business_id,actor_user_id,request_key):
    if not isinstance(request_key,str) or not re.fullmatch('[a-f0-9]{32}',request_key):raise finance.FinanceError('bill_request')
    if not entitlement.self_service():raise finance.FinanceError('finance_unavailable')
    if not payment_details(): raise finance.FinanceError('payment_not_configured')
    with db.app_purchase_transaction(business_id,None):
        finance._scope(business_id,actor_user_id)
        if entitlement.state(business_id)['status']=='TRIAL_ACTIVE':raise finance.FinanceError('trial_active')
        replay=db.query_one('SELECT bill_id FROM finance_bill_requests WHERE business_id=? AND request_key=?',(business_id,request_key))
        if replay:return replay['bill_id']
        old=db.query_one("SELECT id FROM finance_subscription_bills WHERE business_id=? AND status<>'VERIFIED'",(business_id,))
        if old:
            db.execute('INSERT INTO finance_bill_requests (business_id,request_key,bill_id) VALUES (?,?,?)',(business_id,request_key,old['id']))
            return old['id']
        now=entitlement.now().isoformat()
        result=db.insert_returning_id("INSERT INTO finance_subscription_bills (business_id,product_key,amount_minor,currency,status,created_by_user_id,created_at,updated_at) VALUES (?,?,?,?,'PENDING',?,?,?)",(business_id,FINANCE_PLAN['key'],FINANCE_PLAN['amount_minor'],FINANCE_PLAN['currency'],actor_user_id,now,now))
        db.execute('INSERT INTO finance_bill_requests (business_id,request_key,bill_id) VALUES (?,?,?)',(business_id,request_key,result))
        repo.write_audit(actor_user_id,business_id,'FINANCE_SUBSCRIPTION_BILL_CREATED',f'bill_id={result}')
        return result


def upload_proof(business_id,bill_id,actor_user_id,filename,content):
    import file_utils
    _,mime=file_utils.validate_image_upload(filename,content)
    digest=hashlib.sha256(content).hexdigest()
    with db.app_purchase_transaction(business_id,None):
        current=bill(business_id,bill_id,actor_user_id)
        if entitlement.state(business_id)['status']=='TRIAL_ACTIVE':raise finance.FinanceError('trial_active')
        prior=db.query_one('SELECT id FROM finance_subscription_bills WHERE proof_hash=?',(digest,))
        if prior:
            if prior['id']==bill_id:return current
            raise finance.FinanceError('proof_unavailable')
        if current['status'] not in ('PENDING','REJECTED'):raise finance.FinanceError('bill_state')
        db.execute("UPDATE finance_subscription_bills SET proof_content=?,proof_mime=?,proof_hash=?,status='REVIEW',updated_at=? WHERE business_id=? AND id=?",(content,mime,digest,entitlement.now().isoformat(),business_id,bill_id))
        repo.write_audit(actor_user_id,business_id,'FINANCE_SUBSCRIPTION_PROOF_RECEIVED',f'bill_id={bill_id}')
    return bill(business_id,bill_id,actor_user_id)


def review(business_id,bill_id,actor_user_id,approve):
    if type(approve) is not bool:raise finance.FinanceError('bill_action')
    with db.app_purchase_transaction(business_id,None):
        actor=repo.get_user_by_id(actor_user_id)
        if not actor or actor['role']!='KILAS_ADMIN':raise finance.FinanceError('review_forbidden')
        current=bill(business_id,bill_id,actor_user_id)
        if current['status']=='VERIFIED' and approve:return current
        if current['status']=='REJECTED' and not approve:return current
        if current['status']!='REVIEW':raise finance.FinanceError('bill_state')
        accepted_amounts=tuple(FINANCE_PLAN.get('accepted_amounts_minor') or (FINANCE_PLAN['amount_minor'],))
        if current['product_key']!=FINANCE_PLAN['key'] or current['amount_minor'] not in accepted_amounts or current['currency']!='IDR':raise finance.FinanceError('bill_invalid')
        proof=db.query_one('SELECT proof_hash FROM finance_subscription_bills WHERE business_id=? AND id=?',(business_id,bill_id))
        if not proof['proof_hash']:raise finance.FinanceError('proof_unavailable')
        now=entitlement.now();end=None
        if approve:
            ent=db.query_one('SELECT * FROM finance_entitlements WHERE business_id=?',(business_id,))
            previous=entitlement.parse(ent['paid_until']) if ent else None
            end=(max(now,previous) if previous else now)+timedelta(days=FINANCE_PLAN['period_days'])
            if ent:db.execute('UPDATE finance_entitlements SET paid_until=?,updated_at=? WHERE business_id=?',(end.isoformat(),now.isoformat(),business_id))
            else:db.execute('INSERT INTO finance_entitlements (business_id,paid_until,updated_at) VALUES (?,?,?)',(business_id,end.isoformat(),now.isoformat()))
        db.execute('UPDATE finance_subscription_bills SET status=?,reviewed_by_user_id=?,applied_until=?,updated_at=? WHERE business_id=? AND id=?',('VERIFIED' if approve else 'REJECTED',actor_user_id,end.isoformat() if end else None,now.isoformat(),business_id,bill_id))
        repo.write_audit(actor_user_id,business_id,'FINANCE_SUBSCRIPTION_VERIFIED' if approve else 'FINANCE_SUBSCRIPTION_REJECTED',f'bill_id={bill_id}')
    return bill(business_id,bill_id,actor_user_id)
