"""Scoped read-only answers. All arithmetic uses server Finance projections."""
import re
from difflib import SequenceMatcher
import finance_service as f
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
    if re.fullmatch(r'(berikutnya|selanjutnya|lanjut|next)[ ?.]*',current,re.I):return True
    from finance_semantics import period_patch
    from finance_assistant_flow import currency_hint
    if FOLLOW_PREFIX.search(current) and looks_finance(current):return True
    # A bare period/currency answer inherits context; a full new question resets it.
    # Arbitrary words such as weather must not become finance just because a month
    # or the word "kalau" appeared beside them.
    fragments=set('kalau kalo yang terus trus dan nah bulan minggu tahun hari ini lalu sebelumnya depan kemarin dari dri awal sejak selama keseluruhan semuanya semua berapa total aja saja dong ya sampai hingga sama bandingkan bandingin compare idr usd sgd eur gbp aud jpy cny hkd thb myr rupiah dolar dollar amerika singapura australia ringgit euro pound sterling yen yuan renminbi baht'.split())|set(MONTH_ALIAS_TO_NUMBER)
    words=re.findall(r'[A-Za-z]+',current.lower())
    if (period_patch(current) or currency_hint(current)) and all(w in fragments for w in words):return True
    if re.fullmatch(r'(?:(?:yang|tadi|itu|ini|aja|saja|semua|semuanya|kalau|kalo)\s*)+[?.! ]*',current,re.I):return True
    return bool(re.fullmatch(r'\s*(?:(?:berapa|gimana|bagaimana|lagi|usd|idr|sgd|eur|gbp|aud|jpy|cny|hkd|thb|myr|total|dong|ya)\s*)+[?!. ]*',current,re.I))

def result(title,preview,message='Data mengikuti cabang yang dipilih; mata uang tetap terpisah.'):
    return dict(kind='answer',title=title,message=message,preview=preview or [['Hasil','Tidak ada data yang cocok.']])


def money_groups(rows,key):
    groups={}
    for r in rows:groups[r['currency']]=groups.get(r['currency'],0)+r[key]
    return [[code,fx.format_money(value,code)] for code,value in groups.items()]


def query(b,u,text,branch_checked=False):
    # Compatibility entry point; the structured query engine owns every projection.
    from finance_query_plan import plan,execute
    return execute(b,u,plan(b,u,text),scoped=branch_checked)
