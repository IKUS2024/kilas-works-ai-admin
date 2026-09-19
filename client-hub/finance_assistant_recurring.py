"""Reviewed recurring schedules, using existing recurring service and business lock."""
import hashlib
import re
import uuid
from itsdangerous import URLSafeTimedSerializer, BadData
from flask import current_app

import finance_service as finance
import finance_operator as operator
import finance_branches as branches
import finance_entitlements as entitlements
import finance_fx

TTL = 600
FIELDS = {'name', 'amount_text', 'cadence', 'next_due_on', 'end_on', 'account_id', 'category_id'}
EVENT = 'FINANCE_ASSISTANT_RECURRING_CONFIRMED'


def suggest(text):
    # Suggestions only. Missing/ambiguous values stay blank for the user's review.
    amounts = re.findall(r'(?<![\w.,+−-])(?:[Rr][Pp]\.?\s*)?\d+(?:\.\d{3})*(?:,\d{1,3})?\s*(?:rb|ribu|jt|juta)\b|\b[Rr][Pp]\.?\s*\d+(?:\.\d{3})*(?:,\d{1,3})?', text)
    cadence = []
    if re.search(r'\b(bulanan|tiap bulan|setiap bulan)\b', text, re.I):cadence.append('MONTHLY')
    if re.search(r'\b(mingguan|tiap minggu|setiap minggu)\b', text, re.I):cadence.append('WEEKLY')
    return dict(name=text[:160], amount_text=amounts[0].strip() if len(amounts)==1 else '',
                cadence=cadence[0] if len(cadence)==1 else '')


def signer():
    operator.signer()  # Same production key validation; separate purpose/salt.
    return URLSafeTimedSerializer(current_app.secret_key, salt='kilas-finance-recurring-draft-v1',
                                  signer_kwargs={'digest_method': hashlib.sha256})


def validate(business_id, user_id, fields):
    entitlements.require_ai(business_id, user_id, 'OPERATOR')
    finance._scope(business_id, user_id)
    branches.token_branch(business_id)
    if not isinstance(fields, dict) or set(fields) != FIELDS:
        raise ValueError('invalid_fields')
    name=finance._text(fields['name'],160,True)
    cadence=finance._enum(fields['cadence'],('WEEKLY','MONTHLY'))
    start=finance._date(fields['next_due_on'])
    end=fields['end_on']
    if end is not None:end=finance._period(start,end)[1]
    account_id=finance._id(fields['account_id']);category_id=finance._id(fields['category_id'])
    accounts=finance.list_accounts(business_id,actor_user_id=user_id)
    categories=finance.list_categories(business_id,'EXPENSE',actor_user_id=user_id)
    account=next((a for a in accounts if a['id']==account_id),None)
    category=next((c for c in categories if c['id']==category_id),None)
    if not account or not category:raise ValueError('reference_unavailable')
    currency=account['currency']
    if currency=='IDR':amount=operator.rupiah(fields['amount_text'])
    else:
        from routes_finance import currency_amount
        raw=operator.text(fields['amount_text'],60)
        match=re.fullmatch(r'(?:'+currency+r'\s+)?([0-9]+(?:[.,][0-9]{1,2})?)(?:\s+'+currency+r')?',raw,re.I)
        if not match:raise ValueError('invalid_amount')
        amount=currency_amount(match[1],currency)
    return dict(name=name,amount_minor=amount,account_id=account_id,category_id=category_id,
                cadence=cadence,next_due_on=start,end_on=end,expected_currency=currency), [
        ['Nama',name],['Nominal',finance_fx.format_money(amount,currency)],
        ['Kas / Rekening',account['name']],['Kategori',category['name']],
        ['Frekuensi','Bulanan' if cadence=='MONTHLY' else 'Mingguan'],
        ['Jatuh tempo pertama',start],['Berakhir',end or 'Sampai dinonaktifkan']]


def prepare(business_id,user_id,fields):
    draft_signer=signer()
    values,preview=validate(business_id,user_id,fields)
    token=draft_signer.dumps(dict(version=1,business_id=business_id,user_id=user_id,
        branch_id=branches.token_branch(business_id),fields=fields,currency=values['expected_currency'],nonce=uuid.uuid4().hex))
    return dict(token=token,preview=preview,expires_in=TTL)


def confirm(business_id,user_id,token):
    if not isinstance(token,str) or not 1<=len(token)<=6000:raise ValueError('invalid_draft')
    try:data=signer().loads(token,max_age=TTL)
    except BadData:raise ValueError('invalid_draft') from None
    if (not isinstance(data,dict) or set(data)!={'version','business_id','user_id','branch_id','fields','currency','nonce'}
            or type(data['version']) is not int or data['version']!=1
            or type(data['business_id']) is not int or data['business_id']!=business_id
            or type(data['user_id']) is not int or data['user_id']!=user_id
            or not isinstance(data['nonce'],str) or not re.fullmatch('[a-f0-9]{32}',data['nonce'])):
        raise ValueError('invalid_draft')
    branches.check_token(business_id,data['branch_id'])
    # The durable audit marker and rule are committed together under the existing business lock.
    # Only a digest and record ID are retained: no prompt, file, token or financial values.
    values,_=validate(business_id,user_id,data['fields'])
    if values['expected_currency']!=data['currency']:raise ValueError('currency_changed')
    record_id=finance.create_recurring_expense(business_id,**values,actor_user_id=user_id,
        idempotency_key=hashlib.sha256(data['nonce'].encode()).hexdigest())
    return dict(record_id=record_id,message='Jadwal biaya rutin tersimpan. Belum ada pengeluaran dicatat. Tandai biaya yang sudah dibayar melalui Biaya Rutin.')
