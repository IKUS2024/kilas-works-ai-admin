"""Scoped read-only answers. All arithmetic uses server Finance projections."""
import calendar
import re
from difflib import SequenceMatcher
from datetime import date,timedelta
import finance_service as f
import finance_collections as collections
import finance_branches as branches
import finance_fx as fx

MONTHS='januari februari maret april mei juni juli agustus september oktober november desember'.split()
MONTH_ALIASES={
    1:('januari','january','jan'),2:('februari','february','feb'),3:('maret','march','mar'),
    4:('april','apr'),5:('mei','may'),6:('juni','june','jun'),7:('juli','july','jul'),
    8:('agustus','august','aug'),9:('september','sept','sep'),10:('oktober','october','okt','oct'),
    11:('november','nov'),12:('desember','december','des','dec')}
MONTH_ALIAS_TO_NUMBER={alias:number for number,aliases in MONTH_ALIASES.items() for alias in aliases}
FINANCE_TERMS=('finance','keuangan','akuntansi','transaksi','pemasukan','pendapatan','penjualan','pengeluaran','biaya',
               'kas','cash','rekening','bank','saldo','invoice','tagihan','piutang','utang','customer','pelanggan',
               'kategori','proyek','struk','receipt','mutasi','rekonsiliasi','overdue','outstanding','aging',
               'reminder','laporan','arus','rutin','bulanan','mingguan')
TYPO_TERMS=('pemasukan','pendapatan','pengeluaran','customer','pelanggan','laporan','saldo','invoice','piutang',
            'rekening','proyek','rutin','reminder','overdue','transaksi','kategori','mutasi','rekonsiliasi')
FOLLOW_PREFIX=re.compile(r'^\s*(kalau|kalo|yang|terus|trus|lalu|dan|nah|terus kalau|kalau yang)\b',re.I)

def _norm(value):
    value=re.sub(r'[^0-9a-zA-Z]+',' ',str(value or '').casefold()).strip()
    return re.sub(r'\s+',' ',value)

def canonicalize(text):
    """Correct only high-confidence Finance vocabulary typos; leave names/numbers untouched."""
    def replace(match):
        word=match.group(0);lower=word.casefold()
        if lower in TYPO_TERMS:return lower
        ranked=sorted(((SequenceMatcher(None,lower,term).ratio(),term) for term in TYPO_TERMS),reverse=True)
        return ranked[0][1] if ranked and ranked[0][0]>=0.84 else word
    return re.sub(r'[A-Za-z]{4,}',replace,text)

def fuzzy_matches(rows,text,key='name'):
    """Resolve a visible scoped name with typo tolerance; never invent an ID."""
    direct=[r for r in rows if r.get(key) and re.search(r'(?<!\w)'+re.escape(str(r[key]))+r'(?!\w)',text,re.I)]
    if direct:return direct
    tokens=_norm(text).split()
    ranked=[]
    for row in rows:
        name=_norm(row.get(key,''))
        parts=name.split()
        if not parts or not tokens:continue
        width=len(parts)
        windows=[' '.join(tokens[i:i+width]) for i in range(max(1,len(tokens)-width+1))]
        if width==1:windows=tokens
        score=max((SequenceMatcher(None,name,w).ratio() for w in windows if w),default=0)
        if score>=0.80:ranked.append((score,row))
    if not ranked:return []
    best=max(score for score,_ in ranked)
    return [row for score,row in ranked if score>=best-0.025]

def looks_finance(text,b=None,u=None):
    if not isinstance(text,str):return False
    words=_norm(canonicalize(text)).split()
    if any(word in FINANCE_TERMS for word in words):return True
    for word in words:
        if len(word)>=4 and max((SequenceMatcher(None,word,term).ratio() for term in FINANCE_TERMS),default=0)>=0.82:
            return True
    if b is not None and u is not None:
        pools=((f.list_customers(b,actor_user_id=u),'name'),
               (f.list_accounts(b,actor_user_id=u),'name'),
               (f.list_finance_projects(b,actor_user_id=u),'title'))
        if any(fuzzy_matches(rows,text,key) for rows,key in pools):
            return True
    return False

def is_contextual_followup(current):
    current=(current or '').strip()
    if not current:return False
    if FOLLOW_PREFIX.search(current):return True
    if re.search(r'\b(semua(?:nya)?|keseluruhan|dari awal|dri awal|bulan lalu|bulan sebelumnya|yang tadi|tadi|itu|ini|aja|saja)\b',current,re.I):
        return True
    return len(current.split())<=7 and bool(re.search(r'\b(berapa|gimana|bagaimana|lagi|usd|idr|sgd|eur|gbp|aud|jpy|cny|hkd|thb|myr)\b',current,re.I))

def contextualize(previous,current):
    previous=(previous or '').strip();current=(current or '').strip()
    current=canonicalize(current)
    if not previous or not is_contextual_followup(current):return current
    base=previous
    if re.search(r'\bpengeluaran',current,re.I):
        base=re.sub(r'\b(pemasukan|pendapatan|penjualan)\b',' ',base,flags=re.I)
    elif re.search(r'\b(pemasukan|pendapatan|penjualan)',current,re.I):
        base=re.sub(r'\bpengeluaran\b',' ',base,flags=re.I)
    return re.sub(r'\s+',' ',base+' '+current).strip()[-2000:]


def periods(text):
    today=date.today();year=re.search(r'\b(20\d{2})\b',text)
    year=int(year[1]) if year else today.year
    found=[]
    for match in re.finditer(r'\b[A-Za-z]+\b',text):
        word=match.group(0).casefold()
        month=MONTH_ALIAS_TO_NUMBER.get(word)
        if month is None and len(word)>=3:
            ranked=sorted(((SequenceMatcher(None,word,alias).ratio(),number)
                           for alias,number in MONTH_ALIAS_TO_NUMBER.items()),reverse=True)
            if ranked and ranked[0][0]>=0.84:month=ranked[0][1]
        if month:found.append((match.start(),month))
    starts=[date(year,m,1) for _,m in sorted(found)]
    if not starts:
        start=today.replace(day=1)
        lower=text.lower()
        if 'bulan lalu' in lower or 'bulan sebelumnya' in lower:start=(start-timedelta(days=1)).replace(day=1)
        if 'bulan depan' in lower:start=(start+timedelta(days=32)).replace(day=1)
        starts=[start]
    unique=[]
    for item in starts:
        if item not in unique:unique.append(item)
    return [(d.isoformat(),d.replace(day=calendar.monthrange(d.year,d.month)[1]).isoformat()) for d in unique[:2]]


def result(title,preview,message='Data mengikuti cabang yang dipilih; mata uang tetap terpisah.'):
    return dict(kind='answer',title=title,message=message,preview=preview or [['Hasil','Tidak ada data yang cocok.']])


def money_groups(rows,key):
    groups={}
    for r in rows:groups[r['currency']]=groups.get(r['currency'],0)+r[key]
    return [[code,fx.format_money(value,code)] for code,value in groups.items()]


def query(b,u,text,branch_checked=False):
    from finance_assistant_flow import exact_matches,currency_hint
    text=canonicalize(text)
    lower=text.lower();today=date.today()
    all_time=bool(re.search(r'\b(keseluruhan|semua(?:nya)?|dari\s+(?:bulan\s+)?awal|dri\s+(?:bulan\s+)?awal|sejak awal|selama ini|all[ -]?time)\b',lower))
    if not branch_checked:
        named=fuzzy_matches(branches.list_branches(b,u),text)
        if re.search(r'\bcabang\b',text,re.I) and len(named)==1:
            with branches.scope(b,named[0]['id'],u):return query(b,u,text,True)
        if re.search(r'\bcabang\b',text,re.I) and not re.search(r'semua cabang|gabungan',text,re.I) and len(named)!=1:
            return result('Cabang',[], 'Cabang mana? Sebut nama cabang lengkap.')
    if 'saldo awal' in lower:
        return result('Saldo awal',[], 'Saldo awal adalah uang yang sudah ada saat mulai mencatat, bukan pemasukan. Saldo rekening mencakup saldo awal, transaksi aktual, dan perpindahan saldo FX; periode laporan tidak mengubah saldo tersedia saat ini.')
    if 'saldo' in lower:
        rows=f.get_account_balance_report(b,today.isoformat(),u)
        named=fuzzy_matches(rows,text)
        code=currency_hint(text)
        if named:rows=named
        if code:rows=[r for r in rows if r['currency']==code]
        target=re.search(r'\bsaldo\s+(.+?)(?:\s+berapa|[?]|$)',text,re.I)
        target_text=target[1] if target else ''
        target_text=re.sub(r'\b(gw|gue|gua|aku|saya|sy|milik|punya|ku|sekarang|saat ini|nih|ini)\b',' ',target_text,flags=re.I)
        target_text=re.sub(r'\s+',' ',target_text).strip(' ?.,')
        if target_text and not named and not code and target_text.lower() not in ('kas','tersedia','rekening','akun','total'):
            return result('Saldo akun',[],'Rekening belum dikenali. Sebut nama rekening yang tersedia.')
        return result('Saldo akun',[[r['name']+' · '+r['branch_name'],fx.format_money(r['balance_minor'],r['currency'])] for r in rows],
                      'Saldo saat ini mencakup saldo awal. Saldo awal dan penukaran mata uang bukan pendapatan operasional.')
    customers=f.list_customers(b,actor_user_id=u)
    named=fuzzy_matches(customers,text)
    if len(named)>1:return result('Customer',[], 'Ada beberapa customer cocok. Sebut nama lengkap.')
    customer=named[0] if len(named)==1 else None
    receivable=bool(re.search(r'piutang|belum bayar|belum lunas|overdue|jatuh tempo|invoice telat|aging|outstanding|sisa',lower))
    if receivable or 'invoice' in lower or 'reminder' in lower:
        rows=f.get_report_invoices(b,today.isoformat(),actor_user_id=u,customer_id=customer['id'] if customer else None,
                                  open_only=receivable or 'reminder' in lower)
        invoices=exact_matches(rows,text,'invoice_number')
        if re.search(r'\b(?:KFIN|INV)-',text,re.I) and len(invoices)!=1:
            return result('Invoice',[], 'Nomor invoice belum dikenali. Sebut nomor invoice lengkap.')
        if invoices:rows=invoices
        if re.search(r'piutang\s+\w+\s+berapa',lower) and not customer:
            return result('Piutang',[], 'Customer belum dikenali. Sebut nama customer lengkap.')
        if 'overdue' in lower or 'telat' in lower or 'paling lama' in lower:rows=[r for r in rows if r['overdue']]
        if 'minggu ini' in lower:
            end=today+timedelta(days=6-today.weekday())
            rows=[r for r in rows if today.isoformat()<=r['due_date']<=end.isoformat()]
        rows=sorted(rows,key=lambda r:(-r['days_late'],r['id']))
        if 'reminder' in lower:
            rows=[r for r in rows if r['overdue']]
            if not rows:return result('Draft reminder',[], 'Tidak ada invoice overdue yang cocok untuk template pengingat ini.')
            if len(rows)>1:return result('Pilih invoice',[[r['invoice_number'],r['customer_name']] for r in rows[:50]],'Sebut nomor invoice untuk reminder.')
            return result('Draft reminder',[],collections.reminder(b,rows[0]['id'],u))
        preview=money_groups(rows,'outstanding_minor') if receivable else []
        preview += [[r['customer_name']+' · '+r['invoice_number'],r['status']+' · sisa '+fx.format_money(r['outstanding_minor'],r['currency'])+' · jatuh tempo '+r['due_date']] for r in rows[:50]]
        if 'aging' in lower:
            preview=[]
            for group in f.receivables_aging_rows(rows)['by_currency']:
                preview.extend([[bucket['label']+' · '+group['currency'],fx.format_money(bucket['amount_minor'],group['currency'])] for bucket in group['buckets']])
        return result('Piutang / invoice',preview,'Posisi invoice saat ini. Draft dan void tidak dihitung sebagai piutang; maksimal 50 rincian ditampilkan.')
    customer_words=bool(re.search(r'customer|custumer|costumer|pelanggan|nomor|telepon|email',lower))
    if (customer_words or (customer and re.search(r'\b(nama|cek|lihat|cari|ada)\b',lower))) and not re.search(r'paling banyak|transaksi|pemasukan|pengeluaran',lower):
        rows=[customer] if customer else customers if re.search(r'tampilkan|cari|data|lihat|daftar|cek|apa aja|siapa aja',lower) else []
        if not rows:return result('Data customer',[],'Customer yang dimaksud belum ditemukan. Coba tulis nama atau ejaan yang lebih dekat.')
        return result('Data customer',[[r['name'],'Telepon: '+(r['phone'] or '—')+' · Email: '+(r['email'] or '—')] for r in rows[:50]])
    recurring_intent=bool(re.search(r'\b(biaya rutin|pengeluaran rutin|rutin)\b',lower))
    explicit_period=bool(re.search(r'\b(bulan ini|bulan lalu|bulan sebelumnya|bulan depan|minggu ini|20\d{2})\b',lower) or
                         any(re.search(r'\b'+re.escape(alias)+r'\b',lower) for alias in MONTH_ALIAS_TO_NUMBER))
    if recurring_intent and not explicit_period and not all_time:
        rules=f.list_recurring_expenses(b,actor_user_id=u)
        if not rules:return result('Biaya rutin',[],'Belum ada biaya rutin aktif pada cabang yang dipilih.')
        return result('Biaya rutin',[[r['name']+' · '+r['cadence'],
            fx.format_money(r['amount_minor'],r['currency'])+' · jatuh tempo berikutnya '+r['next_due_on']] for r in rules[:100]],
            'Daftar biaya rutin aktif pada cabang yang dipilih.')
    preview=[]
    ranges=[('1900-01-01',today.isoformat())] if all_time else periods(text)
    for start,end in ranges:
        period_label='Semua waktu' if all_time else start[:7]
        if recurring_intent:
            rows=f.get_upcoming_recurring_commitments(b,start,end,u)
            if not rows:
                preview.append([period_label,'Belum ada biaya rutin terjadwal.'])
            else:
                preview.extend([[r['name']+' · '+r['scheduled_on'],fx.format_money(r['amount_minor'],r['currency'])] for r in rows[:100]])
            continue
        rows=f.get_report_transactions(b,start,end,u)
        projects=f.list_finance_projects(b,actor_user_id=u)
        selected=fuzzy_matches(projects,text,'title')
        if 'proyek' in lower and len(selected)>1:return result('Proyek',[], 'Ada beberapa proyek cocok. Sebut nama proyek lengkap.')
        if 'proyek' in lower and selected:rows=[r for r in rows if r['project_id']==selected[0]['id']]
        elif 'proyek' in lower and 'paling' not in lower:return result('Proyek',[], 'Sebut nama proyek yang tersedia.')
        if customer:rows=[r for r in rows if r['customer_id']==customer['id']]
        income=bool(re.search(r'pemasukan|pendapatan|paling banyak bayar',lower))
        expense=bool(re.search(r'pengeluaran',lower))
        if income and not expense:rows=[r for r in rows if r['direction']=='INCOME']
        if expense and not income:rows=[r for r in rows if r['direction']=='EXPENSE']
        if re.search(r'terbesar|paling banyak|kategori',lower):
            key='project_name' if 'proyek' in lower else 'customer_name' if 'customer' in lower else 'category_name'
            groups={}
            for r in rows:
                label=r.get(key) or 'Tanpa '+key.split('_')[0];group=(label,r['currency'])
                groups[group]=groups.get(group,0)+r['amount_minor']
            preview += [[period_label+' · '+name,fx.format_money(amount,code)] for (name,code),amount in sorted(groups.items(),key=lambda x:-x[1])[:20]]
        else:
            codes=sorted({r['currency'] for r in rows})
            if not codes:preview.append([period_label,'Belum ada transaksi.'])
            for code in codes:
                ins=sum(r['amount_minor'] for r in rows if r['currency']==code and r['direction']=='INCOME')
                outs=sum(r['amount_minor'] for r in rows if r['currency']==code and r['direction']=='EXPENSE')
                if not expense:preview.append([period_label+' · Pemasukan',fx.format_money(ins,code)])
                if not income:preview.append([period_label+' · Pengeluaran',fx.format_money(outs,code)])
                if not income and not expense:preview.append([period_label+' · Arus kas bersih',fx.format_money(ins-outs,code)])
            if customer and 'transaksi' in lower:preview.append(['Jumlah transaksi',str(len(rows))])
    return result('Laporan Finance',preview)
