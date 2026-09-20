"""Conversational invoice adapter over the existing invoice service."""
import re
import uuid
from datetime import date
import finance_service as f
import finance_fx as fx


def start(b,u,text):
    import finance_assistant_flow as flow
    customers=flow.exact_matches(f.list_customers(b,actor_user_id=u),text)
    amounts=list(flow.AMOUNT.finditer(text)) or list(flow.BARE_AMOUNT.finditer(text))
    if len(amounts)>1:return dict(kind='clarification',message='Sebut satu item dan harga terlebih dahulu agar invoice tidak salah.')
    amount=amounts[0][0] if amounts else ''
    label=re.sub(r'^.*?\binvoice\s*','',text,flags=re.I)
    if len(customers)==1:label=re.sub(re.escape(customers[0]['name']),'',label,count=1,flags=re.I)
    if amount:label=label.split(amount)[0]
    label=re.split(r'jatuh tempo',label,flags=re.I)[0].strip(' ,')
    due=re.search(r'jatuh tempo\s+(.+)',text,re.I)
    values=dict(customer_id=str(customers[0]['id']) if len(customers)==1 else '',
                issue_date=date.today().isoformat(),due_date=flow.proposed_date(due[1],True) if due else '',
                currency=flow.currency_hint(text) or '',item_description=label,quantity='1',amount=amount,notes='')
    # Rupiah wording is evidence; bare amounts with multiple native currencies need a question.
    if not values['currency']:
        codes={a['currency'] for a in f.list_accounts(b,actor_user_id=u)}
        if len(codes)==1:values['currency']=codes.pop()
    return review_invoice(b,u,dict(action='invoice',nonce=uuid.uuid4().hex,values=values))


def invoice_data(b,u,values):
    import finance_assistant_flow as flow
    customer=f.get_customer(b,int(values['customer_id']),u)
    if not customer or not customer['is_active']:raise ValueError('customer_unavailable')
    issue,due=f._period(values['issue_date'],values['due_date'])
    if issue>date.today().isoformat():raise ValueError('future_date')
    currency=f._currency(values['currency'])
    quantity=f._money(int(values['quantity']),positive=True)
    price=f._money(flow.minor(values['amount'],currency),positive=True)
    f._money(quantity*price)
    return dict(customer_id=customer['id'],issue_date=issue,due_date=due,currency=currency,
                items=[dict(description=f._text(values['item_description'],500,True),quantity=quantity,unit_price_minor=price)],
                notes=f._text(values['notes'],4000))


def issue_fingerprint(b,u,invoice):
    return f.invoice_fingerprint(b,invoice,u)


def review_invoice(b,u,context,edits=None):
    import finance_assistant_flow as flow
    flow.authorize(b,u,'OPERATOR')
    if context['action']=='issue_invoice':
        invoice=f.get_finance_invoice(b,context['values']['invoice_id'],u)
        if not invoice or invoice['status'] not in ('DRAFT','ISSUED'):raise ValueError('invoice_unavailable')
        if context['values'].get('fingerprint') != issue_fingerprint(b,u,invoice):raise ValueError('invalid_draft')
        totals=f.get_invoice_totals(b,invoice['id'],u)
        return dict(kind='review',state='READY_FOR_CONFIRMATION',ready=True,title='Terbitkan invoice',
                    message='Terbitkan invoice '+invoice['invoice_number']+'?',fields=[],
                    preview=[['Total',fx.format_money(totals['total_minor'],invoice['currency'])]],
                    context=flow.seal(b,u,'review',context),token=flow.seal(b,u,'confirm',context))
    values=context['values'].copy()
    if edits is not None:
        if set(edits)!=set(values) or any(not isinstance(v,str) or len(v)>4000 for v in edits.values()):raise ValueError('invalid_fields')
        values=edits.copy()
    customers=f.list_customers(b,actor_user_id=u)
    if values['customer_id'] and not any(str(c['id'])==values['customer_id'] for c in customers):raise ValueError('customer_unavailable')
    labels={'customer_id':'Customer','issue_date':'Tanggal terbit','due_date':'Jatuh tempo','currency':'Mata uang',
            'item_description':'Item','quantity':'Qty','amount':'Harga satuan','notes':'Catatan'}
    fields=[]
    for key,value in values.items():
        options=flow.pick_options(customers) if key=='customer_id' else [dict(value=c,label=c) for c in f.SUPPORTED_CURRENCIES] if key=='currency' else None
        fields.append(flow.field(key,labels[key],value,options,kind='date' if key.endswith('_date') else 'text',required=key!='notes'))
    missing=next((v for v in fields if v['required'] and not v['value']),None)
    context=dict(context,values=values)
    result=dict(kind='review',title='Draft invoice',ready=False,fields=fields,preview=[],
                message='Lengkapi '+missing['label'].lower()+'.' if missing else 'Buat invoice ini sebagai draft? Balas “oke”.',
                state='NEEDS_INFORMATION' if missing else 'READY_FOR_CONFIRMATION',context=flow.seal(b,u,'review',context))
    if not missing:
        data=invoice_data(b,u,values);item=data['items'][0]
        customer=next(c for c in customers if c['id']==data['customer_id'])
        result.update(ready=True,token=flow.seal(b,u,'confirm',context),preview=[['Customer',customer['name']],
            ['Item',item['description']],['Qty',str(item['quantity'])],['Harga',fx.format_money(item['unit_price_minor'],data['currency'])],
            ['Total',fx.format_money(item['quantity']*item['unit_price_minor'],data['currency'])],
            ['Tanggal terbit',data['issue_date']],['Jatuh tempo',data['due_date']],['Catatan',data['notes'] or '—']])
    return result


def issue_start(b,u,text):
    import finance_assistant_flow as flow
    rows=f.list_finance_invoices(b,actor_user_id=u)
    matches=flow.exact_matches(rows,text,'invoice_number')
    if len(matches)!=1:return dict(kind='clarification',message='Invoice mana yang mau diterbitkan? Sebut nomor invoice lengkap.')
    return review_invoice(b,u,dict(action='issue_invoice',values={'invoice_id':matches[0]['id'],'fingerprint':issue_fingerprint(b,u,matches[0])},nonce=uuid.uuid4().hex))


def confirm_invoice(b,u,context):
    if context['action']=='issue_invoice':
        f.issue_finance_invoice(b,context['values']['invoice_id'],u,idempotency_key=context['nonce'],expected_fingerprint=context['values']['fingerprint'])
        row=f.get_finance_invoice(b,context['values']['invoice_id'],u)
        return dict(record_id=row['id'],message='✅ Invoice '+row['invoice_number']+' berhasil diterbitkan.')
    data=invoice_data(b,u,context['values'])
    ident=f.create_finance_invoice(b,**data,actor_user_id=u,idempotency_key=context['nonce'])
    invoice=f.get_finance_invoice(b,ident,u)
    return dict(record_id=ident,message='✅ Invoice '+invoice['invoice_number']+' berhasil dibuat sebagai draft. Mau diterbitkan? Ketik “terbitkan '+invoice['invoice_number']+'” untuk meninjau penerbitan.')
