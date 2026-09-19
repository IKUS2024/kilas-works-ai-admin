"""Assistant orchestration only: existing services own every financial write."""
import calendar
import hashlib
import re
import uuid
from datetime import date, timedelta

from flask import current_app, url_for
from itsdangerous import URLSafeTimedSerializer, BadData
import finance_service as f
import finance_operator as operator
import finance_assistant_recurring as recurring
import finance_receipts as receipts
import finance_branches as branches
import finance_entitlements as entitlement
import finance_analyst as analyst
import finance_fx as fx

TTL = 600
AMOUNT = re.compile(r'(?<![\w.,+−-])(?:Rp\.?\s*\d+(?:[.,]\d+)*\s*(?:ribu|rb|juta|jt)?|\d+(?:[.,]\d+)*\s*(?:ribu|rb|juta|jt)\b|(?:USD|IDR|SGD|MYR|EUR|GBP|AUD|JPY|CNY|HKD|THB)\s+\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*\s+(?:USD|IDR|SGD|MYR|EUR|GBP|AUD|JPY|CNY|HKD|THB)\b)', re.I)
BARE_AMOUNT = re.compile(r'(?<![\w.,+−-])\d{4,}(?![\w.,])')
LABELS = {'create_expense':'Pengeluaran','create_income':'Pemasukan','record_invoice_payment':'Pembayaran invoice',
          'customer':'Customer baru','recurring':'Biaya rutin','receipt':'Struk pengeluaran'}


def authorize(b, u, capability=None):
    f._scope(b, u)
    entitlement.require_ai(b, u, capability)
    branches.token_branch(b)


def signer():
    operator.signer()
    return URLSafeTimedSerializer(current_app.secret_key, salt='kilas-finance-assistant-flow-v1',
                                  signer_kwargs={'digest_method':hashlib.sha256})


def seal(b, u, purpose, data):
    return signer().dumps(dict(b=b,u=u,branch=branches.token_branch(b),purpose=purpose,data=data))


def unseal(b, u, token, purpose):
    if not isinstance(token,str) or len(token)>24000:raise ValueError('invalid_draft')
    try:data=signer().loads(token,max_age=TTL)
    except BadData:raise ValueError('invalid_draft') from None
    if (not isinstance(data,dict) or set(data)!={'b','u','branch','purpose','data'}
            or type(data['b']) is not int or type(data['u']) is not int
            or data['b']!=b or data['u']!=u or data['purpose']!=purpose):raise ValueError('invalid_draft')
    branches.check_token(b,data['branch'])
    return data['data']


def currency_hint(text):
    codes={c for c in f.SUPPORTED_CURRENCIES if re.search(r'\b'+c+r'\b',text,re.I)}
    if re.search(r'\bRp\.?\s*\d|\d\s*(rb|ribu|jt|juta)\b',text,re.I):codes.add('IDR')
    return next(iter(codes)) if len(codes)==1 else ''


def exact_matches(rows, text, key='name'):
    return [r for r in rows if re.search(r'(?<!\w)'+re.escape(r[key])+r'(?!\w)',text,re.I)]


def account_options(b,u,text='',currency=''):
    accounts=f.list_accounts(b,actor_user_id=u)
    if currency:accounts=[a for a in accounts if a['currency']==currency]
    named=exact_matches(accounts,text)
    selected=named[0] if len(named)==1 else (accounts[0] if len(accounts)==1 else None)
    return accounts,selected


def category_choice(categories,text):
    matches=exact_matches(categories,text)
    if len(matches)==1:return matches[0]['id']
    if not matches:
        groups=[('makan','makanan','minuman','konsumsi'),('bensin','bbm','transportasi','transport'),
                ('software','aplikasi','langganan'),('internet','telepon','komunikasi'),('sewa','rent')]
        for words in groups:
            if any(re.search(r'\b'+w+r'\b',text,re.I) for w in words):
                matches += [c for c in categories if any(re.search(r'\b'+w+r'\b',c['name'],re.I) for w in words)]
    ids={c['id'] for c in matches}
    if len(ids)==1:return next(iter(ids))
    return categories[0]['id'] if len(categories)==1 else ''


def proposed_date(text, scheduled=False):
    today=date.today()
    if re.search(r'\bkemarin\b',text,re.I):return (today-timedelta(days=1)).isoformat()
    iso=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text)
    if len(iso)==1:return f._date(iso[0])
    match=re.search(r'\btanggal\s+([0-9]{1,2})\b',text,re.I)
    if match:
        day=int(match[1]);year,month=today.year,today.month
        if scheduled and day<today.day:
            month=month%12+1;year+=month==1
        try:return date(year,month,day).isoformat()
        except ValueError:return ''
    if re.search(r'\b(hari ini|sekarang)\b',text,re.I):return today.isoformat()
    # Explicit but unsupported calendar wording is never silently changed to today.
    if scheduled or re.search(r'\b(tanggal|besok|lusa|januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)\b',text,re.I):return ''
    return today.isoformat()


def minor(amount,currency):
    if currency=='IDR':return operator.rupiah(re.sub(r'\s*IDR\s*','',amount,flags=re.I))
    from routes_finance import currency_amount
    raw=re.sub(r'\b'+re.escape(currency)+r'\b','',amount,flags=re.I).strip()
    if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?',raw):raise ValueError('invalid_amount')
    return currency_amount(raw,currency)


def field(key,label,value='',options=None,kind='text',required=True):
    result=dict(key=key,label=label,value='' if value is None else str(value),type=kind,required=required)
    if options is not None:result['options']=options;result['type']='select'
    return result


def pick_options(rows,label='name'):
    return [dict(value=str(r['id']),label=r[label]) for r in rows]


def answer(b,u,text):
    authorize(b,u,'ANALYST')
    today=date.today()
    if re.search(r'\bsaldo\b',text,re.I):
        rows=f.get_account_balance_report(b,today.isoformat(),u)
        named=exact_matches(rows,text)
        if named:rows=named
        return dict(kind='answer',title='Saldo akun',message='Saldo mencakup saldo awal dan transaksi tercatat. Mata uang ditampilkan terpisah.',
                    preview=[[r['name'],fx.format_money(r['balance_minor'],r['currency'])] for r in rows])
    if re.search(r'customer|pelanggan|siapa',text,re.I) and re.search(r'belum bayar|piutang|belum lunas',text,re.I):
        rows=[r for r in f.get_report_invoices(b,today.isoformat(),actor_user_id=u) if r['status'] in ('ISSUED','PARTIALLY_PAID') and r['outstanding_minor']>0]
        return dict(kind='answer',title='Customer belum lunas',message='Invoice terbuka pada cabang ini; maksimal 50 ditampilkan.',
                    preview=[[r['customer_name']+' · '+r['invoice_number'],fx.format_money(r['outstanding_minor'],r['currency'])] for r in rows[:50]])
    month=today.replace(day=1)
    if re.search(r'bulan lalu',text,re.I):month=(month-timedelta(days=1)).replace(day=1)
    scope='categories' if re.search(r'terbesar|kategori',text,re.I) else 'receivables' if 'piutang' in text.lower() else 'summary'
    context=analyst.build_context(b,u,month,scope)
    return dict(kind='answer',title='Ringkasan Finance',message=context['period_start']+' — '+context['period_end'],
                preview=[[r['label'],r['display']] for r in context['facts']])


def text_message(b,u,text):
    text=operator.text(text,2000)
    authorize(b,u)
    if re.search(r'\b(hapus|delete|transfer|kirim uang|bayarkan|ubah transaksi)\b',text,re.I):
        return dict(kind='clarification',message='Assistant ini menyiapkan catatan untuk review. Penghapusan, transfer dan perubahan transaksi belum didukung.')
    if re.search(r'\b(berapa|apa|siapa|laporan|analisis|ringkas|saldo)\b|\?',text,re.I):return answer(b,u,text)
    customer=re.search(r'\b(?:tambah(?:kan)?|masukin|buat)\s+(?:customer|pelanggan)\s+(.+)',text,re.I)
    if customer:
        raw=customer[1]
        parts=re.split(r'\s*,\s*|\s+(?=nomor\b|wa\b|whatsapp\b|telepon\b|email\b|catatan\b)',raw,flags=re.I)
        phone=re.search(r'(?:nomor|wa|whatsapp|telepon)\s*[:=]?\s*(\+?[0-9][0-9 -]{4,62})',raw,re.I)
        email=re.search(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',raw)
        notes=re.search(r'\bcatatan\s*[:=]?\s*(.+)',raw,re.I)
        return review(b,u,dict(action='customer',nonce=uuid.uuid4().hex,values=dict(name=parts[0].strip(),phone=phone[1].strip() if phone else '',email=email[0] if email else '',notes=notes[1] if notes else '')))
    if re.search(r'\b(buat|bikin)\s+invoice\b',text,re.I):
        return dict(kind='clarification',message='Pembuatan invoice tetap memakai editor invoice yang tersedia. Lengkapi customer, deskripsi item, jumlah, harga, mata uang, tanggal terbit dan jatuh tempo; invoice disimpan sebagai draft.',
                    review_url=url_for('finance.new_invoice',business_id=b))
    schedule=bool(re.search(r'\b(rutin|berulang|mingguan|bulanan|tiap|setiap)\b',text,re.I))
    action='recurring' if schedule else 'record_invoice_payment' if re.search(r'\binvoice\b',text,re.I) else 'create_income' if re.search(r'\b(pemasukan|pendapatan|penjualan|terima)\b',text,re.I) else 'create_expense' if re.search(r'\b(pengeluaran|makan|bensin|beli|bayar|catat|software|biaya|sewa)\b',text,re.I) else ''
    if not action:return dict(kind='clarification',message='Mau mencatat pemasukan, pengeluaran, customer, atau bertanya laporan? Tulis satu permintaan beserta nominal bila ada.')
    matches=list(AMOUNT.finditer(text))
    # Natural Indonesian chat often uses a plain rupiah-sized integer ("2200000")
    # without writing Rp/ribu/juta. Preserve that exact token instead of asking again.
    if not matches:matches=list(BARE_AMOUNT.finditer(text))
    if len(matches)>1:return dict(kind='clarification',message='Ada beberapa nominal. Kirim satu transaksi per pesan agar nominal, akun, dan kategori dapat direview dengan jelas.')
    amount=matches[0][0] if matches else ''
    description=text
    if matches:description=text[:matches[0].start()]+text[matches[0].end():]
    description=re.sub(r'\b(pengeluaran|pemasukan|catat(?:kan)?|tadi|beli|hari ini|kemarin)\b','',description,flags=re.I).strip(' ,.')[:500]
    values=dict(amount=amount,currency=currency_hint(text),date=proposed_date(text,scheduled=schedule),description=description or text[:500],account_id='',category_id='')
    if schedule:
        values.update(name=description[:160],cadence='WEEKLY' if re.search(r'minggu',text,re.I) else 'MONTHLY',end_on='')
    if action=='record_invoice_payment':values['invoice_id']=''
    return review(b,u,dict(action=action,text=text,nonce=uuid.uuid4().hex,values=values))


def review(b,u,context,edits=None):
    action=context['action'];authorize(b,u,None if action=='receipt' else 'OPERATOR')
    values=dict(context['values']);text=context.get('text','')
    if edits is not None:
        if not isinstance(edits,dict) or set(edits)!=set(values) or any(not isinstance(v,str) or len(v)>4000 for v in edits.values()):raise ValueError('invalid_fields')
        values=edits.copy()
    context=dict(context,values=values)
    form=[];preview=[];result=dict(kind='review',title=LABELS[action],message='Periksa usulan ini. Belum ada pencatatan.',ready=False)
    if action=='customer':
        limits={'name':160,'phone':64,'email':254,'notes':4000}
        labels={'name':'Nama','phone':'WhatsApp','email':'Email','notes':'Catatan'}
        for k in values:
            f._text(values[k],limits[k],k=='name')
            form.append(field(k,labels[k],values[k],required=k=='name'));preview.append([labels[k],values[k] or '—'])
        if values['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']):raise ValueError('invalid_email')
        result['ready']=bool(values['name'].strip())
        if result['ready']:result['token']=seal(b,u,'confirm',context)
    else:
        currency=values['currency']
        if currency and currency not in f.SUPPORTED_CURRENCIES:raise ValueError('currency')
        accounts,chosen=account_options(b,u,text,currency)
        if not values['account_id'] and chosen:values['account_id']=str(chosen['id'])
        account=next((a for a in accounts if str(a['id'])==values['account_id']),None)
        if values['account_id'] and not account:raise ValueError('account_unavailable')
        if not currency and account:currency=values['currency']=account['currency']
        direction='INCOME' if action in ('create_income','record_invoice_payment') else 'EXPENSE'
        categories=f.list_categories(b,direction,actor_user_id=u)
        if not values['category_id'] and edits is None:values['category_id']=str(category_choice(categories,text or values.get('description','')) or '')
        category=next((c for c in categories if str(c['id'])==values['category_id']),None)
        if values['category_id'] and not category:raise ValueError('category_unavailable')
        invoice=None
        if action=='record_invoice_payment':
            invoices=f.operator_invoice_choices(b,actor_user_id=u)
            # A sole invoice is not enough: its number must explicitly identify the request.
            named=exact_matches(invoices,text,'invoice_number')
            if not values['invoice_id'] and len(named)==1:values['invoice_id']=str(named[0]['id'])
            invoice=next((i for i in invoices if str(i['id'])==values['invoice_id']),None)
            if values['invoice_id'] and not invoice:raise ValueError('invoice_unavailable')
            form.append(field('invoice_id','Invoice',values['invoice_id'],pick_options(invoices,'invoice_number')))
        form.extend([field('amount','Nominal',values['amount']),field('currency','Mata uang',currency,[dict(value=c,label=c) for c in f.SUPPORTED_CURRENCIES]),
                     field('date','Jatuh tempo pertama' if action=='recurring' else 'Tanggal',values['date'],kind='date'),
                     field('account_id','Kas / Rekening',values['account_id'],[dict(value=str(a['id']),label=a['name']+' · '+a['currency']) for a in accounts]),
                     field('category_id','Kategori',values['category_id'],pick_options(categories)),field('description','Keterangan',values['description'])])
        if action=='recurring':form.extend([field('name','Nama jadwal',values['name']),field('cadence','Frekuensi',values['cadence'],[dict(value='MONTHLY',label='Bulanan'),dict(value='WEEKLY',label='Mingguan')]),field('end_on','Berakhir',values['end_on'],kind='date',required=False)])
        if action=='receipt':form.append(field('merchant_name','Merchant',values['merchant_name'],required=False))
        if not account:result['message']='Nominal sudah terbaca. Tinggal pilih kas / rekening yang dipakai.' if values['amount'] else 'Mau dicatat ke rekening mana? Pilih akun sesuai mata uang sumber.'
        elif not category:result['message']='Kategori belum pasti. Pilih kategori yang sesuai saat review.'
        elif not values['date']:result['message']='Tanggal belum jelas. Lengkapi tanggal pada review.'
        elif action=='record_invoice_payment' and not invoice:result['message']='Invoice belum teridentifikasi secara unik. Pilih invoice yang dibayar.'
        elif not values['amount']:result['message']='Nominal belum jelas. Lengkapi nominal pada review.'
        else:
            amount=minor(values['amount'],currency)
            f._date(values['date'])
            if action=='recurring':
                prepared=recurring.prepare(b,u,dict(name=values['name'],amount_text=values['amount'],cadence=values['cadence'],next_due_on=values['date'],end_on=values['end_on'] or None,account_id=account['id'],category_id=category['id']))
            elif action=='receipt':
                # Original receipt identity is retained in the existing signed extraction token.
                receipts.resolve_token(context['receipt_token'],b,u)
                f._transaction_data(b,dict(direction='EXPENSE',amount_minor=amount,currency=currency,occurred_on=values['date'],account_id=account['id'],category_id=category['id'],description=values['description'],counterparty_name=values['merchant_name'],project_id=None,customer_id=None,source_type='FINANCE_RECEIPT',source_ref=None))
                prepared=dict(preview=[['Merchant',values['merchant_name'] or '—'],['Nominal',fx.format_money(amount,currency)],['Tanggal',values['date']],['Akun',account['name']],['Kategori',category['name']],['Keterangan',values['description']]])
            else:
                prepared=operator.prepare_fields(b,u,action,dict(account_id=account['id'],category_id=category['id'],date=values['date'],invoice_id=invoice['id'] if invoice else None,currency=currency,amount_minor=amount,description=operator.text(values['description'],500)))
            preview=prepared['preview'];result['ready']=True
            result['token']=seal(b,u,'confirm',dict(context,service_token=prepared.get('token')))
    result.update(fields=form,preview=preview,context=seal(b,u,'review',context))
    return result


def revise(b,u,token,values):
    return review(b,u,unseal(b,u,token,'review'),values)


def confirm(b,u,token):
    context=unseal(b,u,token,'confirm');action=context['action']
    authorize(b,u,None if action=='receipt' else 'OPERATOR')
    values=context['values']
    if action in operator.ACTIONS:return operator.confirm(b,u,context['service_token'])
    if action=='recurring':return recurring.confirm(b,u,context['service_token'])
    if action=='customer':
        ident=f.create_customer(b,**values,actor_user_id=u,idempotency_key=context['nonce'])
        return dict(record_id=ident,message='Customer ditambahkan. Konfirmasi ulang tidak membuat duplikat.')
    if action=='receipt':
        amount=minor(values['amount'],values['currency'])
        ident=receipts.confirm(b,u,context['receipt_token'],dict(confirmed='yes',currency=values['currency'],amount=str(fx.major(amount,values['currency'])),occurred_on=values['date'],account_id=values['account_id'],category_id=values['category_id'],merchant_name=values['merchant_name'],description=values['description']))
        return dict(record_id=ident,message='Pengeluaran struk tercatat. Konfirmasi ulang tidak menambah catatan.')
    raise ValueError('invalid_draft')


def document(b,u,files,text,workflow,account_id=''):
    import finance_bank_service as bank
    import finance_bank_extract as extraction
    authorize(b,u)
    text=operator.text(text,2000,False)
    if workflow=='RECEIPT':
        if len(files)!=1:raise ValueError('source_count')
        result=receipts.analyze(b,u,*files[0])
        if result['duplicate']:return dict(kind='answer',title='Struk sudah tercatat',message='File yang sama sudah memiliki transaksi. Tidak ada pencatatan baru.')
        data=result['extraction']
        amount=str(fx.major(data['total_minor'],data['currency'])) if data['total_minor'] and data['currency'] else ''
        values=dict(amount=amount,currency=data['currency'] or '',date=data['transaction_date'] or '',description=data['description'] or data['merchant_name'] or '',
                    merchant_name=data['merchant_name'] or '',account_id='',category_id='')
        if data['suggested_category_name']:
            matches=[c for c in f.list_categories(b,'EXPENSE',actor_user_id=u) if c['name']==data['suggested_category_name']]
            if len(matches)==1:values['category_id']=str(matches[0]['id'])
        review_result=review(b,u,dict(action='receipt',text=text,values=values,receipt_token=result['token'],nonce=uuid.uuid4().hex))
        if result['fallback']:review_result['message']='Struk belum terbaca dengan yakin. Lengkapi data yang belum jelas sebelum review dan konfirmasi.'
        return review_result
    if workflow not in ('BANK_STATEMENT','HANDWRITTEN_NOTE'):raise ValueError('document_kind')
    accounts,chosen=account_options(b,u,text,currency_hint(text))
    if account_id:
        chosen=next((a for a in accounts if str(a['id'])==account_id),None)
        if not chosen:raise ValueError('account_unavailable')
    if not chosen:
        # Validate before asking, without processing the same source twice on a ready path.
        extraction.validate_sources(files)
        return dict(kind='document_account',title='Catatan keuangan' if workflow=='HANDWRITTEN_NOTE' else 'Mutasi bank',
                    workflow=workflow,message='Pilih rekening untuk melanjutkan. Gunakan mata uang yang sama dengan dokumen.',
                    fields=[field('account_id','Kas / Rekening','',[dict(value=str(a['id']),label=a['name']+' · '+a['currency']) for a in accounts])])
    ident,fallback=bank.analyze(b,chosen['id'],files,u,document_kind='notes' if workflow=='HANDWRITTEN_NOTE' else 'bank')
    rows=bank.get_rows(b,ident,u)
    attention=sum(bool(r['possible_overlap']) for r in rows)
    return dict(kind='document_result',title='Catatan keuangan' if workflow=='HANDWRITTEN_NOTE' else 'Mutasi bank',
                message=(str(len(rows))+' transaksi ditemukan; '+str(attention)+' kemungkinan duplikat. Semua baris perlu direview; belum ada pencatatan.' if rows else
                         'Mutasi/catatan belum terbaca dengan yakin. Lengkapi tanggal, nominal, dan arah transaksi di Review; belum ada pencatatan.'),
                review_url=url_for('finance.bank_detail',business_id=b,import_id=ident),count=len(rows),fallback=fallback)
