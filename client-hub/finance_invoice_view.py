"""Read-only Finance invoice presentation and purpose-bound customer sharing."""
import hashlib
import os
from urllib.parse import urlsplit
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadData
import db
import finance_service as finance

VISIBLE = ('ISSUED','PARTIALLY_PAID','PAID')
SHARE_TTL = 7 * 24 * 60 * 60


def signer():
    key=current_app.secret_key
    if not key or (not current_app.testing and (len(key)<32 or key=='dev-only-insecure-secret-key-do-not-use-in-production')):
        raise ValueError('share_not_configured')
    return URLSafeTimedSerializer(key,salt='kilas-finance-invoice-share-v1',signer_kwargs={'digest_method':hashlib.sha256})


def base_url():
    value=os.environ.get('PUBLIC_APP_BASE_URL','').rstrip('/')
    parts=urlsplit(value)
    if (parts.scheme!='https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('','/') or any(c.isspace() for c in value)):
        raise ValueError('share_not_configured')
    return value


def create_token(business_id,invoice_id,user_id):
    __import__("finance_entitlements").require_write(business_id,user_id)
    invoice=finance.get_finance_invoice(business_id,invoice_id,actor_user_id=user_id)
    if not invoice or invoice['status'] not in VISIBLE: raise ValueError('unavailable')
    return signer().dumps({'purpose':'finance_invoice_view','business_id':business_id,'invoice_id':invoice_id})


def resolve_token(token):
    if not isinstance(token,str) or len(token)>1024: raise ValueError('unavailable')
    try: data=signer().loads(token,max_age=SHARE_TTL)
    except BadData: raise ValueError('unavailable') from None
    if (not isinstance(data,dict) or set(data)!={'purpose','business_id','invoice_id'}
            or data['purpose']!='finance_invoice_view'):
        raise ValueError('unavailable')
    for key in ('business_id','invoice_id'):finance._id(data[key])
    return data['business_id'],data['invoice_id']


def document(business_id,invoice_id,user_id=None,public=False):
    """Only call with authorized membership or a verified share token. No write helpers."""
    invoice=finance.get_finance_invoice(business_id,invoice_id,actor_user_id=user_id)
    if not invoice or (public and invoice['status'] not in VISIBLE): raise ValueError('unavailable')
    business=db.query_one('SELECT business_name FROM businesses WHERE id=?',(business_id,))
    customer=finance.get_customer(business_id,invoice['customer_id'],actor_user_id=user_id)
    if not business or not customer: raise ValueError('unavailable')
    items=finance.list_invoice_items(business_id,invoice_id,actor_user_id=user_id)
    totals=finance.get_invoice_totals(business_id,invoice_id,actor_user_id=user_id)
    # Explicit public projection: no internal IDs, audit, customer/private payment notes or accounts.
    return dict(issuer=business['business_name'],
        invoice={key:invoice[key] for key in ('invoice_number','status','issue_date','due_date','currency','notes')},
        customer={key:customer[key] for key in ('name','email','phone')},
        items=[{key:item[key] for key in ('description','quantity','unit_price_minor')} for item in items],totals=totals)
