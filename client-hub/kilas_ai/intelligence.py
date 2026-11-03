"""Private deterministic difficulty and depth; no classifier/provider invocation."""
import re
from collections import Counter

DOMAINS = {
    'business':r'\b(?:strategi|strategy|pricing|harga|unit economics|gtm|positioning|bisnis|business|usaha|monetisasi|saas|margin|profit|estrategia|negocio|precios)\b|商业|定价|策略',
    'coding':r'\b(?:debug|bug|kode|coding|code|sql|refactor|stack trace|traceback|repository|arsitektur|architecture|código|depurar|arquitectura)\b|代码|调试|架构',
    'research':r'\b(?:research|riset|sumber|sources|terbaru|latest|terkini|hari ini|today|search|cari informasi|investigar|fuentes|actualidad)\b|研究|搜索|最新',
    'documents':r'\b(?:pdf|file|dokumen|document|lampiran|attachment|spreadsheet|laporan|report|documento|archivo|informe)\b|文档|文件|报告',
}


def text(content):
    if isinstance(content,list):content=' '.join(str(v.get('text','')) for v in content if isinstance(v,dict))
    # Document source bodies must not masquerade as user intent.
    return str(content).split("\n\nTeks berikut berhasil diekstrak dari lampiran '",1)[0]


def wants_short(text):
    """Length preferences, not a quoted word or a negated brevity request."""
    text=str(text).lower().replace('’', "'")
    text=re.sub(r'```[\s\S]*?```|`[^`]*`|"[^"\n]*"|“[^”\n]*”', ' ', text)
    text=re.sub(r"\b(?:jangan|tidak|bukan|nggak|gak|ga|tak|do not|don't|not|never)\s+(?:(?:terlalu|terlalu\s+dibuat|dibuat|dibikin|terkesan|terkesan\s+terlalu|terlalu\s+singkat|too|be|make it|keep it)\s+)*(?:singkat|pendek|ringkas|concise|brief|short)\b", ' ', text)
    return bool(re.search(r'\b(?:singkat|pendek|ringkas|concise|brief|one sentence|satu kalimat)\b',text))


def classify(messages, *, task=False):
    users=[m for m in messages if m.get('role')=='user']
    current=text(users[-1].get('content','')) if users else ''
    lower=current.lower();score=0;signals=[]
    def add(name,points):
        nonlocal score
        score+=points;signals.append(name)
    domain_text=re.sub(r'\b(?:kode|code)\s+(?:verifikasi|verification|otp|voucher|kupon|coupon|promo|produk|product|pesanan|order|pos|postal)\b|\b(?:verification|postal|coupon|product|order)\s+code\b','',lower)
    domain=next((k for k,p in DOMAINS.items() if re.search(p,domain_text)),'general')
    transform=bool(re.match(r'^(?:tolong )?(?:translate|terjemahkan|benerin typo|perbaiki typo|rewrite)\b',lower))
    definition=bool(re.match(r'^(?:apa itu|what is|define)\b',lower))
    analysis=bool(re.search(r'\b(?:analisis|analisa|analysis|analy[sz]e|bandingkan|bandingin|compare|trade.?offs?|kenapa|why|rencana|plan|strategi|strategy|pricing|positioning|gtm|pilih|mending|risiko|risk|rekomendasi|recommend|hitung|calculate|analiza|analizar|compara|comparar|riesgo|recomienda)\b|分析|比较|风险',lower))
    constraints=len(re.findall(r'\b(?:budget|modal|tanpa|without|jangan|harus|must|only|hanya|maksimal|maximum|constraint|presupuesto|sin|debe|solo|máximo)\b|预算|不要|必须|仅限',lower))
    if domain in ('business','coding') and not (transform or definition):add(domain,2)
    if analysis and not (transform or definition):add('analysis',1)
    if constraints>=2:add('constraints',min(3,(constraints+1)//2))
    if re.search(r'\b(?:mendalam|komprehensif|comprehensive|in.depth|detail(?:ed)?|secara rinci|lengkap|detallado|detallada|profundidad)\b|详细|深入',lower):add('requested_depth',2)
    if re.search(r'\b(?:multi.?file|multi.?document|beberapa (?:file|dokumen)|cross.?file|lintas (?:file|dokumen)|beberapa langkah|multi.?step|varios documentos|varios archivos)\b|多个文件|跨文件',lower):add('synthesis',3)
    blocks=users[-1].get('content',[]) if users else []
    images=sum(1 for b in blocks if isinstance(b,dict) and b.get('type')=='image_url') if isinstance(blocks,list) else 0
    # The current upload also appears in the persistent source context. Count it once.
    source_counts={}
    for message in users[-5:]:
        content=message.get('content','')
        if isinstance(content,list):content='\n'.join(str(b.get('text','')) for b in content if isinstance(b,dict))
        names=[(extracted or stored).strip() for extracted,stored in re.findall(r"Teks berikut berhasil diekstrak dari lampiran '([^']+)'|(?:^|\n)File: ([^\n]+)",str(content))]
        for name,count in Counter(names).items():source_counts[name]=max(source_counts.get(name,0),count)
    source_count=sum(source_counts.values())
    if source_count>=2:add('multiple_sources',3)
    elif source_count or images:add('attachment',1)
    if images and analysis:add('visual_reasoning',1)
    if re.search(r'\b(?:json|schema|skema|structured|tabel|table)\b',lower) and analysis:add('structure',1)
    if task:add('execution',1)
    if len(current)>3500 and not transform:add('extended_context',1)
    followup=bool(len(current)<220 and re.search(r'^(?:lanjut|terus|kenapa|knp|yang|yg|kalau|lebih|buat versi|koreksi|bukan|maksud|actually|continue|what about|and |why|continúa|más detalle|corrige)\b|^(?:继续|更详细|不是|改成)',lower))
    if followup and len(users)>1:
        prior=classify(users[-4:-1])
        score=max(score,prior['score']);domain=prior['domain'] if domain=='general' else domain
        signals.append('followup')
    difficulty='EXPERT' if score>=7 else 'HARD' if score>=3 else 'NORMAL'
    if (score==0 and len(current)<250 and (transform or re.search(r'^(?:halo|hai|hi|hello|thanks|makasih|terima kasih|apa itu|what is|berapa|what time|2\s*[+*])\b',lower))):difficulty='EASY'
    explicit_short=wants_short(current)
    depth='QUICK' if explicit_short or difficulty=='EASY' else 'EXPERT' if difficulty=='EXPERT' else 'DEEP' if difficulty=='HARD' else 'STANDARD'
    if getattr(messages,'quality_retry',False):
        difficulty='EXPERT' if difficulty=='EXPERT' else 'HARD'
        signals.append('validation_repair')
    return {'difficulty':difficulty,'depth':depth,'score':score,'signals':signals,'domain':domain,
            'model':'gpt-6.1-sol' if difficulty in ('HARD','EXPERT') else 'gpt-6-luna',
            'effort':'medium' if difficulty in ('NORMAL','EXPERT') else 'low',
            'output_tokens':{'QUICK':1200,'STANDARD':3500,'DEEP':7000,'EXPERT':11000}[depth]}


PLAYBOOKS={
    'general':'Answer the actual request directly, follow its language and latest correction, preserve relevant context and useful depth. Avoid filler and invented actions.',
    'business':'Use the stated goal and constraints. Distinguish facts from assumptions; examine unit economics, positioning, alternatives, risks and tradeoffs where relevant, then recommend practical next steps.',
    'coding':'Reason from supplied code/errors. Distinguish confirmed causes from hypotheses, preserve interfaces and explain a minimal verifiable fix. Never invent APIs or claim execution.',
    'research':'Separate sourced facts from inference. Claim freshness only from actual supplied Search results, preserve attribution and acknowledge material gaps.',
    'documents':'Ground conclusions in the supplied sources. Identify source conflicts and missing information. Never invent document contents or claim a downloadable file exists without an artifact.',
}


def playbook(profile):return PLAYBOOKS.get(profile['domain'],PLAYBOOKS['general'])


def selected_math_profile(messages, profile):
    """Increase selected Chat reasoning for mathematical tasks, never switch models.

    Keep autonomous planning and legacy model routing unchanged. Source text and
    quoted transformations are evidence, not a request to solve their contents.
    """
    users = [m for m in messages if m.get('role') == 'user']
    if not users:
        return profile
    current = text(users[-1].get('content', '')).lower()
    if re.match(r'^(?:tolong )?(?:translate|terjemah(?:kan)?|rewrite)\b', current):
        return profile
    if re.match(r'^(?:apa itu|what is|define)\b', current) and not re.search(r'[0-9=²³^∫∑∏]|\\(?:int|sum|prod)\b', current):
        return profile
    math = bool(re.search(
        r'\b(?:integral|integrate|integrasikan|turunan|derivative|'
        r'persamaan|equation|ketaksamaan|inequality|rekurensi|recurrence|'
        r'probabilitas|probability|kombinatorik|combinatorics|eigenvalue|eigenvalues|'
        r'determinan|determinant|kongruensi|congruence|teorema|theorem)\b|[∫∑∏]|\\(?:int|sum|prod)\b'
        r'|\b(?:buktikan|pembuktian|prove|proof|limit|lim)\b.{0,160}(?:[=²³^→]|\b(?:bilangan|integer|prima|prime|real|rational|matrix|matriks|x|n)\b)'
        r'|\b(?:ekspektasi|expected (?:waiting time|number))\b.{0,160}\b(?:koin|coin|lemparan|tosses|rolls|dadu)\b'
        r'|\bpeluang\b.{0,160}\b(?:bola|dadu|koin|kartu|tanpa pengembalian|acak)\b', current))
    if not math and len(current) < 220 and re.match(
            r'^(?:lanjut|terus|kenapa|knp|yang|yg|kalau|koreksi|bukan|maksud|actually|continue|what about|why)\b', current):
        prior = selected_math_profile(users[:-1], profile) if len(users) > 1 else profile
        math = prior.get('domain') == 'math'
    if not math:
        return profile
    profile = dict(profile)
    profile.update(domain='math', difficulty='EXPERT' if profile['difficulty']=='EXPERT' else 'HARD')
    if profile['depth'] not in ('QUICK', 'EXPERT'):
        profile['depth'] = 'DEEP'
    profile['signals'] = [*profile['signals'], 'mathematical_reasoning']
    return profile


PLAYBOOKS['math'] = (
    'For mathematical problems, give a checkable solution: state the domain and assumptions, '
    'show the essential equations and justified derivation, then the result. This is a concise '
    'public solution, not private internal deliberation. Check by substitution, boundary cases '
    'or an independent method where practical; check units and distinguish exact values from '
    'approximations. Keep symbols, event names and target quantities consistent from the '
    'problem statement through equations and conclusion. Define probability states precisely, '
    'including overlap. For proofs, distinguish necessary from sufficient conditions; verify '
    'that a counterexample satisfies every hypothesis and actually violates the conclusion. '
    'When correcting an answer, recheck dependent steps and the final result. '
    'For proofs, justify each implication and check excluded or extraneous '
    'solutions. If the premise is false, give a counterexample rather than inventing a proof. '
    'Respect a requested brief final answer while still checking it internally. Never claim '
    'code execution or guaranteed correctness. Use LaTeX delimiters for mathematical notation.'
)
