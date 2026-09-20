"""Structured read plans: semantic context is replaced field by field.

The plan selects existing domain projections. Neither a model nor the browser
calculates totals, chooses trusted IDs, or turns a read into a write.
"""
import re
from datetime import date,timedelta
import finance_service as f
import finance_branches as branches
import finance_fx as fx
from finance_semantics import normalize,period_patch,entity_options
from finance_assistant_queries import result,fuzzy_matches,money_groups

RESOURCES=('cashflow','transactions','balances','customers','projects','accounts','categories','branches','invoices','receivables','reminder','recurring','exchanges')


def ambiguous_entity_scope(b,u,message,candidate,key='account'):
    """A query's conversational tail is not necessarily an entity name.

    Exact scoped names use the existing resolver. Only uncertain phrases need
    semantic interpretation; on failure keep the unresolved filter so we never
    silently widen the requested scope.
    """
    import requests
    import finance_ai_safety as safety
    from finance_semantics import interpret
    # Preserve a bare unresolved name; interpretation is for ambiguous phrases.
    if len(candidate.split())==1:return candidate
    try:
        if not safety.allow_attempt(u,b,'ai'):return candidate
        all_intent='all_accounts' if key=='account' else 'all_entities'
        named_intent='named_account' if key=='account' else 'named_entity'
        data=interpret(message,('unknown',all_intent,named_intent),(key,),context={
            'task':f'Resolve the {key} scope of this Finance query. {all_intent} means a list/total with no particular {key} requested; possessives, plural questions and conversational fillers are not names. {named_intent} means a particular entity is requested; copy its literal name into {key}. unknown means uncertain. Never invent or discard an explicitly named entity.',
            'candidate':candidate,
        })
    except (ValueError,requests.RequestException,TypeError,KeyError):return candidate
    if data['intent']==all_intent and not data['slots']:return None
    if data['intent']==named_intent:return data['slots'].get(key) or candidate
    return candidate


def plan(b,u,message,previous=None):
    from finance_assistant_flow import currency_hint
    from finance_assistant_queries import is_contextual_followup
    text=normalize(message);low=text.lower();previous=previous or {}
    # A complete new question must escape a prior entity-clarification question.
    from finance_assistant_flow import is_read_query
    if previous.get('awaiting') and not is_contextual_followup(text) and is_read_query(b,u,text):previous={}
    follow=is_contextual_followup(text) or bool(previous.get('awaiting')) or bool(re.fullmatch(r'(?:berikutnya|selanjutnya|lanjut|next)[ ?.]*',low))
    p=dict(previous) if follow else {}
    p.pop('awaiting',None)
    resource=None
    for name,pattern in (
        ('reminder',r'reminder|pengingat'),('receivables',r'piutang|belum (bayar|lunas)|overdue|aging|outstanding|invoice telat|sisa invoice'),
        ('balances',r'\bsaldo\b'),('recurring',r'\brutin\b'),('exchanges',r'\bfx\b|penukaran|konversi mata uang'),
        ('transactions',r'(?:lihat|daftar|tampilkan|detail|riwayat)\s+transaksi|transaksi\s+#?\d+'),
        ('invoices',r'\binvoice\b'),('cashflow',r'pemasukan|pendapatan|pengeluaran|arus kas|laporan|transaksi|paling banyak|terbesar')):
        if re.search(pattern,low):resource=name;break
    customers=f.list_customers(b,actor_user_id=u)
    if resource is None:
        for name,word in [('customers','customer|pelanggan|telepon|nomor|email'),('projects','proyek'),('accounts','rekening|akun'),('categories','kategori'),('branches','cabang')]:
            if re.search(r'\b(?:'+word+r')\b',low):resource=name;break
        if resource is None and fuzzy_matches(customers,text):resource='customers'
    if resource and not previous.get('awaiting'):p['resource']=resource
    p.setdefault('resource','cashflow')
    if p['resource'] not in RESOURCES:raise ValueError('invalid_draft')
    p['page']=min(100000,p.get('page',0)+1) if re.fullmatch(r'(?:berikutnya|selanjutnya|lanjut|next)[ ?.]*',low) else 0
    tx_number=re.search(r'\btransaksi\s+#?(\d+)\b',low)
    if tx_number:p['transaction']=int(tx_number[1])
    incoming=bool(re.search('pemasukan|pendapatan|paling banyak bayar',low))
    outgoing=bool(re.search('pengeluaran',low))
    if incoming or outgoing:p['direction']='INCOME' if incoming and not outgoing else 'EXPENSE' if outgoing and not incoming else ''
    if re.search('arus kas|selisih',low):p['direction']=''
    code=currency_hint(text)
    if code:p['currency']=code
    if re.search(r'semua mata uang|seluruh mata uang',low):p.pop('currency',None)
    period=period_patch(text)
    if period:p['period']=period
    p.setdefault('period',period_patch('bulan ini'))
    if p['resource']=='recurring':
        if period:p['forecast']=period['mode']!='all'
        elif not follow:p['forecast']=False
    if p['resource'] in ('receivables','invoices','reminder'):
        if not follow:p['overdue']=False;p['aging']=False;p['due_week']=False
        if re.search('overdue|telat|paling lama',low):p['overdue']=True
        if 'aging' in low:p['aging']=True
        if 'minggu ini' in low:p['due_week']=True
        number=re.search(r'\b(?:KFIN|INV)-[\w-]+',text,re.I)
        if number:p['invoice']=number[0]
    if re.search('terbesar|paling banyak|per kategori|per customer|per proyek|per cabang',low):
        p['group_by']=next((name for name,word in [('project','proyek'),('customer','customer'),('branch','cabang'),('category','kategori')] if word in low),'category')
    p['count']=bool('transaksi' in low) or p.get('count',False)
    # Names are re-resolved against current scoped records at execution time.
    pools={'customer':(customers,'name'), 'project':(f.list_finance_projects(b,actor_user_id=u),'title'),
           'account':(f.list_accounts(b,actor_user_id=u),'name'), 'category':(f.list_categories(b,actor_user_id=u),'name'),
           'branch':(branches.list_branches(b,u),'name')}
    labels={'customer':'customer|pelanggan|piutang','project':'proyek','account':'rekening|akun|saldo','category':'kategori','branch':'cabang'}
    awaiting=previous.get('awaiting') if follow else None
    for key,(rows,label) in pools.items():
        if awaiting==key:
            p[key]=text.strip(' ?.');continue
        if key=='branch' and re.search(r'semua cabang|gabungan',low):p['branch']='*';continue
        named=fuzzy_matches(rows,text,label)
        if named and (key!='category' or 'kategori' in low):
            # Ambiguous short names are preserved as the actual supplied name.
            if len(named)==1:p[key]=str(named[0][label])
            else:
                raw=re.search(r'\b(?:'+labels[key]+r')\s+(.+?)(?=\s+(?:berapa|bulan|tahun|paling|yang|keseluruhan|dari|selama)\b|[?]|$)',text,re.I)
                p[key]=raw[1].strip() if raw else text
        elif re.search(r'\b(?:'+labels[key]+r')\b',low) and p.get('group_by')!=key:
            raw=re.search(r'\b(?:'+labels[key]+r')\s+(.+?)(?=\s+(?:berapa|bulan|tahun|yang|keseluruhan|dari|selama)\b|[?]|$)',text,re.I)
            if raw:
                value=raw[1].strip()
                generic=all(w.lower() in set('gw gue gua aku saya kita apa siapa aja saja semua daftar total tersedia sekarang ini itu awal terbesar paling banyak bayar per minggu lalu depan telat overdue aging outstanding'.split())|{c.lower() for c in f.SUPPORTED_CURRENCIES} for w in value.split())
                if value and not generic and not period_patch(value):
                    if key=='account' and p['resource']=='balances' and not re.search(r'\b(?:rekening|akun)\b',low):
                        value=ambiguous_entity_scope(b,u,message,value)
                    elif p['resource'] in ('customers','projects','accounts','categories','branches'):
                        value=ambiguous_entity_scope(b,u,message,value,key)
                    if value:p[key]=value
                    else:p.pop(key,None)
    return p


def ask(p,key,rows,label='name'):
    p['awaiting']=key
    name={'customer':'Customer','account':'Rekening','project':'Proyek','branch':'Cabang','category':'Kategori'}[key]
    choices=[str(r[label]) for r in rows[:8]]
    return result(name,[],name+' belum jelas. '+('Maksudnya yang mana?' if choices else 'Sebut nama yang tersedia.'))|{'choices':choices}


def execute(b,u,p,scoped=False):
    today=date.today().isoformat();resource=p['resource'];ids={}
    if not scoped and p.get('branch'):
        if p['branch']=='*':branch=None
        else:
            found=entity_options(branches.list_branches(b,u),p['branch'])
            if len(found)!=1:return ask(p,'branch',found)
            branch=found[0]['id']
        with branches.scope(b,branch,u):return execute(b,u,p,True)
    pools={'customer':(f.list_customers(b,actor_user_id=u),'name'),
           'project':(f.list_finance_projects(b,actor_user_id=u),'title'),
           'account':(f.list_accounts(b,include_inactive=True,actor_user_id=u),'name'),
           'category':(f.list_categories(b,include_inactive=True,actor_user_id=u),'name')}
    for key,(rows,label) in pools.items():
        if p.get(key):
            found=entity_options(rows,p[key],label)
            if len(found)!=1:return ask(p,key,found,label)
            ids[key+'_id']=found[0]['id']
    currency=p.get('currency')
    if resource in ('customers','projects','accounts','categories','branches'):
        key={'customers':'customer','projects':'project','accounts':'account','categories':'category','branches':'branch'}[resource]
        rows,label=pools[key] if key in pools else (branches.list_branches(b,u),'name')
        if ids.get(key+'_id'):rows=[r for r in rows if r['id']==ids[key+'_id']]
        if currency and resource=='accounts':rows=[r for r in rows if r['currency']==currency]
        preview=[]
        page=p.get('page',0);count=len(rows)
        for r in rows[page*50:(page+1)*50]:
            info='Telepon: '+(r['phone'] or '—')+' · Email: '+(r['email'] or '—')+' · '+(r['notes'] or '') if resource=='customers' else (
                r['currency']+' · '+r['account_type'] if resource=='accounts' else r['direction'] if resource=='categories' else 'Aktif')
            preview.append([r[label],info])
        return result({'customers':'Data customer','projects':'Proyek','accounts':'Rekening','categories':'Kategori','branches':'Cabang'}[resource],preview)|{'choices':['Berikutnya'] if count>(page+1)*50 else []}
    if resource=='transactions':
        period=p['period'];start,end=(None,None) if period['mode']=='all' else period['ranges'][0]
        filters=dict(start_date=start,end_date=end,direction=p.get('direction') or None,status='POSTED',currency=currency,**ids)
        rows=f.list_transactions(b,**filters,actor_user_id=u,limit=50,offset=p.get('page',0)*50)
        count=f.count_transactions(b,**filters,actor_user_id=u)
        if p.get('transaction'):
            row=f.get_transaction(b,p['transaction'],actor_user_id=u);rows=[row] if row else [];count=len(rows)
        names={r['id']:r['name'] for r in branches.list_branches(b,u)}
        preview=[['Transaksi '+str(r['id'])+' · '+r['occurred_on']+' · '+names[r['branch_id']],r['direction']+' · '+fx.format_money(r['amount_minor'],r['currency'])+' · '+(r['description'] or '—')+' · '+r['status']] for r in rows]
        return result('Transaksi',preview,str(count)+' transaksi sesuai filter.')|{'choices':['Berikutnya'] if count>(p.get('page',0)+1)*50 else []}
    if resource=='balances':
        rows=f.get_account_balance_report(b,today,u)
        if ids.get('account_id'):rows=[r for r in rows if r['id']==ids['account_id']]
        if currency:rows=[r for r in rows if r['currency']==currency]
        preview=[[r['name']+' · '+r['branch_name'],fx.format_money(r['balance_minor'],r['currency'])] for r in rows]
        preview += [['Total '+r['currency'],fx.format_money(r['balance_minor'],r['currency'])] for r in f.aggregate_account_balances_by_currency(rows)]
        return result('Saldo akun',preview,'Saldo saat ini mencakup saldo awal dan FX. Periode laporan tidak mengubah saldo tersedia; saldo awal dan FX bukan pendapatan operasional.')
    if resource in ('receivables','invoices','reminder'):
        rows=f.get_report_invoices(b,today,actor_user_id=u,customer_id=ids.get('customer_id'),open_only=resource!='invoices')
        if p.get('invoice'):
            rows=[r for r in rows if r['invoice_number'].casefold()==p['invoice'].casefold()]
            if not rows:return result('Invoice',[],'Nomor invoice belum dikenali. Sebut nomor invoice lengkap.')
        if currency:rows=[r for r in rows if r['currency']==currency]
        if p.get('overdue') or resource=='reminder':rows=[r for r in rows if r['overdue']]
        if p.get('due_week'):
            end=(date.today()+timedelta(days=6-date.today().weekday())).isoformat()
            rows=[r for r in rows if today<=r['due_date']<=end]
        rows.sort(key=lambda r:(-r['days_late'],r['id']))
        if resource=='reminder':
            if not rows:return result('Draft reminder',[],'Tidak ada invoice overdue yang cocok untuk template pengingat ini.')
            if len(rows)>1:return result('Pilih invoice',[[r['invoice_number'],r['customer_name']] for r in rows[:50]],'Sebut nomor invoice untuk reminder.')|{'choices':[r['invoice_number'] for r in rows[:8]]}
            import finance_collections
            return result('Draft reminder',[],finance_collections.reminder(b,rows[0]['id'],u))
        preview=money_groups(rows,'outstanding_minor') if resource=='receivables' else []
        preview += [[r['customer_name']+' · '+r['invoice_number'],r['status']+' · sisa '+fx.format_money(r['outstanding_minor'],r['currency'])+' · jatuh tempo '+r['due_date']] for r in rows[:50]]
        if p.get('aging'):
            preview=[[bucket['label']+' · '+group['currency'],fx.format_money(bucket['amount_minor'],group['currency'])] for group in f.receivables_aging_rows(rows)['by_currency'] for bucket in group['buckets']]
        return result('Piutang / invoice',preview,'Posisi invoice saat ini. Draft dan void tidak dihitung sebagai piutang; maksimal 50 rincian ditampilkan.')
    if resource=='exchanges':
        rows=f.list_currency_exchanges(b,actor_user_id=u)
        return result('Penukaran mata uang',[[r['occurred_on'],fx.format_money(r['from_amount_minor'],r['from_currency'])+' → '+fx.format_money(r['to_amount_minor'],r['to_currency'])+' · '+r['status']] for r in rows],
                      'FX memindahkan saldo antar mata uang, bukan pemasukan atau pengeluaran operasional.')
    if resource=='recurring' and not p.get('forecast'):
        rows=f.list_recurring_expenses(b,actor_user_id=u)
        if currency:rows=[r for r in rows if r['currency']==currency]
        if not rows:return result('Biaya rutin',[],'Belum ada biaya rutin aktif pada cabang yang dipilih.')
        return result('Biaya rutin',[[r['name']+' · '+r['cadence'],fx.format_money(r['amount_minor'],r['currency'])+' · jatuh tempo berikutnya '+r['next_due_on']] for r in rows[:100]],
                      'Daftar biaya rutin aktif. Jadwal adalah komitmen; belum menjadi pengeluaran sampai kejadiannya dicatat.')
    preview=[];period=p['period'];ranges=[(None,None)] if period['mode']=='all' else period['ranges']
    for start,end in ranges:
        label='Semua waktu' if start is None else start[:7] if start.endswith('-01') and start[:7]==end[:7] else start+' – '+end
        if resource=='recurring':
            rows=f.get_upcoming_recurring_commitments(b,start,end,u)
            if currency:rows=[r for r in rows if r['currency']==currency]
            preview.extend([[r['name']+' · '+r['scheduled_on'],fx.format_money(r['amount_minor'],r['currency'])] for r in rows[:100]])
            if not rows:preview.append([label,'Belum ada biaya rutin terjadwal.'])
            continue
        rows=f.get_cash_totals(b,start,end,actor_user_id=u,**ids,currency=currency,direction=p.get('direction'),group_by=p.get('group_by'))
        if not rows:preview.append([label,'Belum ada transaksi.'])
        if p.get('group_by'):
            # Rank within each native currency, never compare USD nominal to IDR.
            metric='total_expense_minor' if p.get('direction')=='EXPENSE' else 'total_income_minor' if p.get('direction')=='INCOME' else 'net_cashflow_minor'
            rows.sort(key=lambda r:(r['currency'],-r[metric]))
            preview.extend([[label+' · '+(r['name'] or 'Tanpa '+p['group_by']),fx.format_money(r[metric],r['currency'])] for r in rows[:50]])
        else:
            for r in rows:
                for direction,key,title in [('INCOME','total_income_minor','Pemasukan'),('EXPENSE','total_expense_minor','Pengeluaran'),('','net_cashflow_minor','Arus kas bersih')]:
                    if not p.get('direction') or p.get('direction')==direction:preview.append([label+' · '+title,fx.format_money(r[key],r['currency'])])
            if p.get('count'):preview.append(['Jumlah transaksi',str(sum(r['transaction_count'] for r in rows))])
    return result('Biaya rutin' if resource=='recurring' else 'Laporan Finance',preview,
                  'Komitmen terjadwal, belum merupakan pengeluaran aktual.' if resource=='recurring' else 'Transaksi aktual sesuai tanggal kejadian. Saldo awal, FX, draft invoice, dan jadwal belum dibayar tidak menjadi arus kas.')
