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
REQUIRED_FIELDS = {'name', 'amount_text', 'cadence', 'next_due_on', 'end_on', 'category_id'}
OPTIONAL_FIELDS = {'currency', 'account_id', 'project_id', 'counterparty_name', 'description'}
FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
EVENT = 'FINANCE_ASSISTANT_RECURRING_CONFIRMED'


def suggest(text):
    # Suggestions only. Missing/ambiguous values stay blank for the user's review.
    amounts = re.findall(r'(?<![\w.,+−-])(?:[Rr][Pp]\.?\s*)?\d+(?:\.\d{3})*(?:,\d{1,3})?\s*(?:rb|ribu|jt|juta)\b|\b[Rr][Pp]\.?\s*\d+(?:\.\d{3})*(?:,\d{1,3})?', text)
    cadence = []
    if re.search(r'\b(sekali|satu kali|one[ -]?time)\b', text, re.I):cadence.append('ONCE')
    if re.search(r'\b(bulanan|tiap bulan|setiap bulan)\b', text, re.I):cadence.append('MONTHLY')
    if re.search(r'\b(mingguan|tiap minggu|setiap minggu)\b', text, re.I):cadence.append('WEEKLY')
    return dict(name=text[:160], amount_text=amounts[0].strip() if len(amounts)==1 else '',
                cadence=cadence[0] if len(cadence)==1 else '')


def signer():
    operator.signer()  # Same production key validation; separate purpose/salt.
    return URLSafeTimedSerializer(current_app.secret_key, salt='kilas-finance-recurring-draft-v1',
                                  signer_kwargs={'digest_method': hashlib.sha256})


def normalize_fields(fields):
    if (not isinstance(fields, dict) or not REQUIRED_FIELDS.issubset(fields)
            or any(key not in FIELDS for key in fields)):
        raise ValueError('invalid_fields')
    result=dict(fields)
    result.setdefault('currency',None)
    result.setdefault('account_id',None)
    result.setdefault('project_id',None)
    result.setdefault('counterparty_name',None)
    result.setdefault('description',None)
    return result


def validate(business_id, user_id, fields):
    entitlements.require_ai(business_id, user_id, 'OPERATOR')
    finance._scope(business_id, user_id)
    branches.token_branch(business_id)
    fields=normalize_fields(fields)
    name=finance._text(fields['name'],160,True)
    requested_cadence=finance._enum(fields['cadence'],('ONCE','WEEKLY','MONTHLY'))
    start=finance._date(fields['next_due_on'])
    if requested_cadence=='ONCE':
        cadence='MONTHLY'
        end=start
    else:
        cadence=requested_cadence
        end=fields['end_on']
        if end in ('',None):end=None
        if end is not None:end=finance._period(start,end)[1]

    all_accounts=[
        a for a in finance.list_accounts(business_id,actor_user_id=user_id)
        if a['is_active']
    ]
    requested_account=None
    if fields.get('account_id') not in (None,''):
        account_id=finance._id(int(fields['account_id']) if isinstance(fields['account_id'],str) else fields['account_id'])
        requested_account=next((a for a in all_accounts if a['id']==account_id),None)
        if not requested_account:raise ValueError('reference_unavailable')
    currency=finance._currency(fields.get('currency') or (requested_account['currency'] if requested_account else 'IDR'))
    accounts=[a for a in all_accounts if a['currency']==currency]
    account=requested_account if requested_account and requested_account['currency']==currency else None
    if fields.get('account_id') not in (None,'') and account is None:
        raise ValueError('reference_unavailable')
    if account is None and accounts:
        # Tagihan is a commitment, not a cash movement. Keep one compatible account only
        # as an internal schema placeholder; the real account is selected when marking paid.
        account=accounts[0]
    category_id=finance._id(int(fields['category_id']) if isinstance(fields['category_id'],str) else fields['category_id'])
    categories=finance.list_categories(business_id,'EXPENSE',include_children=True,actor_user_id=user_id)
    category=next((c for c in categories if c['id']==category_id),None)
    if not account or not category:raise ValueError('reference_unavailable')
    account_id=account['id']

    project_id=None
    project=None
    if fields['project_id'] not in (None,''):
        project_id=finance._id(int(fields['project_id']) if isinstance(fields['project_id'],str) else fields['project_id'])
        project=next((p for p in finance.list_finance_projects(business_id,actor_user_id=user_id) if p['id']==project_id),None)
        if not project:raise ValueError('reference_unavailable')
    counterparty_name=finance._text(fields['counterparty_name'],160)
    description=finance._text(fields['description'],4000)

    if currency=='IDR':amount=operator.rupiah(fields['amount_text'])
    else:
        from routes_finance import currency_amount
        raw=operator.text(fields['amount_text'],60)
        match=re.fullmatch(r'(?:'+currency+r'\s+)?([0-9]+(?:[.,][0-9]{1,2})?)(?:\s+'+currency+r')?',raw,re.I)
        if not match:raise ValueError('invalid_amount')
        amount=currency_amount(match[1],currency)

    values=dict(name=name,amount_minor=amount,account_id=account_id,category_id=category_id,
                cadence=cadence,next_due_on=start,end_on=end,project_id=project_id,
                counterparty_name=counterparty_name,description=description,expected_currency=currency)
    cadence_label='Sekali' if requested_cadence=='ONCE' else ('Bulanan' if requested_cadence=='MONTHLY' else 'Mingguan')
    preview=[
        ['Nama Tagihan',name],['Mata uang',currency],
        ['Nominal',finance_fx.format_money(amount,currency)],['Kategori',category['name']],
        ['Jatuh Tempo',start],['Frekuensi',cadence_label],
        ['Berakhir','—' if requested_cadence=='ONCE' else (end or 'Sampai dinonaktifkan')],
        ['Penerima / Vendor',counterparty_name or '—'],
        ['Proyek',project['title'] if project else '—'],
        ['Detail',description or '—']
    ]
    return values,preview


def prepare(business_id,user_id,fields):
    draft_signer=signer()
    fields=normalize_fields(fields)
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
    values,_=validate(business_id,user_id,data['fields'])
    if values['expected_currency']!=data['currency']:raise ValueError('currency_changed')
    record_id=finance.create_recurring_expense(business_id,**values,actor_user_id=user_id,
        idempotency_key=hashlib.sha256(data['nonce'].encode()).hexdigest())
    return dict(record_id=record_id,message='Tagihan tersimpan. Belum ada pengeluaran dicatat. Tandai tagihan sebagai dibayar saat pembayarannya benar-benar dilakukan.')
