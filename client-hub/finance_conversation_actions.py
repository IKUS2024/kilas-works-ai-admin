"""Reviewed adapters for the existing manual Finance operations.

No new financial storage: the existing business lock, services and audit log
provide atomic idempotency. Every command is revalidated after confirmation.
"""
import hashlib
import json
import re
import uuid
from datetime import date
import db
import repo
import finance_service as f
import finance_branches as branches
import finance_fx as fx
from finance_semantics import entity_options

TITLES={'create_account':'Rekening baru','create_category':'Kategori baru','create_branch':'Cabang baru',
        'rename_account':'Ubah nama rekening','rename_category':'Ubah nama kategori','rename_branch':'Ubah nama cabang',
        'edit_customer':'Ubah customer','deactivate_customer':'Hapus customer',
        'deactivate_account':'Nonaktifkan rekening','deactivate_category':'Nonaktifkan kategori','deactivate_branch':'Nonaktifkan cabang',
        'deactivate_recurring':'Hentikan biaya rutin','post_recurring':'Catat biaya rutin jatuh tempo',
        'void_transaction':'Batalkan transaksi','edit_transaction':'Koreksi transaksi',
        'void_invoice':'Batalkan invoice','void_fx':'Batalkan penukaran mata uang','exchange':'Catat penukaran mata uang'}
LABELS={'name':'Nama','phone':'Nomor telepon','email':'Email','notes':'Catatan customer',
        'account_type':'Jenis rekening','currency':'Mata uang','opening_balance':'Saldo awal',
        'direction':'Jenis','from_account_id':'Rekening asal','to_account_id':'Rekening tujuan',
        'from_amount':'Nominal keluar','to_amount':'Nominal diterima','date':'Tanggal','note':'Catatan',
        'amount':'Nominal','account_id':'Kas / Rekening','category_id':'Kategori','description':'Catatan',
        'project_id':'Proyek','customer_id':'Pelanggan','counterparty_name':'Pihak terkait'}
OPTIONAL={'note','description','project_id','customer_id','counterparty_name','phone','email','notes'}
REFS={'account_id':'account','from_account_id':'account','to_account_id':'account','category_id':'category','project_id':'project','customer_id':'customer'}


def fingerprint(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()


def targets(b,u,kind):
    if kind=='account':return f.list_accounts(b,actor_user_id=u)
    if kind=='category':return f.list_categories(b,actor_user_id=u)
    if kind=='customer':return f.list_customers(b,actor_user_id=u)
    if kind=='branch':return branches.list_branches(b,u)
    if kind=='recurring':return f.list_recurring_expenses(b,actor_user_id=u)
    if kind=='invoice':return [dict(r,name=r['invoice_number']) for r in f.list_finance_invoices(b,actor_user_id=u)]
    if kind=='transaction':return [dict(r,name='Transaksi '+str(r['id'])) for r in f.list_transactions(b,actor_user_id=u)]
    if kind=='fx':return [dict(r,name='FX '+str(r['id'])) for r in f.list_currency_exchanges(b,actor_user_id=u)]
    raise ValueError('invalid_draft')


def target(b,u,context):
    kind=context['operation'].split('_',1)[1]
    row=get_target(b,u,kind,context['target_id'])
    if not row or fingerprint(row)!=context['snapshot']:raise ValueError('invalid_draft')
    return row


def get_target(b,u,kind,ident):
    if kind=='transaction':
        row=f.get_transaction(b,ident,actor_user_id=u)
        if row:row=dict(row,name='Transaksi '+str(row['id']))
        return row
    return next((r for r in targets(b,u,kind) if r['id']==ident),None)


def start(b,u,operation,values=None,row=None):
    if operation not in TITLES:raise ValueError('invalid_draft')
    v=dict(values or {})
    if operation=='create_account':v={'name':'','account_type':'','currency':'','opening_balance':'0',**v}
    elif operation=='create_category':v={'name':'','direction':'',**v}
    elif operation in ('create_branch','rename_account','rename_category','rename_branch'):v={'name':'',**v}
    elif operation=='edit_customer':
        if not row:raise ValueError('invalid_draft')
        v={'name':row['name'],'phone':row['phone'] or '','email':row['email'] or '','notes':row['notes'] or '',**v}
    elif operation=='exchange':v={'from_account_id':'','to_account_id':'','from_amount':'','to_amount':'','date':f.business_today(b).isoformat(),'note':'',**v}
    elif operation=='edit_transaction':
        v={'direction':row['direction'],'amount':str(fx.major(row['amount_minor'],row['currency'])),'currency':row['currency'],
           'account_id':str(row['account_id']),'category_id':str(row['category_id']),'date':row['occurred_on'],
           'description':row['description'] or '', 'project_id':str(row['project_id'] or ''),
           'customer_id':str(row['customer_id'] or ''),'counterparty_name':row['counterparty_name'] or '',**v}
    context={'action':'command','operation':operation,'nonce':uuid.uuid4().hex,'values':v}
    if row:context.update(target_id=row['id'],snapshot=fingerprint(row))
    return review(b,u,context)


def options(b,u,key,values):
    if key=='currency':return [dict(value=c,label=c) for c in f.SUPPORTED_CURRENCIES]
    if key=='account_type':return [dict(value=k,label=v) for k,v in [('CASH','Tunai'),('BANK','Bank'),('EWALLET','Dompet digital'),('OTHER','Lainnya')]]
    if key=='direction':return [dict(value='INCOME',label='Pemasukan'),dict(value='EXPENSE',label='Pengeluaran')]
    kind=REFS.get(key)
    if kind=='account':rows=f.list_accounts(b,actor_user_id=u)
    elif kind=='category':rows=f.list_categories(b,values.get('direction'),actor_user_id=u)
    elif kind=='project':rows=f.list_finance_projects(b,actor_user_id=u)
    elif kind=='customer':rows=f.list_customers(b,actor_user_id=u)
    else:return None
    return [dict(value=str(r['id']),label=r.get('title') if kind=='project' else r['name']+(' · '+r['currency'] if kind=='account' else '')) for r in rows]


def prepared(b,u,c):
    from finance_assistant_flow import minor
    op=c['operation'];v=c['values'];row=target(b,u,c) if 'target_id' in c else None
    if op=='create_account':
        balance=0 if v['opening_balance']=='0' else minor(v['opening_balance'].lstrip('-'),v['currency'])*(-1 if v['opening_balance'].startswith('-') else 1)
        data=dict(name=f._text(v['name'],160,True),account_type=f._enum(v['account_type'],f.ACCOUNT_TYPES),currency=f._currency(v['currency']),opening_balance_minor=f._money(balance))
    elif op=='create_category':data=dict(name=f._text(v['name'],160,True),direction=f._enum(v['direction'],f.DIRECTIONS))
    elif op=='create_branch' or op.startswith('rename_'):data=dict(name=f._text(v['name'],160,True))
    elif op=='exchange':
        a=f.get_account(b,int(v['from_account_id']),actor_user_id=u,active=True);z=f.get_account(b,int(v['to_account_id']),actor_user_id=u,active=True)
        if a['currency']==z['currency'] or a['branch_id']!=z['branch_id']:raise ValueError('fx_same_currency')
        if c.get('account_currencies') and c['account_currencies']!={str(a['id']):a['currency'],str(z['id']):z['currency']}:raise ValueError('account_currency_mismatch')
        when=f._date(v['date'])
        if when>f.business_today(b).isoformat():raise ValueError('future_date')
        data=dict(from_account_id=a['id'],to_account_id=z['id'],from_amount_minor=minor(v['from_amount'],a['currency']),
                  to_amount_minor=minor(v['to_amount'],z['currency']),occurred_on=when,note=f._text(v['note'],500))
    elif op=='edit_transaction':
        data=dict(direction=v['direction'],amount_minor=minor(v['amount'],v['currency']),currency=v['currency'],account_id=int(v['account_id']),
                  category_id=int(v['category_id']),occurred_on=v['date'],description=v['description'],project_id=int(v['project_id']) if v['project_id'] else None,
                  customer_id=int(v['customer_id']) if v['customer_id'] else None,counterparty_name=v['counterparty_name'])
        if row['source_type'] in ('FINANCE_INVOICE_PAYMENT','FINANCE_RECURRING_EXPENSE') or row['status']!='POSTED':raise ValueError('managed_transaction')
        f._transaction_data(b,dict(data,source_type=row['source_type'],source_ref=row['source_ref']))
    elif op=='edit_customer':
        from finance_draft_fields import customer_values
        name,phone,email,notes=customer_values(dict(name=v['name'],phone=v['phone'],email=v['email'],notes=v['notes']))
        data=dict(name=name,phone=phone,email=email,notes=notes)
    elif op=='post_recurring':
        due=f.preview_due_recurring_expenses(b,f.business_today(b).isoformat(),u)
        found=next((r for r in due if r['id']==row['id'] and r['next_due_on']==row['next_due_on']),None)
        if not found:raise ValueError('recurring_unavailable')
        data={'selection':found['selection']}
    else:
        if op=='void_invoice' and (row['status'] not in ('DRAFT','ISSUED') or f.list_invoice_payments(b,row['id'],u)):raise ValueError('invoice_has_payments')
        if op=='void_transaction' and row['source_type']=='FINANCE_INVOICE_PAYMENT':raise ValueError('invoice_ledger_managed')
        data={}
    return data,row


def review(b,u,c,edits=None):
    import finance_assistant_flow as flow
    flow.authorize(b,u,'OPERATOR')
    if c.get('operation') not in TITLES:raise ValueError('invalid_draft')
    values=c['values'].copy()
    if edits is not None:
        if not isinstance(edits,dict) or set(edits)!=set(values) or any(not isinstance(v,str) or len(v)>4000 for v in edits.values()):raise ValueError('invalid_fields')
        values=edits.copy()
    c=dict(c,values=values);fields=[]
    if edits is not None:c.pop('account_currencies',None)
    if 'target_id' in c:target(b,u,c)
    for key,value in values.items():
        opts=options(b,u,key,values)
        if value and opts is not None and value not in {o['value'] for o in opts}:raise ValueError('reference_unavailable')
        fields.append(flow.field(key,LABELS[key],value,opts,kind='date' if key=='date' else 'text',required=key not in OPTIONAL))
    missing=next((r for r in fields if r['required'] and not r['value']),None)
    preview=[]
    if not missing:
        data,row=prepared(b,u,c)
        if c['operation']=='exchange':
            c['account_currencies']={values[key]:f.get_account(b,int(values[key]),actor_user_id=u,active=True)['currency'] for key in ('from_account_id','to_account_id')}
        if row:
            preview.append(['Data yang dipilih',row['name']])
            if 'amount_minor' in row:preview.append(['Nominal saat ini',fx.format_money(row['amount_minor'],row['currency'])])
            if 'occurred_on' in row:preview.append(['Tanggal',row['occurred_on']])
            if c['operation']=='post_recurring':preview.append(['Tanggal kejadian',row['next_due_on']])
        for field in fields:
            value=field['value'];opts=field.get('options',[])
            display=next((o['label'] for o in opts if o['value']==value),value)
            preview.append([field['label'],display or '—'])
        if c['operation']=='create_branch':preview.append(['Rekening awal','Kas · IDR · saldo awal Rp0'])
    ready=missing is None
    response=dict(kind='review',title=TITLES[c['operation']],ready=ready,fields=fields,preview=preview,
                  context=flow.seal(b,u,'review',c),state='READY_FOR_CONFIRMATION' if ready else 'NEEDS_INFORMATION',
                  message='Periksa perubahan ini. Balas “oke” untuk menyimpan, atau “batal”.' if ready else 'Berapa '+missing['label'].lower()+'?' if 'amount' in missing['key'] else 'Isi '+missing['label'].lower()+' dulu, ya.')
    if missing:response['next_field']=missing['key']
    if ready:response['token']=flow.seal(b,u,'confirm',c)
    if c['operation']=='exchange':response['hint']='Ini hanya mencatat penukaran yang sudah terjadi, tidak mengirim uang. FX bukan pendapatan atau pengeluaran operasional.'
    return response


def confirm(b,u,c):
    op=c['operation'];nonce=c['nonce']
    if op not in TITLES or not re.fullmatch('[a-f0-9]{32}',nonce):raise ValueError('invalid_draft')
    digest=fingerprint(c);prefix='command='+nonce+';'
    with f._write(b,u):
        old=db.query_one('SELECT detail FROM audit_log WHERE business_id=? AND actor_user_id=? AND action=? AND detail LIKE ?',
                         (b,u,'FINANCE_ASSISTANT_COMMAND_CONFIRMED',prefix+'%'))
        if old:
            saved=json.loads(old['detail'][len(prefix):])
            if saved['digest']!=digest:raise ValueError('command_key_conflict')
            ident=saved['id']
        else:
            data,row=prepared(b,u,c);ident=row['id'] if row else None
            if op=='create_account':ident=f.create_account(b,**data,actor_user_id=u)
            elif op=='create_category':ident=f.create_category(b,**data,actor_user_id=u)
            elif op=='create_branch':ident=branches.create_branch(b,**data,actor_user_id=u)
            elif op.startswith('rename_') or op in ('deactivate_account','deactivate_category','deactivate_branch'):
                branches.update_record(b,op.split('_')[1],ident,name=data.get('name'),deactivate=op.startswith('deactivate_'),actor_user_id=u)
            elif op=='edit_customer':ident=f.update_customer(b,ident,actor_user_id=u,**data)
            elif op=='deactivate_customer':ident=f.delete_customer(b,ident,actor_user_id=u)
            elif op=='deactivate_recurring':f.deactivate_recurring_expense(b,ident,u)
            elif op=='void_transaction':f.void_transaction(b,ident,u)
            elif op=='void_invoice':f.void_finance_invoice(b,ident,u)
            elif op=='void_fx':f.void_currency_exchange(b,ident,u)
            elif op=='edit_transaction':f.update_transaction(b,ident,actor_user_id=u,**data)
            elif op=='exchange':ident=f.record_currency_exchange(b,**data,actor_user_id=u)
            elif op=='post_recurring':
                posted=f.process_due_recurring_expenses(b,f.business_today(b).isoformat(),u,selected=[data['selection']])
                if posted['posted_count']!=1:raise ValueError('recurring_unavailable')
            else:raise ValueError('invalid_draft')
            repo.write_audit(u,b,'FINANCE_ASSISTANT_COMMAND_CONFIRMED',prefix+json.dumps({'digest':digest,'id':ident},sort_keys=True))
    return dict(record_id=ident,message='✅ '+TITLES[op]+' berhasil disimpan.'+(' Satu pengeluaran aktual dicatat sesuai tanggal jatuh tempo.' if op=='post_recurring' else ''))


def route(b,u,text,query_context='',classify_only=False):
    """Deterministic action selection; ambiguous references become signed questions."""
    import finance_assistant_flow as flow
    remembered=flow.unseal_query(b,u,query_context) if query_context else {}
    command=remembered.get('command');op=None;raw='';values={}
    if command:
        if re.fullmatch(r'batal|ga jadi|jangan',text,re.I):return dict(kind='answer',message='Oke, dibatalkan.')
        op=command['operation'];raw=text;values=command.get('values',{})
    else:
        last=remembered.get('last_record',{})
        reference=re.search(r'\b(?:yang tadi|transaksi tadi|itu)\b',text,re.I)
        if reference and last.get('kind')=='transaction' and re.search(r'\b(?:ubah|koreksi|masukin|masukkan|ganti|batalkan)\b',text,re.I):
            op='void_transaction' if re.search(r'\bbatalkan\b',text,re.I) else 'edit_transaction';raw='yang tadi'
        issue=re.search(r'\bterbitkan\s+(?:invoice\s+)?(.+)',text,re.I)
        if issue:op='issue_invoice';raw=issue[1]
        create=re.search(r'\b(?:buat|bikin|tambah(?:kan)?)\s+(rekening|akun|kategori|cabang)\s*(.*)',text,re.I)
        if create:
            kind={'rekening':'account','akun':'account','kategori':'category','cabang':'branch'}[create[1].lower()];op='create_'+kind
            name=create[2].strip();values={'name':name}
            if kind=='category':
                direction=next((k for k,pattern in [('INCOME','pemasukan|pendapatan'),('EXPENSE','pengeluaran|biaya')] if re.search(pattern,name,re.I)),None)
                if direction:values['direction']=direction;values['name']=re.sub(r'\b(pemasukan|pendapatan|pengeluaran|biaya)\b','',name,flags=re.I).strip()
            if kind=='account':
                code=flow.currency_hint(name)
                if code:values['currency']=code;name=re.sub(r'\b'+code+r'\b','',name,flags=re.I)
                opening=re.search(r'saldo awal\s+(.+)',name,re.I)
                if opening:values['opening_balance']=opening[1];name=name[:opening.start()]
                typ=re.search(r'\b(bank|cash|tunai|ewallet)\b',name,re.I)
                if typ:values['account_type']={'bank':'BANK','cash':'CASH','tunai':'CASH','ewallet':'EWALLET'}[typ[1].lower()];name=name[:typ.start()]+name[typ.end():]
                values['name']=name.strip()
        if not op:
            action=re.search(r'\b(nonaktifkan|hentikan|stop|hapus|delete|batalkan|void|koreksi|edit|ubah|ganti nama|bayar|posting|proses)\s+(?:biaya\s+)?(rutin|transaksi|invoice|rekening|akun|kategori|cabang|customer|pelanggan|fx)\s*(.*)',text,re.I)
            if action:
                verb,kind,raw=action.groups();kind={'rutin':'recurring','rekening':'account','akun':'account','kategori':'category','cabang':'branch','pelanggan':'customer','transaksi':'transaction'}.get(kind.lower(),kind.lower())
                verb=verb.lower()
                if verb in ('bayar','posting','proses') and kind=='recurring':op='post_recurring'
                elif verb in ('nonaktifkan','hentikan','stop','hapus','delete') and kind in ('recurring','account','category','branch','customer'):op='deactivate_'+kind
                elif verb in ('batalkan','void','hapus','delete') and kind in ('transaction','invoice','fx'):op='void_'+kind
                elif verb in ('ubah','koreksi','edit') and kind=='transaction':op='edit_transaction'
                elif verb in ('ubah','edit') and kind=='customer':op='edit_customer'
                elif verb in ('ubah','ganti nama') and kind in ('account','category','branch'):
                    op='rename_'+kind
                    pieces=re.split(r'\s+(?:jadi|menjadi)\s+',raw,maxsplit=1,flags=re.I);raw=pieces[0]
                    if len(pieces)==2:values['name']=pieces[1]
        if not op and re.search(r'\b(catat|tambah|buat)\b.*\b(fx|penukaran|konversi)\b|^tukar\b',text,re.I):op='exchange'
    if not op:return None
    if classify_only:return op
    try:flow.authorize(b,u,'OPERATOR')
    except f.FinanceError as exc:
        if str(exc) not in ('all_branches_read_only','branch_required'):raise
        return dict(kind='branch_choice',message='Perubahan ini untuk cabang mana?',text=text,branches=[dict(id=r['id'],name=r['name']) for r in branches.list_branches(b,u) if r['is_active']])
    if op.startswith('create_'):return start(b,u,op,values)
    if op=='exchange':
        accounts=f.list_accounts(b,actor_user_id=u)
        for key,pattern in [('from_account_id',r'\bdari\s+(.+?)(?=\s+(?:ke|jadi|menjadi|sebesar|tanggal)\b|$)'),('to_account_id',r'\bke\s+(.+?)(?=\s+(?:jadi|menjadi|sebesar|tanggal)\b|$)')]:
            matched=re.search(pattern,text,re.I)
            if matched:
                found=entity_options(accounts,matched[1].strip())
                if len(found)==1:values[key]=str(found[0]['id'])
        amounts=list(flow.AMOUNT.finditer(text))
        if len(amounts)==2:
            values['from_amount']=amounts[0][0];values['to_amount']=amounts[1][0]
        return start(b,u,op,values)
    kind=op.split('_',1)[1];rows=targets(b,u,kind)
    last=remembered.get('last_record',{})
    if re.search(r'\b(tadi|itu)\b',raw) and last.get('kind')==kind:
        row=get_target(b,u,kind,last['id']);found=[row] if row else []
    else:
        number=re.fullmatch(r'(?:transaksi\s+)?#?(\d+)',raw.strip(),re.I)
        if kind=='transaction' and number:
            row=get_target(b,u,kind,int(number[1]));found=[row] if row else []
        else:
            if kind=='fx' and re.fullmatch(r'#?\d+',raw.strip()):raw='FX '+raw.strip().lstrip('#')
            found=entity_options(rows,raw.strip())
    if len(found)!=1:
        choices=found or rows
        return dict(kind='clarification',message='Yang mana? Pilih data yang ingin diubah; belum ada perubahan.',
                    choices=[r['name'] for r in choices[:8]],preview=[[r['name'],r.get('next_due_on',r.get('occurred_on',''))] for r in choices[:8]],
                    query_context=flow.seal_query(b,u,{'command':{'operation':op,'values':values}}))
    if op=='issue_invoice':
        from finance_assistant_invoice import review_invoice,issue_fingerprint
        row=f.get_finance_invoice(b,found[0]['id'],u)
        return review_invoice(b,u,dict(action='issue_invoice',values={'invoice_id':row['id'],'fingerprint':issue_fingerprint(b,u,row)},nonce=uuid.uuid4().hex))
    if kind=='transaction':found[0]=get_target(b,u,kind,found[0]['id'])
    initial=start(b,u,op,values,found[0])
    if op=='edit_transaction':
        import finance_draft_interpreter as interpreter
        c=flow.unseal(b,u,initial['context'],'review')
        updates=interpreter.deterministic(text,c,initial['fields'])
        if updates:
            try:return review(b,u,c,interpreter.resolve(updates,c,initial['fields']))
            except ValueError:initial['message']='Data yang ingin diganti belum jelas. Sebut kolom dan nilainya; belum ada perubahan.'
    return initial
