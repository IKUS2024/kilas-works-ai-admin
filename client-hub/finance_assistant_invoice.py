"""Conversational invoice adapter over the existing invoice service."""
import re
import uuid
from datetime import date
import finance_service as f
import finance_fx as fx


def start(b,u,text):
    import finance_assistant_flow as flow
    from finance_assistant_queries import fuzzy_matches
    customers=fuzzy_matches(f.list_customers(b,actor_user_id=u),text)
    amounts=list(flow.AMOUNT.finditer(text)) or list(flow.BARE_AMOUNT.finditer(text))
    if len(amounts)>1:return dict(kind='clarification',message='Sebut satu item dan harga terlebih dahulu agar invoice tidak salah.')
    amount=amounts[0][0] if amounts else ''
    label=re.sub(r'^.*?\binvoice\s*','',text,flags=re.I)
    if len(customers)==1:label=re.sub(re.escape(customers[0]['name']),'',label,count=1,flags=re.I)
    if amount:label=label.split(amount)[0]
    label=re.split(r'jatuh tempo',label,flags=re.I)[0].strip(' ,')
    due=re.search(r'jatuh tempo\s+(.+)',text,re.I)
    values=dict(customer_id=str(customers[0]['id']) if len(customers)==1 else '',
                issue_date=f.business_today(b).isoformat(),due_date=flow.proposed_date(due[1],True) if due else '',
                currency=flow.currency_hint(text) or '',item_description=label,quantity='1',amount=amount,notes='')
    # Rupiah wording is evidence; bare amounts with multiple native currencies need a question.
    if not values['currency']:
        codes={a['currency'] for a in f.list_accounts(b,actor_user_id=u)}
        if len(codes)==1:values['currency']=codes.pop()
    return review_invoice(b,u,dict(action='invoice',nonce=uuid.uuid4().hex,values=values))


def requested_steps(context,issue=None,settlement=None):
    """Flags express requested operations, not claimed accounting state."""
    if issue or settlement:context['issue_after']=True
    if settlement:
        context['pay_after']=True
        for key in ('account_id','category_id','date'):context['values'].setdefault(key,'')


def payment_data(b,u,values):
    account=f.get_account(b,int(values['account_id']),actor_user_id=u,active=True)
    if account['currency']!=values['currency']:raise ValueError('account_currency_mismatch')
    category=next((r for r in f.list_categories(b,'INCOME',actor_user_id=u) if str(r['id'])==values['category_id']),None)
    if not category:raise ValueError('category_unavailable')
    when=f._date(values['date'])
    if when>f.business_today(b).isoformat():raise ValueError('future_date')
    return account,category,when


def invoice_data(b,u,values):
    import finance_assistant_flow as flow
    customer=f.get_customer(b,int(values['customer_id']),u)
    if not customer or not customer['is_active']:raise ValueError('customer_unavailable')
    issue,due=f._period(values['issue_date'],values['due_date'])
    if issue>f.business_today(b).isoformat():raise ValueError('future_date')
    currency=f._currency(values['currency'])
    items=[];total=0
    count=1+sum(1 for key in values if re.fullmatch(r'item\d+_description',key))
    if not 1<=count<=100:raise ValueError('invalid_items')
    for index in range(1,count+1):
        keys=('item_description','quantity','amount') if index==1 else tuple('item'+str(index)+'_'+k for k in ('description','quantity','amount'))
        if any(key not in values for key in keys):raise ValueError('invalid_items')
        quantity=f._money(int(values[keys[1]]),positive=True)
        price=0 if values[keys[2]].strip()=='0' else f._money(flow.minor(values[keys[2]],currency),positive=True)
        total=f._money(total+quantity*price)
        items.append(dict(description=f._text(values[keys[0]],500,True),quantity=quantity,unit_price_minor=price))
    return dict(customer_id=customer['id'],issue_date=issue,due_date=due,currency=currency,
                items=items,
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
        settle_after=bool(context.get('settle_after'))
        return dict(kind='review',state='READY_FOR_CONFIRMATION',ready=True,
                    title='Terbitkan + pelunasan' if settle_after else 'Terbitkan invoice',
                    message=('Terbitkan invoice '+invoice['invoice_number']+
                             ' lalu lanjutkan ke review pelunasan?' if settle_after else
                             'Terbitkan invoice '+invoice['invoice_number']+'?'),
                    fields=[],
                    preview=([['Tindakan','Terbitkan invoice → review pembayaran penuh']] if settle_after else [])+
                            [['Total',fx.format_money(totals['total_minor'],invoice['currency'])]],
                    context=flow.seal(b,u,'review',context),token=flow.seal(b,u,'confirm',context))
    values=context['values'].copy()
    if edits is not None:
        if set(edits)!=set(values) or any(not isinstance(v,str) or len(v)>4000 for v in edits.values()):raise ValueError('invalid_fields')
        values=edits.copy()
    from finance_conversation_live import refresh_values
    stale=refresh_values(b,u,values)
    if stale:context=dict(context,awaiting=stale[0])
    if context.get('awaiting') and values.get(context['awaiting']):
        context=dict(context);context.pop('awaiting')
    customers=f.list_customers(b,actor_user_id=u)
    accounts=f.list_accounts(b,actor_user_id=u)
    accounts=[r for r in accounts if r['currency']==values['currency']]
    categories=f.list_categories(b,'INCOME',actor_user_id=u)
    if context.get('pay_after'):
        if values['account_id'] and not any(str(r['id'])==values['account_id'] for r in accounts):
            values['account_id']='';stale.append('account_id')
        if not values['account_id'] and len(accounts)==1 and 'account_id' not in stale and context.get('awaiting')!='account_id':values['account_id']=str(accounts[0]['id'])
        if not values['category_id'] and len(categories)==1 and 'category_id' not in stale and context.get('awaiting')!='category_id':values['category_id']=str(categories[0]['id'])
    labels={'customer_id':'Customer','issue_date':'Tanggal terbit','due_date':'Jatuh tempo','currency':'Mata uang',
            'item_description':'Item','quantity':'Qty','amount':'Harga satuan','notes':'Catatan',
            'account_id':'Rekening penerima','category_id':'Kategori pemasukan','date':'Tanggal pembayaran'}
    fields=[]
    for key,value in values.items():
        options=flow.pick_options(customers) if key=='customer_id' else [dict(value=c,label=c) for c in f.SUPPORTED_CURRENCIES] if key=='currency' else None
        if key=='account_id':options=[dict(value=str(r['id']),label=r['name']+' · '+r['currency']) for r in accounts]
        if key=='category_id':options=flow.pick_options(categories)
        label=labels.get(key)
        if not label:
            item=re.fullmatch(r'item(\d+)_(description|quantity|amount)',key)
            if not item or not 2<=int(item[1])<=100:raise ValueError('invalid_fields')
            label='Item '+item[1]+' · '+{'description':'Deskripsi','quantity':'Qty','amount':'Harga satuan'}[item[2]]
        fields.append(flow.field(key,label,value,options,kind='date' if key.endswith('_date') or key=='date' else 'text',required=key!='notes'))
    order=['customer_id','item_description','amount','currency','due_date','issue_date','quantity']
    ordered=sorted(fields,key=lambda v:order.index(v['key']) if v['key'] in order else len(order))
    missing=next((v for v in ordered if v['required'] and not v['value']),None)
    context=dict(context,values=values)
    result=dict(kind='review',title='Draft invoice',ready=False,fields=fields,preview=[],
                message='Lengkapi '+missing['label'].lower()+'.' if missing else 'Buat invoice ini sebagai draft? Balas “oke”.',
                state='NEEDS_INFORMATION' if missing else 'READY_FOR_CONFIRMATION',context=flow.seal(b,u,'review',context))
    if missing:
        result['next_field']=missing['key']
        if missing['key']=='item_description':result['message']='Tagihan ini untuk apa?'
    if not missing:
        data=invoice_data(b,u,values);item=data['items'][0]
        customer=next(c for c in customers if c['id']==data['customer_id'])
        result.update(ready=True,token=flow.seal(b,u,'confirm',context),preview=[['Customer',customer['name']],
            ['Item',item['description']],['Qty',str(item['quantity'])],['Harga',fx.format_money(item['unit_price_minor'],data['currency'])],
            ['Total',fx.format_money(sum(i['quantity']*i['unit_price_minor'] for i in data['items']),data['currency'])],
            ['Tanggal terbit',data['issue_date']],['Jatuh tempo',data['due_date']],['Catatan',data['notes'] or '—']])
        for index,item in enumerate(data['items'][1:],2):
            result['preview'].insert(index+2,['Item '+str(index),item['description']+' · '+str(item['quantity'])+' × '+fx.format_money(item['unit_price_minor'],data['currency'])])
    if context.get('issue_after'):
        result['title']='Buat dan terbitkan invoice'+(' + catat pelunasan' if context.get('pay_after') else '')
        if result['ready']:
            total=sum(i['quantity']*i['unit_price_minor'] for i in data['items'])
            f._money(total,positive=True)
            steps='Buat draft → terbitkan invoice'
            if context.get('pay_after'):
                account,category,when=payment_data(b,u,values)
                steps+=' → catat pembayaran penuh'
                result['preview'] += [['Pembayaran',fx.format_money(total,data['currency'])],['Tanggal bayar',when],
                    ['Rekening penerima',account['name']],['Kategori pemasukan',category['name']],['Sisa setelah pembayaran',fx.format_money(0,data['currency'])]]
            result['preview'].insert(0,['Tindakan',steps])
            result['message']=steps+'. Periksa seluruh rincian, lalu balas “oke”.'
    if stale:result['message']='Pilihan sebelumnya sudah tidak aktif. '+result['message']
    return result


def add_item(b,u,context,message):
    """Append an explicitly requested line; each price/quantity stays reviewable."""
    import finance_assistant_flow as flow
    match=re.match(r'\s*(?:tambah(?:kan)?|add)\s+item\s+(.+)',message,re.I)
    if not match:return None
    count=2+sum(1 for k in context['values'] if re.fullmatch(r'item\d+_description',k))
    if count>100:raise ValueError('invalid_items')
    text=match[1];amounts=list(flow.AMOUNT.finditer(text)) or list(flow.BARE_AMOUNT.finditer(text))
    if len(amounts)!=1:return dict(review_invoice(b,u,context),message='Harga satuan item barunya berapa? Tulis “tambah item nama item 100 ribu qty 1”.')
    amount=amounts[0];qty=re.search(r'\b(?:qty|jumlah)\s+(\d+)\b',text,re.I)
    description=text[:amount.start()].strip(' ,')
    values=dict(context['values'],**{'item'+str(count)+'_description':description,'item'+str(count)+'_quantity':qty[1] if qty else '1','item'+str(count)+'_amount':amount[0]})
    return review_invoice(b,u,dict(context,values=values))


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
        if context.get('settle_after'):
            from finance_assistant_payment import review as payment_review
            payment_context=dict(action='record_invoice_payment',nonce=context['nonce'],settle_full=True,
                values=dict(invoice_id=str(row['id']),customer_id=str(row['customer_id']),amount='',currency=row['currency'],
                            date=f.business_today(b).isoformat(),account_id='',category_id='',description=''))
            if context.get('conversation'):payment_context['conversation']=context['conversation']
            result=payment_review(b,u,payment_context)
            result['message']='✅ Invoice '+row['invoice_number']+' sudah diterbitkan. '+result['message']
            return result
        return dict(record_id=row['id'],message='✅ Invoice '+row['invoice_number']+' berhasil diterbitkan.')
    # The existing Finance business lock makes the ordered services atomic.
    # Same nonce per service/audit namespace ensures transport retries never duplicate.
    with f._write(b,u):
        data=invoice_data(b,u,context['values'])
        payment=payment_data(b,u,context['values']) if context.get('pay_after') else None
        ident=f.create_finance_invoice(b,**data,actor_user_id=u,idempotency_key=context['nonce'])
        invoice=f.get_finance_invoice(b,ident,u)
        if context.get('issue_after'):
            if invoice['status']=='VOID':raise ValueError('invoice_unavailable')
            f.issue_finance_invoice(b,ident,u,idempotency_key=context['nonce'])
        if payment:
            account,category,when=payment
            total=sum(i['quantity']*i['unit_price_minor'] for i in data['items'])
            f.record_invoice_payment(b,ident,total,when,account['id'],category['id'],actor_user_id=u,
                idempotency_key='assistant_invoice_'+context['nonce'])
        invoice=f.get_finance_invoice(b,ident,u)
        if payment:
            message='✅ Invoice '+invoice['invoice_number']+' diterbitkan dan pembayaran dicatat. Status: '+invoice['status']+'. Sisa tagihan: '+fx.format_money(f.get_invoice_totals(b,ident,u)['outstanding_minor'],invoice['currency'])+'.'
        elif context.get('issue_after'):message='✅ Invoice '+invoice['invoice_number']+' berhasil diterbitkan.'
        else:message='✅ Invoice '+invoice['invoice_number']+' berhasil dibuat sebagai draft. Mau diterbitkan? Ketik “terbitkan '+invoice['invoice_number']+'” untuk meninjau penerbitan.'
    return dict(record_id=ident,message=message)
