"""Invoice settlement review using live open invoices and canonical posting."""
import db
import finance_service as f
import finance_fx as fx
import finance_conversation_live as live


def payment_key(context):
    # One conversation draft may post at most once, even across review revisions.
    return context.get('legacy_payment_key') or 'assistant_payment_'+context['nonce']


def review(b,u,context,edits=None):
    import finance_assistant_flow as flow
    flow.authorize(b,u,'OPERATOR')
    if context.get('service_token') and not context.get('invoice_state'):
        # Carry pre-release operator submissions into this adapter without a new key.
        from itsdangerous import BadData
        try:legacy=flow.operator.signer().loads(context['service_token'],max_age=flow.operator.TTL)
        except BadData:raise ValueError('invalid_draft') from None
        if legacy.get('business_id')!=b or legacy.get('user_id')!=u or legacy.get('action')!='record_invoice_payment':raise ValueError('invalid_draft')
        context=dict(context,legacy_payment_key='operator_'+legacy['nonce'])
        existing=db.query_one('SELECT invoice_id FROM finance_invoice_payments WHERE business_id=? AND idempotency_key=?',(b,payment_key(context)))
        if existing:
            invoice=f.get_finance_invoice(b,existing['invoice_id'],u)
            if not invoice:raise ValueError('invoice_unavailable')
            totals=f.get_invoice_totals(b,invoice['id'],u)
            return dict(kind='answer',message='Pembayaran dari review ini sudah tercatat. Sisa invoice '+invoice['invoice_number']+': '+fx.format_money(totals['outstanding_minor'],invoice['currency'])+'.')
    values=dict(context['values'])
    if edits is not None:
        if set(edits)!=set(values) or any(not isinstance(v,str) or len(v)>4000 for v in edits.values()):raise ValueError('invalid_fields')
        values=dict(edits)
        if values.get('amount')!=context['values'].get('amount'):context=dict(context,settle_full=False)
        if values.get('customer_id')!=context['values'].get('customer_id') and values.get('invoice_id')==context['values'].get('invoice_id'):values['invoice_id']=''
    values.setdefault('customer_id','')
    changed=live.refresh_values(b,u,values)
    context=dict(context,values=values)
    context.pop('service_token',None)
    if changed:context['awaiting']=changed[0]
    if context.get('awaiting') and values.get(context['awaiting']):context.pop('awaiting')
    if 'customer_id' in changed:
        values['invoice_id']='';context['awaiting']='customer_id'
    customers=f.list_customers(b,actor_user_id=u)
    invoices=live.open_invoices(b,u,int(values['customer_id']) if values['customer_id'] else None)
    invoice=next((r for r in invoices if str(r['id'])==values['invoice_id']),None)
    if values['invoice_id'] and not invoice:
        old=f.get_finance_invoice(b,int(values['invoice_id']),u)
        if old and not values['customer_id']:values['customer_id']=str(old['customer_id'])
        return live.no_receivable(b,u,int(values['customer_id']) if values['customer_id'] else None)
    if not invoices and values['customer_id']:return live.no_receivable(b,u,int(values['customer_id']))
    # A single global invoice is not evidence of the intended customer.
    if not invoice and values['customer_id'] and len(invoices)==1 and not context.get('awaiting'):
        invoice=invoices[0];values['invoice_id']=str(invoice['id'])
    if invoice:
        values['customer_id']=str(invoice['customer_id'])
        values['currency']=invoice['currency']
        if context.get('settle_full'):values['amount']=str(fx.major(invoice['outstanding_minor'],invoice['currency']))
    accounts=f.list_accounts(b,actor_user_id=u)
    if values['currency']:accounts=[r for r in accounts if r['currency']==values['currency']]
    if values['account_id'] and not any(str(r['id'])==values['account_id'] for r in accounts):
        values['account_id']='';changed.append('account_id')
    if not values['account_id'] and len(accounts)==1 and 'account_id' not in changed and context.get('awaiting')!='account_id':values['account_id']=str(accounts[0]['id'])
    categories=f.list_categories(b,'INCOME',actor_user_id=u)
    if values['category_id'] and not any(str(r['id'])==values['category_id'] for r in categories):values['category_id']=''
    if not values['category_id'] and len(categories)==1 and 'category_id' not in changed and context.get('awaiting')!='category_id':values['category_id']=str(categories[0]['id'])
    names={r['id']:r['name'] for r in customers}
    options=[dict(value=str(r['id']),label=r['invoice_number']+' · '+names[r['customer_id']]+' · sisa '+fx.format_money(r['outstanding_minor'],r['currency'])+' · '+r['due_date']) for r in invoices]
    fields=[flow.field('customer_id','Customer',values['customer_id'],flow.pick_options(customers),required=context.get('awaiting')=='customer_id'),
            flow.field('invoice_id','Invoice',values['invoice_id'],options),
            flow.field('amount','Nominal',values['amount']),flow.field('currency','Mata uang',values['currency'],required=False),
            flow.field('date','Tanggal pembayaran',values['date'],kind='date'),
            flow.field('account_id','Rekening penerima',values['account_id'],[dict(value=str(r['id']),label=r['name']+' · '+r['currency']) for r in accounts]),
            flow.field('category_id','Kategori pemasukan',values['category_id'],flow.pick_options(categories)),
            flow.field('description','Catatan',values['description'],required=False)]
    missing=next((x for x in fields if x['required'] and not x['value']),None)
    result=dict(kind='review',title='Pembayaran invoice',fields=fields,preview=[],ready=False,state='NEEDS_INFORMATION')
    if missing:
        result.update(next_field=missing['key'],message={'invoice_id':'Invoice mana yang dibayar? Pilih nomor invoice berikut.',
            'date':'Tanggal pembayarannya kapan?', 'account_id':'Pembayaran masuk ke rekening mana?',
            'amount':'Nominal pembayaran berapa?','customer_id':'Customer yang tadi tidak aktif. Pilih customer aktif.',
            'category_id':'Kategori pemasukan apa yang sesuai?'}[missing['key']])
        if missing['key']=='invoice_id':result['choices']=[o['label'] for o in options[:8]]
    else:
        amount=flow.minor(values['amount'],invoice['currency'])
        prepared=flow.operator.prepare_fields(b,u,'record_invoice_payment',dict(account_id=int(values['account_id']),category_id=int(values['category_id']),
            date=values['date'],invoice_id=invoice['id'],currency=invoice['currency'],amount_minor=amount,description=values['description']))
        context['invoice_state']=dict(fingerprint=f.invoice_fingerprint(b,invoice,u),outstanding=invoice['outstanding_minor'])
        result.update(ready=True,state='READY_FOR_CONFIRMATION',preview=prepared['preview']+[
            ['Sisa setelah pembayaran',fx.format_money(invoice['outstanding_minor']-amount,invoice['currency'])]],
            message='Catat '+('pelunasan' if context.get('settle_full') else 'pembayaran')+' invoice '+invoice['invoice_number']+' sebesar '+fx.format_money(amount,invoice['currency'])+'? Periksa rinciannya, lalu balas “oke”.')
        result['token']=flow.seal(b,u,'confirm',context)
    result['context']=flow.seal(b,u,'review',context)
    return result


def confirm(b,u,context):
    import finance_assistant_flow as flow
    values=context['values'];key=payment_key(context)
    with f._write(b,u):
        existing=db.query_one('SELECT id FROM finance_invoice_payments WHERE business_id=? AND idempotency_key=?',(b,key))
        invoice=f.get_finance_invoice(b,int(values['invoice_id']),u)
        if not invoice:raise ValueError('invoice_unavailable')
        if not existing:
            customer=f.get_customer(b,invoice['customer_id'],u)
            if not customer or not customer['is_active']:raise ValueError('customer_unavailable')
            if invoice['status'] not in ('ISSUED','PARTIALLY_PAID'):return live.no_receivable(b,u,invoice['customer_id'])
            totals=f.get_invoice_totals(b,invoice['id'],u)
            state=dict(fingerprint=f.invoice_fingerprint(b,invoice,u),outstanding=totals['outstanding_minor'])
            if state!=context.get('invoice_state'):
                if not context.get('settle_full') and flow.minor(values['amount'],values['currency'])>totals['outstanding_minor']:
                    context=dict(context,values=dict(values,amount=''))
                result=review(b,u,context)
                result['message']='Data invoice berubah sejak review. '+result['message']
                return result
        amount=flow.minor(values['amount'],values['currency'])
        ident=f.record_invoice_payment(b,invoice['id'],amount,values['date'],int(values['account_id']),int(values['category_id']),
            note=values['description'],actor_user_id=u,idempotency_key=key)
        totals=f.get_invoice_totals(b,invoice['id'],u)
    return dict(record_id=ident,invoice_id=invoice['id'],message='✅ Pembayaran '+fx.format_money(amount,values['currency'])+
        ' untuk invoice '+invoice['invoice_number']+' berhasil dicatat. Sisa tagihan: '+fx.format_money(totals['outstanding_minor'],values['currency'])+'.')
