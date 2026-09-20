"""Scoped read-only answers. All arithmetic uses server Finance projections."""
import calendar
import re
from datetime import date,timedelta
import finance_service as f
import finance_collections as collections
import finance_branches as branches
import finance_fx as fx

MONTHS='januari februari maret april mei juni juli agustus september oktober november desember'.split()


def periods(text):
    today=date.today();year=re.search(r'\b(20\d{2})\b',text)
    year=int(year[1]) if year else today.year
    found=[(m.start(),i+1) for i,name in enumerate(MONTHS) for m in re.finditer(r'\b'+name+r'\b',text,re.I)]
    starts=[date(year,m,1) for _,m in sorted(found)]
    if not starts:
        start=today.replace(day=1)
        if 'bulan lalu' in text.lower():start=(start-timedelta(days=1)).replace(day=1)
        if 'bulan depan' in text.lower():start=(start+timedelta(days=32)).replace(day=1)
        starts=[start]
    return [(d.isoformat(),d.replace(day=calendar.monthrange(d.year,d.month)[1]).isoformat()) for d in starts[:2]]


def result(title,preview,message='Data mengikuti cabang yang dipilih; mata uang tetap terpisah.'):
    return dict(kind='answer',title=title,message=message,preview=preview or [['Hasil','Tidak ada data yang cocok.']])


def money_groups(rows,key):
    groups={}
    for r in rows:groups[r['currency']]=groups.get(r['currency'],0)+r[key]
    return [[code,fx.format_money(value,code)] for code,value in groups.items()]


def query(b,u,text,branch_checked=False):
    from finance_assistant_flow import exact_matches,currency_hint
    lower=text.lower();today=date.today()
    if not branch_checked:
        named=exact_matches(branches.list_branches(b,u),text)
        if re.search(r'\bcabang\b',text,re.I) and len(named)==1:
            with branches.scope(b,named[0]['id'],u):return query(b,u,text,True)
        if re.search(r'\bcabang\b',text,re.I) and not re.search(r'semua cabang|gabungan',text,re.I) and len(named)!=1:
            return result('Cabang',[], 'Cabang mana? Sebut nama cabang lengkap.')
    if 'saldo awal' in lower:
        return result('Saldo awal',[], 'Saldo awal adalah uang yang sudah ada saat mulai mencatat, bukan pemasukan. Saldo rekening mencakup saldo awal, transaksi aktual, dan perpindahan saldo FX; periode laporan tidak mengubah saldo tersedia saat ini.')
    if 'saldo' in lower:
        rows=f.get_account_balance_report(b,today.isoformat(),u)
        named=exact_matches(rows,text)
        code=currency_hint(text)
        if named:rows=named
        if code:rows=[r for r in rows if r['currency']==code]
        target=re.search(r'\bsaldo\s+(.+?)(?:\s+berapa|[?]|$)',text,re.I)
        if target and not named and not code and target[1].strip().lower() not in ('saya','kas','tersedia','rekening','akun','sekarang','total'):
            return result('Saldo akun',[],'Rekening belum dikenali. Sebut nama rekening yang tersedia.')
        return result('Saldo akun',[[r['name']+' · '+r['branch_name'],fx.format_money(r['balance_minor'],r['currency'])] for r in rows],
                      'Saldo saat ini mencakup saldo awal. Saldo awal dan penukaran mata uang bukan pendapatan operasional.')
    customers=f.list_customers(b,actor_user_id=u)
    named=exact_matches(customers,text)
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
    if re.search(r'customer|pelanggan|nomor|telepon|email',lower) and not re.search(r'paling banyak|transaksi|pemasukan|pengeluaran',lower):
        rows=[customer] if customer else customers if re.search(r'tampilkan customer|cari customer|data customer|lihat customer',lower) else []
        return result('Data customer',[[r['name'],'Telepon: '+(r['phone'] or '—')+' · Email: '+(r['email'] or '—')] for r in rows[:50]])
    preview=[]
    for start,end in periods(text):
        if re.search(r'biaya rutin|rutin bulan',lower):
            rows=f.get_upcoming_recurring_commitments(b,start,end,u)
            preview.extend([[r['name']+' · '+r['scheduled_on'],fx.format_money(r['amount_minor'],r['currency'])] for r in rows[:100]])
            continue
        rows=f.get_report_transactions(b,start,end,u)
        projects=f.list_finance_projects(b,actor_user_id=u)
        selected=exact_matches(projects,text,'title')
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
            preview += [[start[:7]+' · '+name,fx.format_money(amount,code)] for (name,code),amount in sorted(groups.items(),key=lambda x:-x[1])[:20]]
        else:
            codes=sorted({r['currency'] for r in rows})
            if not codes:preview.append([start[:7],'Belum ada transaksi.'])
            for code in codes:
                ins=sum(r['amount_minor'] for r in rows if r['currency']==code and r['direction']=='INCOME')
                outs=sum(r['amount_minor'] for r in rows if r['currency']==code and r['direction']=='EXPENSE')
                if not expense:preview.append([start[:7]+' · Pemasukan',fx.format_money(ins,code)])
                if not income:preview.append([start[:7]+' · Pengeluaran',fx.format_money(outs,code)])
                if not income and not expense:preview.append([start[:7]+' · Arus kas bersih',fx.format_money(ins-outs,code)])
            if customer and 'transaksi' in lower:preview.append(['Jumlah transaksi',str(len(rows))])
    return result('Laporan Finance',preview)
