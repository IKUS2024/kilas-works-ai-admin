"""Assistant orchestration only: existing services own every financial write."""
import calendar
import hashlib
import re
import uuid
import requests
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
AMOUNT = re.compile(r'(?<![\w.,+−-])(?:Rp\.?\s*\d+(?:[.,]\d+)*\s*(?:ribu|rb|juta|jt)?|\d+(?:[.,]\d+)*\s*(?:ribu|rb|juta|jt)\b|(?:US\$|S\$|A\$|HK\$|€|£|¥|฿)\s*\d+(?:[.,]\d+)*|(?:USD|IDR|SGD|MYR|EUR|GBP|AUD|JPY|CNY|HKD|THB)\s+\d+(?:[.,]\d+)*|\d+(?:[.,]\d+)*\s+(?:USD|IDR|SGD|MYR|EUR|GBP|AUD|JPY|CNY|HKD|THB)\b)', re.I)
BARE_AMOUNT = re.compile(r'(?<![\w.,+−-])\d{4,}(?![\w.,])')
LABELS = {'create_expense':'Pengeluaran','create_income':'Pemasukan','record_invoice_payment':'Pembayaran invoice',
          'customer':'Customer baru','recurring':'Biaya rutin','invoice':'Draft invoice','issue_invoice':'Terbitkan invoice','receipt':'Struk pengeluaran'}


def authorize(b, u, capability=None, write=True):
    f._scope(b, u)
    entitlement.require_ai(b, u, capability)
    if write:branches.token_branch(b)


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


def seal_query(b,u,data):
    """Short-lived signed read context; supports a selected branch or Semua Cabang."""
    branches.validate(b,write=False)
    current=branches._current.get()
    branch=current[1] if current and current[0]==b else None
    return signer().dumps(dict(b=b,u=u,branch=branch,purpose='query',data=data))


def unseal_query(b,u,token):
    if not isinstance(token,str) or len(token)>12000:raise ValueError('invalid_draft')
    try:data=signer().loads(token,max_age=TTL)
    except BadData:raise ValueError('invalid_draft') from None
    current=branches._current.get();branch=current[1] if current and current[0]==b else None
    if (not isinstance(data,dict) or set(data)!={'b','u','branch','purpose','data'}
            or data['b']!=b or data['u']!=u or data['purpose']!='query' or data['branch']!=branch
            or not isinstance(data['data'],dict)):
        raise ValueError('invalid_draft')
    return data['data']


def currency_hint(text):
    codes={c for c in f.SUPPORTED_CURRENCIES if re.search(r'\b'+c+r'\b',text,re.I)}
    aliases={
        'IDR':r'\b(rupiah|rp)\b|Rp\.?\s*\d',
        'USD':r'\b(?:dolar|dollar)\s+(?:amerika|as|us)\b|\bus\$|\busd\b',
        'SGD':r'\b(?:dolar|dollar)\s+singapura\b|\bs\$|\bsgd\b',
        'MYR':r'\b(?:ringgit|myr|rm)\b',
        'EUR':r'\b(?:euro|eur)\b|€',
        'GBP':r'\b(?:pound|sterling|gbp)\b|£',
        'AUD':r'\b(?:dolar|dollar)\s+australia\b|\b(?:aud|a\$)\b',
        'JPY':r'\b(?:yen|jpy)\b|¥',
        'CNY':r'\b(?:yuan|renminbi|rmb|cny)\b',
        'HKD':r'\b(?:dolar|dollar)\s+hong\s*kong\b|\b(?:hkd|hk\$)\b',
        'THB':r'\b(?:baht|thb)\b|฿'}
    for code,pattern in aliases.items():
        if re.search(pattern,text,re.I):codes.add(code)
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
        # Specific shared words outrank generic direction words such as pendapatan.
        scores={c['id']:sum((1 if w in ('pendapatan','pengeluaran','penjualan') else 3)
                           for w in set(re.findall(r'[a-z]+',c['name'].lower()))
                           if len(w)>2 and re.search(r'\b'+re.escape(w)+r'\b',text,re.I)) for c in categories}
        highest=max(scores.values(),default=0)
        if highest:matches=[c for c in categories if scores[c['id']]==highest]
        if not matches:
            groups=[('makan','makanan','minuman','konsumsi'),('bensin','bbm','transportasi','transport'),
                    ('software','aplikasi','langganan','api','ai'),('internet','telepon','komunikasi'),('sewa','rent')]
            for words in groups:
                if any(re.search(r'\b'+w+r'\b',text,re.I) for w in words):
                    matches += [c for c in categories if any(re.search(r'\b'+w+r'\b',c['name'],re.I) for w in words)]
    ids={c['id'] for c in matches}
    if len(ids)==1:return next(iter(ids))
    return categories[0]['id'] if len(categories)==1 else ''


def proposed_date(text, scheduled=False, default_today=True):
    today=date.today()
    for source,target in [('yesterday','kemarin'),('today','hari ini'),('tomorrow','besok'),('last month','bulan lalu'),('next month','bulan depan')]:
        text=re.sub(r'\b'+source+r'\b',target,text,flags=re.I)
    if re.search(r'\bkemarin\b',text,re.I):return (today-timedelta(days=1)).isoformat()
    from finance_assistant_queries import MONTH_ALIAS_TO_NUMBER
    months=MONTH_ALIAS_TO_NUMBER
    calendar_date=re.search(r'\b(\d{1,2})\s+('+'|'.join(sorted(months,key=len,reverse=True))+r')(?:\s+(20\d{2}))?\b',text,re.I)
    if calendar_date:
        try:return date(int(calendar_date[3] or today.year),months[calendar_date[2].lower()],int(calendar_date[1])).isoformat()
        except ValueError:return ''
    iso=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text)
    if len(iso)==1:return f._date(iso[0])
    match=re.search(r'\btanggal\s+([0-9]{1,2})\b',text,re.I)
    if match:
        day=int(match[1]);year,month=today.year,today.month
        if re.search('bulan lalu|bulan sebelumnya',text,re.I):
            prior=today.replace(day=1)-timedelta(days=1);year,month=prior.year,prior.month
        elif re.search('bulan depan',text,re.I) or scheduled and day<today.day:
            month=month%12+1;year+=month==1
        try:return date(year,month,day).isoformat()
        except ValueError:return ''
    if re.search(r'\b(hari ini|sekarang)\b',text,re.I):return today.isoformat()
    if scheduled and re.fullmatch(r'(?:mulai\s+)?(?:besok|lusa)',text.strip(),re.I):return (today+timedelta(days=2 if 'lusa' in text.lower() else 1)).isoformat()
    # Explicit but unsupported calendar wording is never silently changed to today.
    if scheduled or not default_today or re.search(r'\b(tanggal|besok|lusa|bulan lalu|bulan depan|bulan ini)\b',text,re.I) or any(re.search(r'\b'+word+r'\b',text,re.I) for word in months):return ''
    return today.isoformat()


def minor(amount,currency):
    if currency=='IDR':return operator.rupiah(re.sub(r'\s*IDR\s*','',amount,flags=re.I))
    from routes_finance import currency_amount
    raw=re.sub(r'\b'+re.escape(currency)+r'\b','',amount,flags=re.I).strip()
    symbols={'USD':'US$','SGD':'S$','AUD':'A$','HKD':'HK$','EUR':'€','GBP':'£','JPY':'¥','THB':'฿'}
    if currency in symbols:raw=re.sub(re.escape(symbols[currency]),'',raw,flags=re.I).strip()
    if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?',raw):raise ValueError('invalid_amount')
    return currency_amount(raw,currency)


def field(key,label,value='',options=None,kind='text',required=True):
    result=dict(key=key,label=label,value='' if value is None else str(value),type=kind,required=required)
    if options is not None:result['options']=options;result['type']='select'
    return result


def pick_options(rows,label='name'):
    return [dict(value=str(r['id']),label=r[label]) for r in rows]


FINANCE_DOMAIN = re.compile(
    r'\b(finance|keuangan|akuntansi|transaksi|pemasukan|pendapatan|penjualan|pengeluaran|biaya|kas|cash|rekening|bank|'
    r'saldo|invoice|tagihan|piutang|utang|customer|pelanggan|kategori|proyek|struk|receipt|mutasi|rekonsiliasi|'
    r'belum bayar|belum lunas|overdue|outstanding|aging|reminder|laporan|arus kas|cash ?flow|laba|rugi|aset|liabilitas|modal|pajak|budget|anggaran|rutin|bulanan|mingguan)\b', re.I)
BANK_CHAT_LIMIT = 200


def accounting_help(text):
    lower=text.lower()
    topics=[
        (('arus kas','cash flow','cashflow'),'Arus kas menunjukkan uang yang benar-benar masuk dan keluar pada suatu periode. Di Kilas Finance, saldo awal dan penukaran mata uang dipisahkan dari pemasukan/pengeluaran.'),
        (('laba rugi','profit loss'),'Laba rugi akuntansi berbeda dari arus kas. Kilas Finance saat ini berfokus pada pencatatan kas, invoice, piutang, rekening, biaya rutin, dan laporan operasional.'),
        (('piutang',),'Piutang adalah tagihan kepada customer yang belum lunas. Kilas Finance bisa melacak invoice terbuka, pembayaran, dan keterlambatan.'),
        (('rekonsiliasi','mutasi bank'),'Rekonsiliasi mencocokkan mutasi bank dengan transaksi yang sudah tercatat agar tidak terjadi pencatatan ganda.'),
        (('saldo awal',),'Saldo awal adalah uang yang sudah ada di kas/rekening sebelum transaksi periode berjalan. Saldo awal bukan pemasukan.'),
        (('aset','liabilitas','utang'),'Aset adalah sumber daya yang dimiliki, sedangkan liabilitas/utang adalah kewajiban. Kilas Finance mencatat arus kas operasional dan tidak menggantikan pembukuan akuntansi penuh.'),
        (('invoice','tagihan'),'Invoice adalah tagihan ke customer. Pembayaran invoice dicatat sebagai penerimaan kas dan mengurangi sisa piutang.'),
        (('biaya rutin','rutin','bulanan','mingguan'),'Biaya rutin adalah pengeluaran berulang. Sebut nominal, frekuensi, rekening, kategori, dan tanggal mulai; Assistant akan menyiapkan jadwal untuk dikonfirmasi.'),
    ]
    for keys,message in topics:
        if any(key in lower for key in keys):return dict(kind='answer',title='Kilas Finance',message=message)
    return dict(kind='answer',title='Kilas Finance',message='Aku fokus khusus pada keuangan dan akuntansi di Kilas Finance: transaksi, kas/rekening, customer, invoice, piutang, biaya rutin, struk, mutasi bank, rekonsiliasi, dan laporan. Tanyakan salah satu hal itu ya.')


def _other_category(categories):
    matches=[c for c in categories if re.search(r'\b(lain|lainnya|other)\b',c['name'],re.I)]
    return matches[0]['id'] if len(matches)==1 else (categories[0]['id'] if len(categories)==1 else None)


def _bank_preview(row,currency):
    direction='Masuk' if row['direction']=='INCOME' else 'Keluar'
    label=row['occurred_on']+' · '+direction
    description=(row['description'] or 'Tanpa keterangan').strip()
    if len(description)>80:description=description[:77]+'…'
    return [label,fx.format_money(row['amount_minor'],currency)+' · '+description]


def _bank_confirm(b,u,context):
    import finance_bank_service as bank
    imp=bank.get_import(b,context['import_id'],u)
    if imp['status']=='CANCELLED':raise ValueError('invalid_draft')
    rows=bank.get_rows(b,imp['id'],u)
    if len(rows)>BANK_CHAT_LIMIT:raise ValueError('bank_chat_limit')
    if imp['status']=='REVIEW':
        bank.open_import(b,imp['id'],context['revision'],u)
        imp=bank.get_import(b,imp['id'],u)
    elif imp['status'] not in ('OPEN','COMPLETED'):
        raise ValueError('invalid_draft')
    candidates=bank.candidates(b,imp['id'],u) if imp['status']=='OPEN' else {}
    posted=held=already=0
    for row in bank.get_rows(b,imp['id'],u):
        if row['reconciliation_status']!='UNMATCHED':
            already+=1;continue
        if row['possible_overlap'] or row['needs_attention'] or candidates.get(row['id']):
            held+=1;continue
        categories=f.list_categories(b,row['direction'],actor_user_id=u)
        category_id=category_choice(categories,row['description'] or '') or _other_category(categories)
        if not category_id:
            held+=1;continue
        try:
            bank.decide(b,imp['id'],row['id'],'post',u,fields=dict(
                category_id=category_id,occurred_on=row['occurred_on'],
                description=row['description'] or 'Mutasi bank',counterparty_name=None))
            posted+=1
        except f.FinanceError as error:
            if str(error) in ('bank_decision_conflict','bank_origin_conflict','bank_transaction_already_linked'):
                held+=1;continue
            raise
    suffix=''
    if held:suffix=f' {held} transaksi saya tahan karena kemungkinan duplikat atau kategorinya belum cukup jelas; tidak saya catat otomatis.'
    if already:suffix+=f' {already} baris sudah pernah diproses sebelumnya.'
    dates=[row['occurred_on'] for row in rows if row.get('occurred_on')]
    date_note=''
    if dates:
        first_on,last_on=min(dates),max(dates)
        period_label=first_on if first_on==last_on else first_on+' s.d. '+last_on
        date_note=' Tanggal transaksi mengikuti mutasi ('+period_label+'), bukan tanggal file di-upload.'
    return dict(record_id=imp['id'],action='bank_import',
                message=f'Selesai. {posted} transaksi dari mutasi bank sudah masuk ke Kilas Finance.'+suffix+date_note,
                posted_count=posted,held_count=held,already_count=already)

def answer(b,u,text,query_context=''):
    authorize(b,u,'ANALYST',write=False)
    from finance_query_plan import plan,execute
    previous=unseal_query(b,u,query_context).get('plan',{}) if query_context else {}
    if not isinstance(previous,dict):raise ValueError('invalid_draft')
    current=plan(b,u,text,previous)
    result=execute(b,u,current)
    result['query_context']=seal_query(b,u,{'plan':current})
    return result


def message_intents(text):
    """Shared existing intent signals for new messages and interrupted drafts."""
    from finance_semantics import period_patch
    question_intent=bool(re.search(r'\b(berapa|apa|siapa|laporan|analisis|ringkas|saldo|cek|lihat|tampilkan|total|nama)\b|\?',text,re.I))
    explicit_write=bool(re.search(r'\b(tambah(?:in|kan)?|masukin|catat(?:kan)?|beli|bayar|lunas|lunasi|pelunasan|terima|dibayar|bayaran|buat|terbitkan)\b',text,re.I))
    amounts=[m for m in BARE_AMOUNT.finditer(text) if not (re.fullmatch(r'20\d{2}',m[0]) and period_patch(text))]
    if not explicit_write and not (AMOUNT.search(text) or amounts) and (period_patch(text) or re.search(r'\b(daftar|ada|status)\b',text,re.I)):
        question_intent=True
    schedule_hint=bool(re.search(r'\b(rutin|berulang|mingguan|bulanan|tiap|setiap|per bulan|per minggu)\b',text,re.I))
    if re.search(r'belum bayar|belum lunas',text,re.I):explicit_write=False;question_intent=True
    return question_intent,explicit_write,schedule_hint


def is_read_query(b,u,text,query_context=''):
    from finance_assistant_queries import looks_finance,is_contextual_followup
    from finance_semantics import period_patch
    question_intent,explicit_write,_=message_intents(text)
    if re.search(r'\b(reminder|cari (?:customer|custumer|costumer)|ada (?:customer|custumer|costumer)|nomor .* apa)\b',text,re.I):return True
    return question_intent and not explicit_write and (FINANCE_DOMAIN.search(text) or looks_finance(text,b,u) or
        (period_patch(text) and re.search(r'\b(bandingkan|bandingin|compare)\b',text,re.I)) or
        (query_context and is_contextual_followup(text)))


def text_message(b,u,text,query_context=''):
    text=operator.text(text,2000)
    from finance_assistant_queries import canonicalize,is_contextual_followup
    from finance_semantics import normalize,period_patch
    text=normalize(text)
    authorize(b,u,write=False)
    from finance_conversation_actions import route
    routed=route(b,u,text,query_context)
    if routed is not None:return routed
    if re.fullmatch(r'\s*(hai|halo|hi|pagi|siang|sore|malam)[!. ]*',text,re.I):
        return dict(kind='answer',title='Kilas Finance AI',message='Hai. Aku siap bantu urusan Finance: catat pemasukan/pengeluaran, customer, invoice & piutang, biaya rutin, laporan, struk, dan mutasi bank.')
    if re.search(r'\b(hapus|delete|transfer|kirim uang|bayarkan|ubah transaksi)\b',text,re.I):
        return dict(kind='answer',title='Kilas Finance',message='Untuk keamanan, aku tidak melakukan transfer uang atau menghapus transaksi lewat chat. Aku bisa membantu menyiapkan dan mencatat transaksi baru, lalu kamu konfirmasi sebelum disimpan.')
    if re.search(r'\b(apa itu|jelaskan|bedanya|beda apa|gimana cara)\b',text,re.I) and FINANCE_DOMAIN.search(text):
        return accounting_help(text)
    question_intent,explicit_write,schedule_hint=message_intents(text)
    if query_context:
        remembered=unseal_query(b,u,query_context)
        if remembered.get('plan',{}).get('awaiting'):return answer(b,u,text,query_context)
    from finance_assistant_queries import looks_finance
    if is_read_query(b,u,text,query_context):return answer(b,u,text,query_context)
    if explicit_write or schedule_hint or re.search(r'\b(pemasukan|pengeluaran)\b',text,re.I):
        try:branches.token_branch(b)
        except f.FinanceError as error:
            if str(error) not in ('all_branches_read_only','branch_required'):raise
            return dict(kind='branch_choice',message='Transaksi ini untuk cabang mana?',text=text,
                        branches=[dict(id=r['id'],name=r['name']) for r in branches.list_branches(b,u) if r['is_active']])
    customer=re.search(r'\b(?:tambah(?:kan)?|masukin|buat)\s+(?:customer|custumer|costumer|pelanggan)\s+(.+)',text,re.I)
    if customer:
        raw=customer[1].strip()
        parts=re.split(r'\s*,\s*|\s+(?=(?:nomor|no(?:mor)?(?:\s+hp)?|wa|whatsapp|whatsap|telepon)(?:nya)?\b|email(?:nya)?\b|catatan(?:nya)?\b)',raw,flags=re.I)
        name=re.sub(r'^(?:atas\s+nama|bernama|nama(?:nya)?(?:\s+adalah)?)\s+','',parts[0].strip(),flags=re.I)
        name=re.sub(r'\s+(?:ya|dong|weh)$','',name,flags=re.I).strip()
        phone=re.search(r'(?:nomor|no(?:mor)?(?:\s+hp)?|wa|whatsapp|whatsap|telepon)(?:nya)?\s*[:=]?\s*(\+?[0-9][0-9 -]{4,62})',raw,re.I)
        email=re.search(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',raw)
        notes=re.search(r'\bcatatan(?:nya)?\s*[:=]?\s*(.+)',raw,re.I)
        return review(b,u,dict(action='customer',nonce=uuid.uuid4().hex,values=dict(
            name=name,phone=phone[1].strip() if phone else '',email=email[0] if email else '',notes=notes[1] if notes else '')))
    if re.search(r'\b(buat|bikin|tambah)\s+invoice\b',text,re.I):
        from finance_assistant_invoice import start
        return start(b,u,text)
    if re.search(r'\bterbitkan\b',text,re.I):
        from finance_assistant_invoice import issue_start
        return issue_start(b,u,text)
    schedule=schedule_hint
    action='recurring' if schedule else 'record_invoice_payment' if re.search(r'\binvoice\b',text,re.I) else 'create_income' if re.search(r'\b(pemasukan|pendapatan|penjualan|terima|dibayar|bayaran)\b',text,re.I) else 'create_expense' if re.search(r'\b(pengeluaran|makan|bensin|beli|bayar|catat|software|biaya|sewa|belanja)\b',text,re.I) else ''
    if not action:
        if query_context and is_contextual_followup(text):return answer(b,u,text,query_context)
        if looks_finance(text,b,u) or AMOUNT.search(text):
            from finance_intent_interpreter import understand
            understood=understand(b,u,text)
            if understood is not None:return understood
        return accounting_help(text) if FINANCE_DOMAIN.search(text) else dict(kind='answer',title='Kilas Finance',message='Aku khusus membantu keuangan dan akuntansi di Kilas Finance. Aku tidak menjawab topik di luar itu. Kamu bisa minta catat transaksi, cek laporan, tambah customer, biaya rutin, scan struk, atau baca mutasi bank.')
    matches=list(AMOUNT.finditer(text))
    if not matches:matches=list(BARE_AMOUNT.finditer(text))
    if len(matches)>1:return dict(kind='clarification',message='Saya menemukan lebih dari satu nominal. Kirim satu transaksi per pesan supaya tidak salah pencatatan.')
    amount=matches[0][0] if matches else ''
    description=text
    if matches:description=text[:matches[0].start()]+text[matches[0].end():]
    description=re.sub(r'\b(pengeluaran|pemasukan|pendapatan|catat(?:kan)?|tambah(?:in|kan)?|tadi|beli|hari ini|kemarin|setiap bulan|tiap bulan|bulanan)\b','',description,flags=re.I).strip(' ,.')[:500]
    values=dict(amount=amount,currency=currency_hint(text),date=proposed_date(text,scheduled=schedule),
                description=description or text[:500],account_id='',category_id='')
    if action in ('create_income','create_expense'):
        values.update(project_id='',customer_id='',counterparty_name='')
    if schedule:
        cadence='WEEKLY' if re.search(r'\b(mingguan|tiap minggu|setiap minggu|per minggu)\b',text,re.I) else (
                'MONTHLY' if re.search(r'\b(bulanan|tiap bulan|setiap bulan|per bulan|tiap tanggal|setiap tanggal)\b',text,re.I) else '')
        recurring_name=description[:160]
        purpose=re.search(r'\buntuk\s+(.+?)(?=\s+(?:tanggal|mulai|pakai|rekening|kategori|tiap|setiap|per)\b|$)',text,re.I)
        if purpose:
            recurring_name=purpose[1].strip(' ,.')
        recurring_name=re.sub(r'^(?:rutin|biaya rutin)\s+','',recurring_name,flags=re.I).strip() or 'Biaya rutin'
        recurring_name=re.split(r'\b(?:tiap|setiap|per bulan|per minggu|mulai|tanggal)\b',recurring_name,flags=re.I)[0].strip() or recurring_name
        values.update(name=recurring_name[:160],cadence=cadence,
                      end_on='',project_id='',counterparty_name='')
    if action=='recurring':
        vendor=re.search(r'\bke\s+(.+?)(?=\s+(?:tanggal|pakai|kategori)\b|$)',text,re.I)
        if vendor:values['counterparty_name']=vendor[1].strip()
        label=re.search(r'\bbayar\s+(.+?)(?=\s+(?:Rp\.?\s*)?\d)',text,re.I)
        if label:values['name']=label[1].strip()
    if action=='record_invoice_payment':values['invoice_id']=''
    return review(b,u,dict(action=action,text=text,nonce=uuid.uuid4().hex,values=values))

def review(b,u,context,edits=None):
    if context['action']=='command':
        from finance_conversation_actions import review as command_review
        return command_review(b,u,context,edits)
    if context['action'] in ('invoice','issue_invoice'):
        from finance_assistant_invoice import review_invoice
        return review_invoice(b,u,context,edits)
    action=context['action'];authorize(b,u,None if action=='receipt' else 'OPERATOR')
    values=dict(context['values']);text=context.get('text','')
    if edits is not None:
        if not isinstance(edits,dict) or set(edits)!=set(values) or any(not isinstance(v,str) or len(v)>4000 for v in edits.values()):raise ValueError('invalid_fields')
        values=edits.copy()
    context=dict(context,values=values)
    form=[];preview=[];result=dict(kind='review',title=LABELS[action],message='Periksa usulan ini. Belum ada pencatatan.',ready=False)
    if action=='customer':
        from finance_draft_fields import CUSTOMER_LIMITS as limits, customer_values
        if values['name'].strip():customer_values(values)
        labels={'name':'Nama customer','phone':'Nomor telepon','email':'Email','notes':'Catatan'}
        for k in values:
            f._text(values[k],limits[k],k=='name' and bool(values[k].strip()))
            form.append(field(k,labels[k],values[k],required=k=='name'));preview.append([labels[k],values[k] or '—'])
        if values['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']):raise ValueError('invalid_email')
        result['ready']=bool(values['name'].strip())
        if result['ready']:result['token']=seal(b,u,'confirm',context)
    else:
        currency=values['currency']
        if currency and currency not in f.SUPPORTED_CURRENCIES:raise ValueError('currency')
        if action=='record_invoice_payment' and not values.get('invoice_id'):
            available=f.operator_invoice_choices(b,actor_user_id=u)
            matched=exact_matches(available,text,'invoice_number')
            if not matched and not re.search(r'KFIN-|INV-',text,re.I):
                names=exact_matches(f.list_customers(b,actor_user_id=u),text)
                if len(names)==1:
                    ids={r['id'] for r in f.list_finance_invoices(b,customer_id=names[0]['id'],actor_user_id=u)}
                    matched=[r for r in available if r['id'] in ids]
            if len(matched)==1:
                values['invoice_id']=str(matched[0]['id'])
                if not currency:currency=values['currency']=matched[0]['currency']
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
            named=exact_matches(invoices,text,'invoice_number')
            if not values['invoice_id'] and len(named)==1:values['invoice_id']=str(named[0]['id'])
            invoice=next((i for i in invoices if str(i['id'])==values['invoice_id']),None)
            if values['invoice_id'] and not invoice:raise ValueError('invoice_unavailable')
            if invoice and not values['amount'] and re.search(r'\b(lunas|lunasi|pelunasan)\b',text,re.I):
                remaining=f.get_invoice_totals(b,invoice['id'],u)['outstanding_minor']
                values['amount']=str(fx.major(remaining,invoice['currency']))
            form.append(field('invoice_id','Invoice',values['invoice_id'],pick_options(invoices,'invoice_number')))

        projects=f.list_finance_projects(b,actor_user_id=u) if action in ('create_income','create_expense','recurring') else []
        customers=f.list_customers(b,actor_user_id=u) if action in ('create_income','create_expense') else []
        project=None;customer=None
        if action in ('create_income','create_expense','recurring'):
            if not values.get('project_id') and edits is None:
                from finance_assistant_queries import fuzzy_matches
                named_projects=fuzzy_matches(projects,text,'title')
                if len(named_projects)==1:values['project_id']=str(named_projects[0]['id'])
                elif len(named_projects)>1:context['awaiting']='project_id'
            project=next((p for p in projects if str(p['id'])==values.get('project_id','')),None)
            if values.get('project_id') and not project:raise ValueError('project_unavailable')
        if action in ('create_income','create_expense'):
            if not values.get('customer_id') and edits is None:
                from finance_assistant_queries import fuzzy_matches
                named_customers=fuzzy_matches(customers,text)
                if len(named_customers)==1:values['customer_id']=str(named_customers[0]['id'])
                elif len(named_customers)>1:context['awaiting']='customer_id'
            customer=next((item for item in customers if str(item['id'])==values.get('customer_id','')),None)
            if values.get('customer_id') and not customer:raise ValueError('customer_unavailable')

        if action=='recurring':
            form.extend([
                field('name','Nama',values['name']),
                field('account_id','Kas / Rekening',values['account_id'],[dict(value=str(a['id']),label=a['name']+' · '+a['currency']) for a in accounts]),
                field('amount','Nominal',values['amount']),
                field('currency','Mata uang',currency,[dict(value=code,label=code) for code in f.SUPPORTED_CURRENCIES],required=False),
                field('category_id','Kategori pengeluaran',values['category_id'],pick_options(categories)),
                field('cadence','Frekuensi',values['cadence'],[dict(value='MONTHLY',label='Bulanan'),dict(value='WEEKLY',label='Mingguan')]),
                field('date','Jatuh tempo pertama',values['date'],kind='date'),
                field('end_on','Berakhir',values['end_on'],kind='date',required=False),
                field('project_id','Proyek',values.get('project_id',''),[dict(value=str(p['id']),label=p['title']) for p in projects],required=False),
                field('counterparty_name','Vendor / penerima',values.get('counterparty_name',''),required=False),
                field('description','Deskripsi',values['description'],required=False)
            ])
        else:
            form.extend([
                field('amount','Nominal',values['amount']),
                field('currency','Mata uang',currency,[dict(value=code,label=code) for code in f.SUPPORTED_CURRENCIES],required=False),
                field('date','Tanggal',values['date'],kind='date'),
                field('account_id','Kas / Rekening',values['account_id'],[dict(value=str(a['id']),label=a['name']+' · '+a['currency']) for a in accounts]),
                field('category_id','Kategori',values['category_id'],pick_options(categories)),
                field('description','Catatan',values['description'],required=False)
            ])
            if action in ('create_income','create_expense'):
                form.extend([
                    field('project_id','Proyek',values.get('project_id',''),[dict(value=str(p['id']),label=p['title']) for p in projects],required=False),
                    field('customer_id','Pelanggan',values.get('customer_id',''),[dict(value=str(item['id']),label=item['name']) for item in customers],required=False),
                    field('counterparty_name','Pihak terkait',values.get('counterparty_name',''),required=False)
                ])
            if action=='receipt':
                form.append(field('merchant_name','Merchant',values['merchant_name'],required=False))

        if not account:result['message']='Nominal sudah terbaca. Mau dicatat ke rekening mana?' if values['amount'] else 'Mau dicatat ke rekening mana? Pilih akun sesuai mata uang sumber.'
        elif not category:result['message']='Kategori belum pasti. Pilih kategori yang sesuai saat review.'
        elif action=='recurring' and not values.get('cadence'):
            result['message']='Biaya rutin ini mau berulang seberapa sering? Pilih Bulanan atau Mingguan.'
        elif not values['date']:
            result['message']='Mulai kapan biaya rutin ini berlaku? Tulis misalnya “hari ini”, “tanggal 25”, atau tanggal lengkap.'
        elif action=='record_invoice_payment' and not invoice:result['message']='Invoice belum teridentifikasi secara unik. Pilih invoice yang dibayar.'
        elif not values['amount']:result['message']='Nominal belum jelas. Lengkapi nominal pada review.'
        else:
            amount=minor(values['amount'],currency)
            f._date(values['date'])
            if action=='recurring':
                prepared=recurring.prepare(b,u,dict(name=values['name'],amount_text=values['amount'],cadence=values['cadence'],
                    next_due_on=values['date'],end_on=values['end_on'] or None,account_id=account['id'],category_id=category['id'],
                    project_id=values.get('project_id') or None,counterparty_name=values.get('counterparty_name') or None,
                    description=values.get('description') or None))
            elif action=='receipt':
                receipts.resolve_token(context['receipt_token'],b,u)
                f._transaction_data(b,dict(direction='EXPENSE',amount_minor=amount,currency=currency,occurred_on=values['date'],
                    account_id=account['id'],category_id=category['id'],description=values['description'],
                    counterparty_name=values['merchant_name'],project_id=None,customer_id=None,
                    source_type='FINANCE_RECEIPT',source_ref=None))
                prepared=dict(preview=[['Merchant',values['merchant_name'] or '—'],['Nominal',fx.format_money(amount,currency)],
                    ['Tanggal',values['date']],['Akun',account['name']],['Kategori',category['name']],
                    ['Catatan',values['description'] or '—']])
            else:
                prepared=operator.prepare_fields(b,u,action,dict(account_id=account['id'],category_id=category['id'],
                    date=values['date'],invoice_id=invoice['id'] if invoice else None,currency=currency,amount_minor=amount,
                    description=values['description'],project_id=int(values['project_id']) if values.get('project_id') else None,
                    customer_id=int(values['customer_id']) if values.get('customer_id') else None,
                    counterparty_name=values.get('counterparty_name') or None))
            preview=prepared['preview'];result['ready']=True
            result['token']=seal(b,u,'confirm',dict(context,service_token=prepared.get('token')))
    if result.get('ready'):
        result['message']='Oke, saya sudah rangkum '+LABELS[action].lower()+' ini. Kalau sudah benar, balas “oke”.'
        result['hint']='Kalau ada yang perlu diubah, cukup tulis di chat, misalnya “WhatsApp 0822…”, “pakai BCA”, “vendor Telkom”, atau “ubah jadi 300 ribu”. Ketik “batal” untuk membatalkan.'
    else:
        order=['cadence','date','account_id','category_id','amount','name'] if action=='recurring' else ['invoice_id','account_id','category_id','amount','date']
        missing=next((r for key in order for r in form if r['key']==key and r['required'] and not r['value']),None)
        if missing:
            result['next_field']=missing['key']
            questions={'cadence':'Biaya rutin ini mau berulang seberapa sering? Bulanan atau Mingguan?',
                       'date':'Mulai kapan biaya rutin ini berlaku?' if action=='recurring' else 'Tanggal transaksinya kapan?',
                       'account_id':result['message'] if 'rekening mana' in result['message'] else 'Mau dicatat ke rekening mana?',
                       'category_id':'Kategori apa yang sesuai?', 'amount':'Nominalnya berapa?',
                       'invoice_id':'Invoice mana yang dibayar?','name':'Nama biaya rutinnya apa?'}
            result['message']=questions[missing['key']]
    if context.get('awaiting'):
        if values.get(context['awaiting']):context.pop('awaiting')
        else:
            spec=next((r for r in form if r['key']==context['awaiting']),None)
            if spec:
                result.update(ready=False,next_field=spec['key'],message=spec['label']+' belum jelas. Pilih yang dimaksud.')
                result.pop('token',None);spec['required']=True
    result['state']='READY_FOR_CONFIRMATION' if result['ready'] else 'NEEDS_INFORMATION'
    result.update(fields=form,preview=preview,context=seal(b,u,'review',context))
    return result


def revise(b,u,token,values):
    return review(b,u,unseal(b,u,token,'review'),values)


def confirm(b,u,token):
    context=unseal(b,u,token,'confirm')
    result=_confirm(b,u,token)
    action=context['action']
    kind={'create_income':'transaction','create_expense':'transaction','invoice':'invoice','issue_invoice':'invoice',
          'recurring':'recurring','customer':'customer'}.get(action)
    if action=='command':kind=context['operation'].split('_',1)[-1] if context['operation']!='exchange' else 'fx'
    if kind and type(result.get('record_id')) is int:
        result['query_context']=seal_query(b,u,{'last_record':{'kind':kind,'id':result['record_id']}})
    return result


def _confirm(b,u,token):
    context=unseal(b,u,token,'confirm');action=context['action']
    authorize(b,u,None if action in ('receipt','bank_import') else 'OPERATOR')
    if action=='command':
        from finance_conversation_actions import confirm as command_confirm
        return command_confirm(b,u,context)
    if action in ('invoice','issue_invoice'):
        from finance_assistant_invoice import confirm_invoice
        return confirm_invoice(b,u,context)
    if action=='bank_import':return _bank_confirm(b,u,context)
    values=context['values']
    amount_label=''
    if values.get('amount') and values.get('currency'):
        try:amount_label=fx.format_money(minor(values['amount'],values['currency']),values['currency'])
        except Exception:amount_label=values['amount']
    if action in operator.ACTIONS:
        result=operator.confirm(b,u,context['service_token'])
        label='Pemasukan' if action=='create_income' else 'Pengeluaran' if action=='create_expense' else 'Pembayaran invoice'
        detail=(' · '+values.get('description','')) if values.get('description') else ''
        result['message']=f'✅ {label} {amount_label}{detail} berhasil dicatat di Kilas Finance.'
        if action=='record_invoice_payment':
            invoice=f.get_finance_invoice(b,int(values['invoice_id']),u)
            totals=f.get_invoice_totals(b,invoice['id'],u)
            result['message']='✅ Pembayaran '+amount_label+' untuk invoice '+invoice['invoice_number']+' berhasil dicatat. Sisa tagihan: '+fx.format_money(totals['outstanding_minor'],invoice['currency'])+'.'
        else:
            account=f.get_account(b,int(values['account_id']),actor_user_id=u)
            result['message']+=' Rekening: '+account['name']+'.'
        return result
    if action=='recurring':
        result=recurring.confirm(b,u,context['service_token'])
        result['message']=f'Sudah. Biaya rutin {values.get("name") or values.get("description") or ""} {amount_label} berhasil dijadwalkan. Belum ada pengeluaran aktual yang dibuat.'
        return result
    if action=='customer':
        ident=f.create_customer(b,**values,actor_user_id=u,idempotency_key=context['nonce'])
        return dict(record_id=ident,message='Sudah. Customer '+values['name']+' berhasil ditambahkan.')
    if action=='receipt':
        amount=minor(values['amount'],values['currency'])
        ident=receipts.confirm(b,u,context['receipt_token'],dict(confirmed='yes',currency=values['currency'],amount=str(fx.major(amount,values['currency'])),occurred_on=values['date'],account_id=values['account_id'],category_id=values['category_id'],merchant_name=values['merchant_name'],description=values['description']))
        merchant=(' dari '+values['merchant_name']) if values.get('merchant_name') else ''
        return dict(record_id=ident,message='Sudah. Pengeluaran '+fx.format_money(amount,values['currency'])+merchant+' dari struk berhasil dicatat.')
    raise ValueError('invalid_draft')

def document(b,u,files,text,workflow,account_id='',document_context=''):
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
    detected_currency=''
    if document_context:
        detection=unseal(b,u,document_context,'document')
        if detection['hashes'] != [hashlib.sha256(raw).hexdigest() for _,raw in files]:raise ValueError('invalid_draft')
        detected_currency=detection['currency']
    accounts,chosen=account_options(b,u,text,detected_currency or currency_hint(text))
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
    imp=bank.get_import(b,ident,u);rows=bank.get_rows(b,ident,u)
    title='Catatan keuangan' if workflow=='HANDWRITTEN_NOTE' else 'Mutasi bank'
    if not rows:
        return dict(kind='answer',title=title,message='Dokumennya berhasil saya buka, tapi transaksi belum terbaca dengan cukup yakin. Coba kirim PDF asli atau foto/scan yang lebih jelas. Belum ada data yang saya catat.',count=0,fallback=fallback)
    currency=chosen['currency'];attention=sum(bool(r['possible_overlap']) for r in rows)
    preview=[_bank_preview(row,currency) for row in rows[:8]]
    if len(rows)>8:preview.append(['Lainnya',str(len(rows)-8)+' transaksi lagi'])
    if len(rows)>BANK_CHAT_LIMIT:
        return dict(kind='answer',title=title,message=f'Saya membaca {len(rows)} transaksi, tetapi terlalu banyak untuk konfirmasi chat sekali jalan. Pecah mutasi per bulan atau maksimal {BANK_CHAT_LIMIT} transaksi supaya aman.',preview=preview,count=len(rows),fallback=fallback)
    token=seal(b,u,'confirm',dict(action='bank_import',import_id=ident,revision=imp['revision'],document_kind=workflow,nonce=uuid.uuid4().hex))
    message=f'Saya menemukan {len(rows)} transaksi pada {chosen["name"]} ({currency}).'
    if attention:message+=f' Ada {attention} baris yang terlihat duplikat di dalam dokumen.'
    message+=' Saat kamu balas “oke”, saya akan mencatat transaksi yang aman dan menahan yang berpotensi duplikat atau kategorinya belum jelas.'
    return dict(kind='bank_review',title=title,message=message,hint='Balas “oke” untuk memproses, “batal” untuk membatalkan.',ready=True,token=token,preview=preview,count=len(rows),fallback=fallback)


def follow_up(b,u,token,message,confirmation=None,query_context=''):
    import finance_draft_interpreter as interpreter
    message=operator.text(message,2000)
    context=unseal(b,u,token,'review')
    authorize(b,u,None if context['action']=='receipt' else 'OPERATOR')
    if query_context:unseal_query(b,u,query_context)
    if interpreter.NO.fullmatch(message):return dict(kind='answer',state='CANCELLED',message='Oke, draft dibatalkan. Belum ada pencatatan.')
    if interpreter.YES.fullmatch(message):
        if context.get('awaiting'):
            current=review(b,u,context);current.pop('token',None)
            current.update(ready=False,state='NEEDS_INFORMATION',message='Pilih dulu data yang dimaksud sebelum menyimpan.')
            return current
        if not confirmation:return review(b,u,context)
        confirmed=unseal(b,u,confirmation,'confirm')
        # The confirmation must be for exactly the active reviewed values, not an older revision.
        if any(confirmed.get(k)!=context.get(k) for k in ('action','values','nonce')):raise ValueError('invalid_draft')
        result=confirm(b,u,confirmation)
        return dict(kind='success',state='CONFIRMED',**result)
    current=review(b,u,context)
    if context['action']=='invoice':
        from finance_assistant_invoice import add_item
        added=add_item(b,u,context,message)
        if added is not None:return added
    # Route before permissive slot filling, for every signed draft adapter.
    from finance_intent_interpreter import pending_turn
    interruption,updates,continuation=pending_turn(b,u,message,context,current,query_context)
    if interruption is not None:
        interruption['keep_pending']=True
        interruption.setdefault('hint','Draft sebelumnya tetap tersedia. Lanjutkan isinya atau balas “batal”.')
        return interruption
    if context['action']=='issue_invoice':
        current['message']='Balas “oke” untuk menerbitkan invoice yang ditinjau, atau “batal”.'
        return current
    if not updates and continuation:updates=interpreter.slot_reply(message,context,current['fields'],current.get('next_field'))
    if not updates:
        current['message']='Bagian mana yang mau diubah? Sebut nama kolom dan nilainya, atau balas “oke” untuk menyimpan.'
        return current
    try:values=interpreter.resolve(updates,context,current['fields'])
    except interpreter.ReferenceAmbiguous as exc:
        context=dict(context,awaiting=exc.key)
        current['context']=seal(b,u,'review',context)
        current['message']='Pilihan belum jelas. '+('Maksudnya yang mana?' if exc.options else 'Sebut nama yang tersedia; draft sebelumnya tetap aman.')
        current['choices']=[r['label'] for r in exc.options[:8]]
        current.pop('token',None);current.update(ready=False,state='NEEDS_INFORMATION')
        return current
    except ValueError:
        current['message']='Pilihan atau tanggal belum jelas. Pilih nama yang tersedia atau tulis tanggal lengkap; draft sebelumnya tetap aman.'
        return current
    context.pop('awaiting',None)
    return review(b,u,context,values)
