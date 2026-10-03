"""Private deterministic difficulty and depth; no classifier/provider invocation."""
import re

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
    source_names=set()
    for message in users[-5:]:
        content=message.get('content','')
        if isinstance(content,list):content='\n'.join(str(b.get('text','')) for b in content if isinstance(b,dict))
        for extracted,stored in re.findall(r"Teks berikut berhasil diekstrak dari lampiran '([^']+)'|(?:^|\n)File: ([^\n]+)",str(content)):
            source_names.add((extracted or stored).strip())
    source_count=len(source_names)
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
    explicit_short=bool(re.search(r'\b(?:singkat|pendek|ringkas|concise|brief|one sentence|satu kalimat)\b',lower))
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
