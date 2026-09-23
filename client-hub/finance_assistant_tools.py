"""Thin chat adapters for existing invoice, recurring and budget services."""
import re
import finance_service as f
import finance_fx as fx
import finance_invoice_editor as editor

TITLES = {'edit_recurring':'Ubah biaya rutin', 'edit_invoice':'Ubah invoice',
          'set_budget':'Atur anggaran'}
LABELS = {'cadence':'Frekuensi', 'end_on':'Berakhir', 'month':'Bulan',
          'issue_date':'Tanggal terbit', 'due_date':'Jatuh tempo',
          'item_description':'Item', 'quantity':'Jumlah', 'amount':'Harga satuan'}


def initial(b, u, operation, row):
    if operation == 'set_budget':
        return dict(month='', category_id='', amount='', currency='')
    if operation == 'edit_recurring':
        return dict(name=row['name'], amount=str(fx.major(row['amount_minor'],row['currency'])),
                    currency=row['currency'], account_id=str(row['account_id']), category_id=str(row['category_id']),
                    cadence=row['cadence'], date=row['next_due_on'], end_on=row['end_on'] or '',
                    description=row['description'] or '', project_id=str(row['project_id'] or ''),
                    counterparty_name=row['counterparty_name'] or '')
    values={k:row[k] for k in ('issue_date','due_date','currency')}
    values.update(customer_id=str(row['customer_id']),notes=row['notes'] or '')
    for index,item in enumerate(f.list_invoice_items(b,row['id'],u),1):
        keys=('item_description','quantity','amount') if index==1 else tuple('item'+str(index)+'_'+k for k in ('description','quantity','amount'))
        values.update(zip(keys,(item['description'],str(item['quantity']),str(fx.major(item['unit_price_minor'],row['currency'])))))
    # Snapshot metadata stays with this invoice; editing never changes defaults.
    document=editor.snapshot(row,u)
    for group,keys in editor.GROUPS.items():
        for key in keys:
            if (group,key)==('sender','email'):continue
            values[group+'_'+key]=document[group][key]
    return values


def label(key):
    match=re.fullmatch(r'item(\d+)_(description|quantity|amount)',key)
    if match:return 'Item '+match[1]+' · '+{'description':'Deskripsi','quantity':'Jumlah','amount':'Harga satuan'}[match[2]]
    if '_' in key and key.split('_',1)[0] in editor.GROUPS:
        group,field=key.split('_',1)
        return {'sender':'Pengirim','recipient':'Penerima','payment':'Pembayaran'}[group]+' · '+{
            'name':'Nama','address':'Alamat','phone':'Telepon','email':'Email','tax_id':'NPWP',
            'website':'Website','pic':'Kontak','method':'Metode','bank':'Bank','account_number':'Nomor rekening',
            'account_holder':'Atas nama','instructions':'Petunjuk'}[field]
    return LABELS.get(key,key)


def optional(key):
    return key in ('end_on','notes') or any(key.startswith(group+'_') for group in editor.GROUPS)


def prepared(b,u,context,row):
    from finance_assistant_flow import minor
    v=context['values'];op=context['operation']
    if op=='set_budget':
        return dict(month=f._budget_month(v['month']),category_id=int(v['category_id']),
                    amount_minor=f._money(minor(v['amount'],v['currency']),positive=True),currency=f._currency(v['currency']))
    if op=='edit_recurring':
        if not row['is_active']:raise ValueError('recurring_unavailable')
        account=f.get_account(b,int(v['account_id']),actor_user_id=u,active=True)
        if not account or account['currency']!=v['currency']:raise ValueError('account_currency_mismatch')
        return dict(name=f._text(v['name'],160,True), amount_minor=minor(v['amount'],v['currency']),
                    account_id=int(v['account_id']),category_id=int(v['category_id']),
                    cadence=f._enum(v['cadence'],('WEEKLY','MONTHLY')), next_due_on=f._date(v['date']),
                    end_on=f._period(v['date'],v['end_on'])[1] if v['end_on'] else None,
                    description=v['description'],project_id=int(v['project_id']) if v['project_id'] else None,
                    counterparty_name=v['counterparty_name'],expected_currency=v['currency'])
    from finance_assistant_invoice import invoice_data
    data=invoice_data(b,u,v)
    if row['status']=='VOID':raise ValueError('invoice_unavailable')
    if row['status'] in ('PARTIALLY_PAID','PAID') or f.list_invoice_payments(b,row['id'],u):
        old=f.list_invoice_items(b,row['id'],u)
        if (any(data[k]!=row[k] for k in ('customer_id','issue_date','due_date','currency')) or
                [(i['quantity'],i['unit_price_minor']) for i in data['items']]!=[(i['quantity'],i['unit_price_minor']) for i in old]):
            raise ValueError('invoice_financial_locked')
    document=editor.snapshot(row,u)
    for group,keys in editor.GROUPS.items():
        for key in keys:
            if group+'_'+key in v:document[group][key]=v[group+'_'+key]
    if data['customer_id']!=row['customer_id']:
        customer=f.get_customer(b,data['customer_id'],u)
        before=editor.snapshot(row,u)['recipient']
        for key in ('name','phone','email'):
            if document['recipient'][key]==before[key]:document['recipient'][key]=customer.get(key) or ''
    return dict(data,document_data=editor.clean_document(document))


def execute(b,u,context,data,row):
    op=context['operation']
    if op=='set_budget':return f.set_monthly_budget(b,actor_user_id=u,**data)
    if op=='edit_recurring':return f.update_recurring_expense(b,row['id'],actor_user_id=u,**data)
    return editor.edit(b,row['id'],data,actor_user_id=u,expected_revision=row['revision'])
