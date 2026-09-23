"""Semantic language boundary; signed server state and services own all authority.

A single constrained interpretation per natural-language turn. The model sees
visible labels, never IDs/tokens, and emits only literal spans from this turn.
"""
import re
import uuid
from difflib import SequenceMatcher
import requests
import finance_ai_safety as safety
import finance_semantics as semantics
import finance_draft_interpreter as draft
import finance_assistant_flow as flow
import finance_conversation_actions as commands
import finance_conversation_live as live
from finance_query_plan import RESOURCES, execute

READS=tuple('recurring_list' if r=='recurring' else r for r in RESOURCES)
WRITES=('customer','create_income','create_expense','recurring','invoice','issue_invoice','record_invoice_payment')+tuple(commands.TITLES)
INTENTS=('unknown','capabilities','continue_draft','continue_query','continue_command','new_command','add_invoice_item','select_document_account')+READS+WRITES
SLOTS=('name','phone','email','notes','amount','currency','date','description','account','category','parent_category','project','customer',
       'invoice','counterparty_name','cadence','end_on','due_date','issue_date','item_description','item_number','quantity','note',
       'period','month','count','direction','account_type','opening_balance','from_account','to_account','from_amount','to_amount',
       'issue','settlement','payment_fraction','target','customer_reference','target_reference','group_by','branch','overdue','aging','due_week','page')
SLOTS+=tuple(group+'_'+key for group,keys in commands.tools.editor.GROUPS.items() for key in keys if (group,key)!=('sender','email'))
TASK=('Understand this Finance conversation before extracting fields. customer creates a customer; customers lists them. '
      'A new/baru customer is an unnamed draft, not a customer named baru. Extract the actual name after conversational labels. '
      'create_income/create_expense record transactions, even with typos in nouns or verbs. A date alone does not make a report. '
      'List questions do not contain a person named after the rest of the question. '
      'With an active draft choose continue_draft only for edits to that draft; choose a read resource for an interruption, '
      'or the specific new write intent for a separate write. Use new_command only when a write is clear but its operation is not. '
      'Never confirm/cancel/save: the server handles explicit confirmation. '
      'continue_query keeps the previous read filters and replaces supplied fields; a new read resource starts a fresh query. '
      'continue_command supplies a missing target for the previous command. '
      'For pronouns referring to the last confirmed customer use customer_reference containing the literal pronoun; '
      'for a previous operation target use target_reference. Never copy context values into slots; only current-message spans. '
      'Unpaid debt is not income or a payment. When the user wants to record a new unpaid amount for a customer, choose invoice '
      'and leave item_description missing if its purpose is unknown. Asking who owes money is receivables. '
      'Projects can be listed or linked to a transaction; project creation is unsupported. FX records an exchange, never sends money. '
      'edit_customer changes an existing customer name/phone/email/notes; deactivate_customer is the reviewed safe delete for a customer. '
      'For edit/delete/void/rename operations, target is the existing record being changed; resource-specific names may identify that target. '
      'Use visible names to understand references, but return literal user spelling, not IDs. Keep unspecified fields unchanged. '
      'Capabilities means asking what you can do. Unknown means unclear/unsupported/off-topic. '
      'Invoice item additions use add_invoice_item and literal item_description, quantity, amount. '
      'For filters return period/direction/group_by/overdue/aging/due_week/page/count only as literal user words. '
      'For one transaction/invoice/FX record use target with its literal visible reference, or target_reference for the last confirmed record. '
      'Use settlement with the literal request for full payment (lunas/lunasi); the server calculates the outstanding amount. '
      'Use record_invoice_payment for a customer who already paid or is now being settled: Wilson sudah bayar, '
      'atas nama Wilson lunas, yang Putri lunasin. customer holds the literal name; settlement holds any literal '
      'full-settlement/already-paid phrase when no partial amount is specified. Partial payments use amount. '
      'New invoice requests with terbitkan use invoice plus issue containing that literal request. '
      'New invoice requests with sudah bayar use invoice plus settlement; this requests create, issue, then payment review. '
      'While an invoice draft is active, terbitkan sekalian/yang tadi terbitkan is continue_draft with issue, not a new command. '
      'An answer like beli bensin 25 ribu fills item_description=beli bensin AND amount=25 ribu on the SAME item. '
      'untuk beli bensin supplies item_description=beli bensin; bensinnya 25 ribu supplies amount. '
      'Only an EXPLICIT request for another line, such as tambah item oli 50 ribu, uses add_invoice_item. '
      'Debt questions (utang Putri berapa) ALWAYS use receivables, never customer notes. '
      'sisanya berapa, utang dia berapa, kalau yang belum lunas continue the previous customer receivables query; '
      'use continue_query or customer_reference with the literal pronoun. '
      'For recurring creation, name is the literal bill label (internet in biaya internet); do not omit name when it is given. '
      'For recurring schedules like tiap tanggal 10, cadence MUST copy the full literal phrase tiap tanggal 10, and date copies tanggal 10. Never shorten cadence to tiap. '
      'edit_recurring edits an existing recurring rule, including a short correction after creating it. '
      'edit_invoice edits an existing invoice; amount is unit price, quantity and item_description refer to one item. '
      'For multi-item invoices ask which item; item_number is the literal row number the user selects. '
      'Invoice sender_*, recipient_* and payment_* slots edit document details using literal values only. '
      'set_budget creates or updates a monthly category budget using month, category, amount and currency; budgets reads budgets. '
      'A comparison must include BOTH requested periods in the period span. '
      'For a partial payment always use amount, NEVER settlement; setengah/separuh uses payment_fraction. '
      'When correcting a bare amount like eh 250 after 300 ribu, ask for its unit; do not infer a multiplier. '
      'No guessed names, dates, contacts, categories, amounts, or payment status.')


def visible_options(b,u):
    pools={
        'customer':flow.f.list_customers(b,actor_user_id=u),
        'account':flow.f.list_accounts(b,actor_user_id=u),
        'category':flow.f.list_categories(b,include_children=True,actor_user_id=u),
        'project':flow.f.list_finance_projects(b,actor_user_id=u),
        'branch':flow.branches.list_branches(b,u),
        'invoice':flow.f.list_finance_invoices(b,actor_user_id=u),
        'recurring':flow.f.list_recurring_expenses(b,actor_user_id=u),
    }
    return {key:[{k:str(row[k])[:200] for k in ('name','title','invoice_number','currency','direction','status') if k in row}
                 for row in rows[:50] if row.get('is_active',True)] for key,rows in pools.items()}


def last_record(b,u,previous):
    ref=previous.get('last_record',{})
    if ref.get('kind')=='customer':
        row=flow.f.get_customer(b,ref.get('id'),actor_user_id=u)
        return (ref['kind'],row) if row and row['is_active'] else (None,None)
    if ref.get('kind') in ('transaction','invoice','recurring','account','category','branch','fx'):
        row=commands.get_target(b,u,ref['kind'],ref.get('id'))
        return (ref['kind'],row) if row and row.get('is_active',True) else (None,None)
    return None,None


def safe_context(b,u,previous,context=None,current=None):
    state={'task':TASK,'visible_options':visible_options(b,u)}
    if previous.get('document_pending'):
        state['document_pending']='An uploaded document is waiting for an account. select_document_account with the literal account span ONLY if the user selects its account. Balance/report questions still use read intents; a different action uses its own intent.'
    if previous.get('plan'):
        plan=previous['plan']
        state['previous_query']={k:v for k,v in plan.items() if k not in ('transaction','exchange','entity_refs')}
        for key,ident in plan.get('entity_refs',{}).items():
            rows=({'customer':flow.f.list_customers,'account':flow.f.list_accounts,
                   'project':flow.f.list_finance_projects}.get(key))
            records=(flow.f.list_categories(b,include_children=True,actor_user_id=u)
                     if key=='category' else (rows(b,actor_user_id=u) if rows else []))
            if records:
                row=next((r for r in records if r['id']==ident),None)
                state['previous_query'][key]=(row.get('name') or row.get('title')) if row else '[tidak tersedia]'
    if previous.get('command'):state['previous_command']={'operation':previous['command']['operation'],'missing_field':'target','values':previous['command'].get('slots',{})}
    customer=live.customer(b,u,previous)
    if customer:state['current_customer']={'name':customer['name']}
    kind,row=last_record(b,u,previous)
    if row:
        state['last_confirmed']={'kind':kind,'name':row.get('name') or row.get('invoice_number'),
                                'currency':row.get('currency')}
    if context:
        reverse={v:k for k,v in draft.REFERENCES.items()}
        state.update(action=context['action'],operation=context.get('operation'),
                     missing_field=context.get('awaiting') or current.get('next_field'))
        state['fields']=[]
        for field in current['fields']:
            if field['key'] in ('fingerprint',):continue
            value=field['value']
            if field.get('options'):
                value=next((o['label'] for o in field['options'] if o['value']==value),'')
            elif field['key'].endswith('_id'):continue
            state['fields'].append(dict(name=reverse.get(field['key'],field['key']),value=value,
                missing=field.get('required',True) and not bool(field['value']),
                options=[o['label'] for o in field.get('options',[])[:50]]))
    return state


def classify(b,u,message,previous,context=None,current=None):
    if not safety.allow_attempt(u,b,'ai'):return None
    try:
        slots=SLOTS
        if context:
            reverse={v:k for k,v in draft.REFERENCES.items()}
            slots=tuple(dict.fromkeys(SLOTS+tuple(reverse.get(k,k) for k in context['values'] if not k.endswith('_id') and k!='fingerprint')))
        state=safe_context(b,u,previous,context,current)
        normalized=semantics.normalize(message)
        if normalized.casefold()!=message.casefold():
            state['vocabulary_hint']=normalized
            state['vocabulary_hint_rule']='Understanding only. Slots must still copy literal text from the original message.'
        try:return semantics.interpret(message,INTENTS,slots,state)
        except ValueError as exc:
            if str(exc)!='invalid_result' or not safety.allow_attempt(u,b,'ai'):raise
            safety.event('invalid_result')
            # One bounded repair consumes the same existing user/business quota.
            # The repaired output must pass the unchanged literal-span validator.
            state['validation_feedback']='The previous interpretation was rejected. Return only allowed keys, string values copied verbatim from the CURRENT message, and an allowed intent. Omit inferred currency and normalized dates/enums. Do not copy values from context.'
            return semantics.interpret(message,INTENTS,slots,state)
    except (ValueError,requests.RequestException,TypeError,KeyError):return None


def social_response(message):
    """Natural small-talk replies only; no Finance state, services, or writes are touched."""
    text=re.sub(r'[^a-z0-9 ]+',' ',semantics.normalize(message).casefold())
    text=' '.join(text.split())
    greetings={
        'hai','halo','hi','hello','hey','pagi','siang','sore','malam',
        'selamat pagi','selamat siang','selamat sore','selamat malam'
    }
    thanks={'makasih','makasi','terima kasih','thanks','thank you','thx'}
    if text in greetings:
        return dict(kind='answer',title='Kilas Finance',
                    message='Halo! Saya siap membantu. Kamu bisa langsung ceritakan kebutuhan Finance-mu, misalnya mencatat transaksi, membuat invoice, mengecek piutang, atau melihat laporan.')
    if text in thanks:
        return dict(kind='answer',title='Kilas Finance',
                    message='Sama-sama. Kalau ada yang ingin dicek atau dicatat di Finance, langsung sampaikan saja.')
    if text in ('apa kabar','gimana kabar','bagaimana kabar','how are you'):
        return dict(kind='answer',title='Kilas Finance',
                    message='Baik, terima kasih. Saya siap membantu urusan Finance-mu. Mau cek data, membuat pencatatan, atau melanjutkan pekerjaan yang tadi?')
    return None


def uncertain():
    return dict(kind='clarification',title='Kilas Finance',message=(
        'Saya belum menangkap maksud Finance dari pesan itu. Kamu bisa langsung tulis kebutuhannya, '
        'misalnya “catat pengeluaran 200 ribu”, “siapa yang belum bayar?”, atau “buat invoice untuk Putri”. '
        'Belum ada data yang diubah.'))


def manual_fallback(pending=False):
    message=('Saya belum bisa memproses permintaan ini dengan aman saat ini. Tidak ada data yang diubah. '
             'Mohon lakukan tindakan ini melalui menu Finance secara manual, atau coba lagi nanti.')
    if pending:message+=' Draft yang tadi belum disimpan.'
    return dict(kind='clarification',title='Kilas Finance',message=message)


def manual_only_request(text):
    """Keep bulk/destructive operations out of conversational execution."""
    low=semantics.normalize(text).casefold()
    destructive=bool(re.search(r'\b(reset|kosongkan|bersihkan|hapus|delete)\b',low))
    bulk=bool(re.search(r'\b(semua|seluruh|keseluruhan)\b',low))
    finance_object=bool(re.search(r'\b(finance|data|transaksi|invoice|customer|rekening|akun|kategori|cabang)\b',low))
    return destructive and bulk and finance_object


def pending_uncertain(current):
    key=current.get('next_field')
    spec=next((r for r in current.get('fields',[]) if r.get('key')==key),None)
    if not spec:return uncertain()
    examples={'date':'“hari ini” atau “20 September 2026”','due_date':'“30 September 2026”',
              'issue_date':'“hari ini”','amount':'“200 ribu”','account_id':'nama rekening, misalnya “BCA”',
              'category_id':'nama kategori, misalnya “Transport”','invoice_id':'nomor invoice yang dimaksud',
              'name':'nama yang ingin digunakan','cadence':'“Bulanan” atau “Mingguan”'}
    example=examples.get(key)
    message='Saya masih menunggu '+spec.get('label','data yang diminta').lower()+'.'
    if example:message+=' Tulis '+example+'.'
    message+=' Kalau ingin pindah ke pekerjaan lain, langsung tulis perintah barunya.'
    return dict(kind='clarification',title=current.get('title') or 'Kilas Finance',message=message)


def read(b,u,intent,slots,previous):
    flow.authorize(b,u,'ANALYST',write=False)
    if intent=='continue_query':
        if not previous.get('plan'):return uncertain()
        p=dict(previous['plan']);p.pop('awaiting',None)
    else:p={'resource':'recurring' if intent=='recurring_list' else intent,'period':semantics.period_patch('bulan ini'),'page':0}
    for key in ('account','category','customer','project','branch','invoice'):
        if key in slots:
            p[key]=slots[key]
            p['entity_refs']={k:v for k,v in p.get('entity_refs',{}).items() if k!=key}
    if slots.get('branch','').casefold() in ('semua cabang','all branches','gabungan'):p['branch']='*'
    if 'target' in slots or 'target_reference' in slots:
        kind={'transactions':'transaction','invoices':'invoice','exchanges':'fx'}.get(p['resource'])
        if not kind:return uncertain()
        if 'target_reference' in slots:
            last_kind,row=last_record(b,u,previous)
            if last_kind!=kind:return uncertain()
        else:
            found=semantics.entity_options(commands.targets(b,u,kind),slots['target'])
            if len(found)!=1:return uncertain()
            row=found[0]
        key={'transaction':'transaction','invoice':'invoice','fx':'exchange'}[kind]
        p[key]=row['invoice_number'] if kind=='invoice' else row['id']
    if 'customer_reference' in slots:
        row=live.customer(b,u,previous)
        if not row:return live.unavailable('Customer')
        p['customer']=row['name']
        p.setdefault('entity_refs',{})['customer']=row['id']
    if 'period' in slots:
        period=semantics.period_patch(slots['period'])
        if not period:return uncertain()
        p['period']=period
        if p['resource']=='recurring':p['forecast']=period['mode']!='all'
    if 'currency' in slots:
        code=flow.currency_hint(slots['currency'])
        if slots['currency'].casefold() in ('semua mata uang','all currencies'):p.pop('currency',None)
        elif code:p['currency']=code
        else:return uncertain()
    if 'direction' in slots:
        word=semantics.normalize(slots['direction']).casefold()
        direction={'pemasukan':'INCOME','pendapatan':'INCOME','pengeluaran':'EXPENSE','arus kas':''}.get(word)
        if direction is None:return uncertain()
        p['direction']=direction
    if 'group_by' in slots:
        group={'customer':'customer','pelanggan':'customer','proyek':'project','kategori':'category','cabang':'branch'}.get(semantics.normalize(slots['group_by']).casefold())
        if not group:return uncertain()
        p['group_by']=group
    for key in ('overdue','aging','due_week','count'):
        if key in slots:p[key]=True
    if 'page' in slots:p['page']=min(100000,p.get('page',0)+1)
    result=execute(b,u,p)
    remembered={'plan':p}
    if p.get('entity_refs',{}).get('customer'):remembered['customer_ref']=p['entity_refs']['customer']
    elif previous.get('customer_ref'):remembered['customer_ref']=previous['customer_ref']
    if previous.get('last_record'):remembered['last_record']=previous['last_record']
    result['query_context']=flow.seal_query(b,u,remembered)
    return result


def apply_slots(b,u,initial,slots,previous):
    context=flow.unseal(b,u,initial['context'],'review')
    context['conversation']={k:previous[k] for k in ('last_record','plan','customer_ref') if k in previous}
    slots=dict(slots)
    if 'payment_fraction' in slots:
        fraction=slots.pop('payment_fraction').strip().casefold()
        if context['action']!='record_invoice_payment' or fraction not in ('setengah','separuh','setengah dulu','separuh dulu'):return uncertain()
        context['settle_half']=True;context['settle_full']=False
    if 'customer_reference' in slots:
        row=live.customer(b,u,previous)
        if not row or 'customer_id' not in context['values']:return live.unavailable('Customer')
        context['values']['customer_id']=str(row['id']);slots.pop('customer_reference')
    issue=slots.pop('issue',None);settlement=slots.pop('settlement',None)
    if issue and context['action']!='invoice':return uncertain()
    if settlement and context['action'] not in ('invoice','record_invoice_payment'):return uncertain()
    if context['action']=='invoice':
        from finance_assistant_invoice import requested_steps
        requested_steps(context,issue,settlement)
        initial=flow.review(b,u,context)
    elif settlement and not slots.get('amount'):context['settle_full']=True
    if context['action']=='record_invoice_payment' and slots.get('amount'):context['settle_full']=False;context['settle_half']=False
    if context['action']=='invoice' and not context['values'].get('customer_id') and 'customer' not in slots:
        row=live.customer(b,u,previous)
        if row:context['values']['customer_id']=str(row['id'])
    if context['action']=='record_invoice_payment' and 'target_reference' in slots:
        kind,row=last_record(b,u,previous)
        if kind!='invoice':return live.unavailable('Invoice')
        context['values']['invoice_id']=str(row['id']);slots.pop('target_reference')
    if context['action']=='record_invoice_payment' and 'target' in slots:slots['invoice']=slots.pop('target')
    if context['action']=='record_invoice_payment' and 'customer' in slots:
        found=semantics.entity_options(flow.f.list_customers(b,actor_user_id=u),slots['customer'])
        if len(found)==1:
            context['values']['customer_id']=str(found[0]['id']);context['values']['invoice_id']=''
            slots.pop('customer')
            initial=flow.review(b,u,context)
            if initial['kind']!='review':return initial
            context=flow.unseal(b,u,initial['context'],'review')
    allowed={draft.REFERENCES.get(k,k) for k in slots}
    if not allowed.issubset(context['values']):return uncertain()
    try:values=draft.resolve(slots,context,initial['fields'])
    except ValueError:
        # One unclear field must not discard the other grounded fields in the message.
        # Keep every failed field empty and require it before confirmation.
        values=dict(context['values']);missing=[]
        for semantic,raw in slots.items():
            key=draft.REFERENCES.get(semantic,semantic)
            try:values=draft.resolve({semantic:raw},dict(context,values=values),initial['fields'])
            except ValueError:
                values[key]='';missing.append(key)
        if missing:context['awaiting']=missing[0]
        return flow.review(b,u,context,values)
    return flow.review(b,u,context,values)


def start(b,u,intent,slots,previous):
    try:flow.authorize(b,u,'OPERATOR')
    except flow.f.FinanceError as exc:
        if str(exc) not in ('all_branches_read_only','branch_required'):raise
        return dict(kind='branch_choice',message='Perubahan ini untuk cabang mana?',
                    branches=[dict(id=r['id'],name=r['name']) for r in flow.branches.list_branches(b,u) if r['is_active']])
    slots=dict(slots)
    if intent=='continue_command':
        intent=previous.get('command',{}).get('operation')
        if intent not in WRITES:return uncertain()
        slots={**previous['command'].get('slots',{}),**slots}
    if intent in commands.TITLES or intent=='issue_invoice':
        row=None
        settle_after=bool(slots.pop('settlement',None)) if intent=='issue_invoice' else False
        slots.pop('issue',None) if intent=='issue_invoice' else None
        if intent not in ('create_account','create_category','create_subcategory','create_branch','exchange','set_budget'):
            kind=intent.split('_',1)[1]
            if 'target_reference' in slots:
                last_kind,row=last_record(b,u,previous)
                if last_kind!=kind:return uncertain()
                slots.pop('target_reference')
            elif kind=='customer' and 'customer_reference' in slots:
                row=live.customer(b,u,previous)
                slots.pop('customer_reference')
                if not row:return live.unavailable('Customer')
            else:
                raw=slots.pop('target','')
                if not raw and kind in slots:raw=slots.pop(kind)
                found=semantics.entity_options(commands.targets(b,u,kind),raw) if raw else []
                if len(found)==1:row=found[0]
                elif not raw:
                    last_kind,last=last_record(b,u,previous)
                    if last_kind==kind:row=last
            if row is None:
                remembered={'command':{'operation':intent,'slots':slots}}
                if previous.get('last_record'):remembered['last_record']=previous['last_record']
                return dict(kind='clarification',message='Data yang mana? Sebut nama atau nomor yang dimaksud; belum ada perubahan.',
                    choices=[r['name'] for r in commands.targets(b,u,kind)[:8]],query_context=flow.seal_query(b,u,remembered))
        if intent=='issue_invoice':
            from finance_assistant_invoice import review_invoice,issue_fingerprint
            context=dict(action=intent,values={'invoice_id':row['id'],'fingerprint':issue_fingerprint(b,u,row)},nonce=uuid.uuid4().hex)
            if settle_after:context['settle_after']=True
            return review_invoice(b,u,context)
        if intent=='edit_invoice':
            items=flow.f.list_invoice_items(b,row['id'],u)
            item_slots={key:slots[key] for key in ('item_description','quantity','amount') if key in slots}
            index=slots.pop('item_number','')
            if item_slots and len(items)>1 and not index:
                remembered={'command':{'operation':intent,'slots':dict(slots,target=row['name'])}}
                return dict(kind='clarification',message='Item invoice yang mana yang ingin diubah? Sebut nomor itemnya.',
                            preview=[[str(i),item['description']] for i,item in enumerate(items,1)],
                            query_context=flow.seal_query(b,u,remembered))
            if index:
                if not index.isdigit() or not 1<=int(index)<=len(items):return uncertain()
                if int(index)>1:
                    for key,value in item_slots.items():
                        slots.pop(key);slots['item'+str(int(index))+'_'+('description' if key=='item_description' else key)]=value
        initial=commands.start(b,u,intent,row=row)
    elif intent=='customer':
        initial=flow.review(b,u,dict(action=intent,nonce=uuid.uuid4().hex,values=dict(name='',phone='',email='',notes='')))
    elif intent=='invoice':
        from finance_assistant_invoice import start as invoice_start
        initial=invoice_start(b,u,'buat invoice')
    elif intent in ('create_income','create_expense','recurring','record_invoice_payment'):
        if intent=='recurring' and not slots.get('name') and slots.get('description'):
            slots['name']=slots['description'][:160]
        values=dict(amount='',currency='',date='' if intent=='recurring' else flow.proposed_date('hari ini'),
                    account_id='',category_id='',description='')
        if intent=='recurring':values.update(name='',cadence='',end_on='',project_id='',counterparty_name='')
        elif intent=='record_invoice_payment':
            values.update(invoice_id='',customer_id='',date='')
            if not any(k in slots for k in ('invoice','customer','target','target_reference')):
                last_kind,last=last_record(b,u,previous)
                if last_kind=='invoice' and last and last.get('status') in ('ISSUED','PARTIALLY_PAID'):
                    values['invoice_id']=str(last['id'])
        else:values.update(project_id='',customer_id='',counterparty_name='')
        initial=flow.review(b,u,dict(action=intent,nonce=uuid.uuid4().hex,values=values))
    else:return uncertain()
    return apply_slots(b,u,initial,slots,previous)


def contextual_last_action(b,u,text,previous):
    """Resolve short follow-ups against the last confirmed live record.

    This is protocol context, not a stale business snapshot: last_record() always
    re-reads the scoped database row before an action is proposed.
    """
    kind,row=last_record(b,u,previous)
    if not row:return None
    low=' '.join(re.findall(r'[a-z0-9]+',semantics.normalize(text).casefold()))
    if not low or '?' in text or re.search(r'\b(apa|apakah|berapa|kenapa|mengapa|status|cek|lihat|tampilkan)\b',low):
        return None
    words=low.split()
    paid=re.search(r'\b(?:sudah|udah|telah)?\s*(bayar|dibayar|lunas|lunasi|lunasin|pelunasan)\b',low)
    # Only exact protocol-like follow-ups may bypass semantic interpretation.
    # A named customer, explicit amount, negation or partial payment must never
    # settle the last invoice merely because it also contains "bayar".
    exact_issue=re.fullmatch(r'(?:yang tadi |invoice tadi )?(?:terbitkan|issue)(?: sekalian| saja| aja)?',low)
    exact_paid=re.fullmatch(r'(?:yang tadi |invoice tadi )?(?:(?:sudah|udah|telah) (?:bayar|dibayar)|lunas|lunasi|lunasin|pelunasan)(?: saja| aja)?',low)
    if kind=='invoice' and exact_issue:
        slots={'settlement':paid[0]} if paid else {}
        return start(b,u,'issue_invoice',slots,previous)
    if kind=='invoice' and exact_paid:
        if row.get('status')=='DRAFT':
            return start(b,u,'issue_invoice',{'settlement':paid[0]},previous)
        if row.get('status') in ('ISSUED','PARTIALLY_PAID'):
            return start(b,u,'record_invoice_payment',{'settlement':paid[0]},previous)
        if row.get('status')=='PAID':
            totals=flow.f.get_invoice_totals(b,row['id'],u)
            return dict(kind='answer',title='Invoice sudah lunas',
                        message='Invoice '+row['invoice_number']+' sudah berstatus PAID. Sisa tagihan: '+
                                flow.fx.format_money(totals['outstanding_minor'],row['currency'])+'.')
    if re.fullmatch(r'(?:hapus|delete|batalkan|void|nonaktifkan)(?: yang tadi| tadi| itu)(?: saja| aja)?',low):
        operation={'customer':'deactivate_customer','account':'deactivate_account','category':'deactivate_category',
                   'branch':'deactivate_branch','recurring':'deactivate_recurring','transaction':'void_transaction',
                   'invoice':'void_invoice','fx':'void_fx'}.get(kind)
        if operation:return start(b,u,operation,{},previous)
    return None


def message(b,u,text,query_context=''):
    text=flow.operator.text(text,2000);flow.authorize(b,u,write=False)
    previous=flow.unseal_query(b,u,query_context) if query_context else {}
    if draft.NO.fullmatch(text):return dict(kind='answer',state='CANCELLED',message='Baik, draft dibatalkan. Tidak ada data yang diubah.')
    if draft.YES.fullmatch(text):return dict(kind='answer',message='Belum ada draft yang menunggu konfirmasi. Silakan sampaikan apa yang ingin dicatat atau dicek.')
    social=social_response(text)
    if social:return social
    if manual_only_request(text):return manual_fallback()
    contextual=contextual_last_action(b,u,text,previous)
    if contextual:return contextual
    data=classify(b,u,text,previous)
    if data is None:return manual_fallback()
    if data['intent']=='unknown':return uncertain()
    intent=data['intent'];slots=data['slots']
    if intent=='capabilities':return flow.capabilities()
    if intent in READS or intent=='continue_query':return read(b,u,intent,slots,previous)
    result=start(b,u,intent,slots,previous)
    if result.get('kind')=='branch_choice':result['text']=text
    return result


def document_message(b,u,text,query_context=''):
    """Interpret interruptions before reading retained document bytes again."""
    text=flow.operator.text(text,2000);flow.authorize(b,u,write=False)
    previous=flow.unseal_query(b,u,query_context) if query_context else {}
    data=classify(b,u,text,dict(previous,document_pending=True))
    if data is None:return dict(manual_fallback(),keep_pending=True)
    intent,slots=data['intent'],data['slots']
    if intent=='select_document_account':
        rows=semantics.entity_options(flow.f.list_accounts(b,actor_user_id=u),slots.get('account',''))
        if len(rows)==1:return dict(kind='document_selection',account_id=str(rows[0]['id']))
        return dict(kind='clarification',message='Rekening mana yang dimaksud? Pilih rekening yang tersedia.',keep_pending=True)
    if intent in READS or intent=='continue_query':return dict(read(b,u,intent,slots,previous),keep_pending=True)
    if intent=='capabilities':return dict(flow.capabilities(),keep_pending=True)
    if intent in WRITES:return start(b,u,intent,slots,previous)
    return dict(uncertain(),keep_pending=True)


def exact_updates(message,context,current):
    """Resolve an unambiguous answer to the field the server just asked for.

    This is deliberately narrower than intent interpretation: short dates,
    amounts, contacts and one clearly matching visible option can skip an AI
    round-trip, including common spelling noise.
    """
    raw=message.strip();reverse={v:k for k,v in draft.REFERENCES.items()}
    # Free text may be a question, a labelled name, or a compound item/price.
    # Leave it to the semantic boundary instead of copying the whole sentence.
    if re.search(r'[?]|\b(berapa|brp|siapa|apa|bisa|tolong|nama(?:nya)?|customernya)\b',raw,re.I):return {}
    # A unit-bearing correction without a named target belongs to the active
    # single-amount draft. Never reinterpret it as editing a persisted record.
    if 'amount' in context['values'] and not any(k!='amount' and k.endswith('_amount') for k in context['values']):
        correction=re.fullmatch(r'(?:(?:ubah|ganti|koreksi)(?:\s+nominal(?:nya)?)?\s+(?:(?:jadi|ke)\s+)?|(?:eh|maksudnya)\s+)?(.+)',raw,re.I)
        amount=correction[1].strip() if correction else ''
        if flow.AMOUNT.fullmatch(amount):return {'amount':amount}
    matches=[]
    for field in current['fields']:
        for option in field.get('options',[]):
            if raw.casefold() in (option['label'].casefold(),option['label'].split('·')[0].strip().casefold()):
                matches.append((reverse.get(field['key'],field['key']),raw))
    matches=list(dict.fromkeys(matches))
    if len(matches)==1:return dict(matches)
    key=context.get('awaiting') or current.get('next_field')
    spec=next((r for r in current.get('fields',[]) if r.get('key')==key),None)
    if key in ('amount','from_amount','to_amount','opening_balance') and (flow.AMOUNT.fullmatch(raw) or re.fullmatch(r'\d+(?:[.,]\d+)?',raw)):
        return {key:raw}
    if key in ('date','due_date','issue_date','end_on'):
        try:
            if flow.proposed_date(raw,scheduled=context['action'] in ('recurring','invoice'),default_today=False):
                return {key:raw}
        except (ValueError,TypeError):
            pass
    if key=='phone' and re.fullmatch(r'\+?\d[\d -]{4,62}',raw):
        return {'phone':raw}
    if key=='email' and re.fullmatch(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',raw):
        return {'email':raw}
    if spec and spec.get('options') and len(raw)<=120 and '?' not in raw:
        candidate=re.sub(r'^\s*(?:pakai|gunakan|pilih|rekening|akun|kategori|customer|pelanggan|invoice|proyek)\s+','',raw,flags=re.I)
        candidate=re.sub(r'\s+(?:aja|saja|ya|dong)$','',candidate,flags=re.I).strip()
        def norm(value):return re.sub(r'[^0-9a-z]+',' ',value.casefold()).strip()
        value=norm(candidate);ranked=[]
        if value and not re.search(r'\b(buat|catat|tambah|hapus|ubah|cek|lihat|laporan)\b',value):
            for option in spec['options']:
                name=norm(option['label'].split('·')[0].strip())
                if not name:continue
                score=max(SequenceMatcher(None,value,name).ratio(),
                          max((SequenceMatcher(None,value,part).ratio() for part in name.split()),default=0))
                ranked.append((score,option))
        ranked.sort(key=lambda x:x[0],reverse=True)
        if ranked:
            best_score,best_option=ranked[0]
            best_name=norm(best_option['label'].split('·')[0].strip())
            short=min(len(value),len(best_name))<=4
            threshold=0.66 if short else 0.84
            gap=0.20 if short else 0.08
            if best_score>=threshold and (len(ranked)==1 or best_score-ranked[1][0]>=gap):
                return {reverse.get(key,key):best_option['label'].split('·')[0].strip()}
    # Names and descriptions are intentionally semantic, even when short.
    return {}

def pending(b,u,message,context,current,query_context=''):
    previous=dict(context.get('conversation',{}))
    if query_context:previous.update(flow.unseal_query(b,u,query_context))
    social=social_response(message)
    if social:
        social['keep_pending']=True
        social['hint']='Draft sebelumnya tetap tersedia. Kamu bisa melanjutkannya kapan saja atau membatalkannya dengan “batal”.'
        return social,{},False
    if manual_only_request(message):return manual_fallback(pending=True),{},False
    if re.fullmatch(r'\s*(?:yang tadi\s+)?lanjut(?:kan)?(?:\s+yang tadi)?[.! ]*',message,re.I):
        return current,{},False
    updates=exact_updates(message,context,current)
    if updates:
        if context['action']=='record_invoice_payment' and 'amount' in updates:context['settle_full']=False;context['settle_half']=False
        return None,updates,True
    data=classify(b,u,message,previous,context,current)
    if data is None:return manual_fallback(pending=True),{},False
    if data['intent']=='unknown':return pending_uncertain(current),{},False
    intent=data['intent'];slots=data['slots']
    if intent=='capabilities':return flow.capabilities(),{},False
    if intent in READS or intent=='continue_query':return read(b,u,intent,slots,previous),{},False
    if intent=='continue_draft':
        slots=dict(slots)
        if (slots.get('amount') and re.fullmatch(r'\d{1,3}(?:[.,]\d+)?',slots['amount'].strip())
                and re.search(r'\b(ribu|rb|k|juta|jt|miliar)\b|\d(?:k|rb|jt)\b',context['values'].get('amount',''),re.I)):
            return dict(kind='clarification',message='Maksudnya '+slots['amount']+' rupiah atau '+slots['amount']+' ribu? Tulis nominal lengkap supaya tidak salah.'),{},False
        if 'customer_reference' in slots:
            row=live.customer(b,u,previous)
            if not row or 'customer_id' not in context['values']:return live.unavailable('Customer'),{},False
            slots.pop('customer_reference');slots['customer']=row['name']
        if context['action']=='invoice' and ('issue' in slots or 'settlement' in slots):
            result=apply_slots(b,u,current,slots,previous)
            return result,{},False
        if context['action']=='record_invoice_payment':
            if 'payment_fraction' in slots:
                fraction=slots.pop('payment_fraction').strip().casefold()
                if fraction not in ('setengah','separuh','setengah dulu','separuh dulu'):return uncertain(),{},False
                context['settle_half']=True;context['settle_full']=False
            if 'settlement' in slots:context['settle_full']=not bool(slots.get('amount'));slots.pop('settlement')
            if 'amount' in slots:context['settle_full']=False;context['settle_half']=False
            if 'customer' in slots:context['values']['invoice_id']=''
            if not slots:return flow.review(b,u,context),{},False
        if not {draft.REFERENCES.get(k,k) for k in slots}.issubset(context['values']):return uncertain(),{},False
        return None,slots,False
    if intent=='add_invoice_item' and context['action']=='invoice':
        if set(slots)-{'item_description','quantity','amount'} or not slots.get('item_description'):return uncertain(),{},False
        count=1+sum(bool(re.fullmatch(r'item\d+_description',k)) for k in context['values'])
        if count>=100:return uncertain(),{},False
        values=dict(context['values']);prefix='item'+str(count+1)+'_'
        values.update({prefix+'description':slots['item_description'],prefix+'quantity':slots.get('quantity','1'),prefix+'amount':slots.get('amount','')})
        return flow.review(b,u,dict(context,values=values)),{},False
    if intent=='new_command':
        routed=commands.route(b,u,message)
        if routed is not None:
            if routed.get('kind')=='review':routed['message']='Draft sebelumnya tidak disimpan. '+routed['message']
            return routed,{},False
        fresh=classify(b,u,message,previous)
        if fresh and fresh['intent'] in WRITES:
            result=start(b,u,fresh['intent'],fresh['slots'],previous)
            if result.get('kind')=='review':result['message']='Draft sebelumnya tidak disimpan. '+result['message']
            return result,{},False
        return uncertain(),{},False
    if intent in WRITES:
        result=start(b,u,intent,slots,previous)
        if result.get('kind')=='review':result['message']='Draft sebelumnya tidak disimpan. '+result['message']
        return result,{},False
    return uncertain(),{},False
