"""Semantic language boundary; signed server state and services own all authority.

A single constrained interpretation per natural-language turn. The model sees
visible labels, never IDs/tokens, and emits only literal spans from this turn.
"""
import re
import uuid
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
INTENTS=('unknown','capabilities','continue_draft','continue_query','continue_command','new_command','add_invoice_item')+READS+WRITES
SLOTS=('name','phone','email','notes','amount','currency','date','description','account','category','project','customer',
       'invoice','counterparty_name','cadence','end_on','due_date','issue_date','item_description','quantity','note',
       'period','count','direction','account_type','opening_balance','from_account','to_account','from_amount','to_amount',
       'issue','settlement','target','customer_reference','target_reference','group_by','branch','overdue','aging','due_week','page')
TASK=('Understand this Finance conversation before extracting fields. customer creates a customer; customers lists them. '
      'A new/baru customer is an unnamed draft, not a customer named baru. Extract the actual name after conversational labels. '
      'create_income/create_expense record transactions, even with typos in nouns or verbs. A date alone does not make a report. '
      'List questions do not contain a person named after the rest of the question. '
      'With an active draft choose continue_draft only for edits to that draft; choose a read resource for an interruption, '
      'or new_command for a separate write. Never confirm/cancel/save: the server handles explicit confirmation. '
      'continue_query keeps the previous read filters and replaces supplied fields; a new read resource starts a fresh query. '
      'continue_command supplies a missing target for the previous command. '
      'For pronouns referring to the last confirmed customer use customer_reference containing the literal pronoun; '
      'for a previous operation target use target_reference. Never copy context values into slots; only current-message spans. '
      'Unpaid debt is not income or a payment. When the user wants to record a new unpaid amount for a customer, choose invoice '
      'and leave item_description missing if its purpose is unknown. Asking who owes money is receivables. '
      'Projects can be listed or linked to a transaction; project creation is unsupported. FX records an exchange, never sends money. '
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
      'No guessed names, dates, contacts, categories, amounts, or payment status.')


def visible_options(b,u):
    pools={
        'customer':flow.f.list_customers(b,actor_user_id=u),
        'account':flow.f.list_accounts(b,actor_user_id=u),
        'category':flow.f.list_categories(b,actor_user_id=u),
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
    if previous.get('plan'):
        plan=previous['plan']
        state['previous_query']={k:v for k,v in plan.items() if k not in ('transaction','exchange','entity_refs')}
        for key,ident in plan.get('entity_refs',{}).items():
            rows=({'customer':flow.f.list_customers,'account':flow.f.list_accounts,
                   'category':flow.f.list_categories,'project':flow.f.list_finance_projects}.get(key))
            if rows:
                row=next((r for r in rows(b,actor_user_id=u) if r['id']==ident),None)
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
        return semantics.interpret(message,INTENTS,slots,safe_context(b,u,previous,context,current))
    except (ValueError,requests.RequestException,TypeError,KeyError):return None


def uncertain():
    return dict(kind='clarification',title='Kilas Finance',message='Aku khusus membantu Finance dan belum yakin maksudnya. Mau mencatat, mengubah draft, atau melihat data Finance? Belum ada perubahan data.')


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
    elif settlement:context['settle_full']=True
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
    except draft.ReferenceAmbiguous as exc:
        context['awaiting']=exc.key
        initial=flow.review(b,u,context)
        initial['message']='Nama yang dimaksud belum jelas. Pilih data yang tersedia; belum ada perubahan.'
        return initial
    except ValueError:
        for key in ('date','issue_date','due_date'):
            if key in slots and key in context['values']:context['values'][key]=''
        result=flow.review(b,u,context)
        result['message']='Nilainya belum jelas. Lengkapi draft ini; belum ada perubahan data.'
        return result
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
        if intent not in ('create_account','create_category','create_branch','exchange'):
            kind=intent.split('_',1)[1]
            if 'target_reference' in slots:
                last_kind,row=last_record(b,u,previous)
                if last_kind!=kind:return uncertain()
                slots.pop('target_reference')
            else:
                raw=slots.pop('target','')
                found=semantics.entity_options(commands.targets(b,u,kind),raw)
                if len(found)==1:row=found[0]
            if row is None:
                remembered={'command':{'operation':intent,'slots':slots}}
                if previous.get('last_record'):remembered['last_record']=previous['last_record']
                return dict(kind='clarification',message='Data yang mana? Sebut nama atau nomor yang dimaksud; belum ada perubahan.',
                    choices=[r['name'] for r in commands.targets(b,u,kind)[:8]],query_context=flow.seal_query(b,u,remembered))
        if intent=='issue_invoice':
            from finance_assistant_invoice import review_invoice,issue_fingerprint
            return review_invoice(b,u,dict(action=intent,values={'invoice_id':row['id'],'fingerprint':issue_fingerprint(b,u,row)},nonce=uuid.uuid4().hex))
        initial=commands.start(b,u,intent,row=row)
    elif intent=='customer':
        initial=flow.review(b,u,dict(action=intent,nonce=uuid.uuid4().hex,values=dict(name='',phone='',email='',notes='')))
    elif intent=='invoice':
        from finance_assistant_invoice import start as invoice_start
        initial=invoice_start(b,u,'buat invoice')
    elif intent in ('create_income','create_expense','recurring','record_invoice_payment'):
        values=dict(amount='',currency='',date='' if intent=='recurring' else flow.proposed_date('hari ini'),
                    account_id='',category_id='',description='')
        if intent=='recurring':values.update(name='',cadence='',end_on='',project_id='',counterparty_name='')
        elif intent=='record_invoice_payment':values.update(invoice_id='',customer_id='',date='')
        else:values.update(project_id='',customer_id='',counterparty_name='')
        initial=flow.review(b,u,dict(action=intent,nonce=uuid.uuid4().hex,values=values))
    else:return uncertain()
    return apply_slots(b,u,initial,slots,previous)


def message(b,u,text,query_context=''):
    text=flow.operator.text(text,2000);flow.authorize(b,u,write=False)
    previous=flow.unseal_query(b,u,query_context) if query_context else {}
    if draft.NO.fullmatch(text):return dict(kind='answer',state='CANCELLED',message='Oke, dibatalkan.')
    if draft.YES.fullmatch(text):return dict(kind='answer',message='Belum ada draft yang ditinjau untuk disimpan. Mau mencatat apa?')
    data=classify(b,u,text,previous)
    if not data or data['intent']=='unknown':return uncertain()
    intent=data['intent'];slots=data['slots']
    if intent=='capabilities':return flow.capabilities()
    if intent in READS or intent=='continue_query':return read(b,u,intent,slots,previous)
    result=start(b,u,intent,slots,previous)
    if result.get('kind')=='branch_choice':result['text']=text
    return result


def exact_updates(message,context,current):
    """Only whole-message literals/options may bypass semantic interpretation."""
    raw=message.strip();reverse={v:k for k,v in draft.REFERENCES.items()}
    matches=[]
    for field in current['fields']:
        for option in field.get('options',[]):
            if raw.casefold() in (option['label'].casefold(),option['label'].split('·')[0].strip().casefold()):
                matches.append((reverse.get(field['key'],field['key']),raw))
    matches=list(dict.fromkeys(matches))
    if len(matches)==1:return dict(matches)
    key=context.get('awaiting') or current.get('next_field')
    if key in ('amount','from_amount','to_amount','opening_balance') and (flow.AMOUNT.fullmatch(raw) or re.fullmatch(r'\d+(?:[.,]\d+)?',raw)):
        return {key:raw}
    if key in ('date','due_date','issue_date','end_on') and re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):return {key:raw}
    return {}


def pending(b,u,message,context,current,query_context=''):
    previous=dict(context.get('conversation',{}))
    if query_context:previous.update(flow.unseal_query(b,u,query_context))
    updates=exact_updates(message,context,current)
    if updates:
        if context['action']=='record_invoice_payment' and 'amount' in updates:context['settle_full']=False
        return None,updates,True
    data=classify(b,u,message,previous,context,current)
    if not data:return uncertain(),{},False
    intent=data['intent'];slots=data['slots']
    if intent=='capabilities':return flow.capabilities(),{},False
    if intent in READS or intent=='continue_query':return read(b,u,intent,slots,previous),{},False
    if intent=='continue_draft':
        slots=dict(slots)
        if 'customer_reference' in slots:
            row=live.customer(b,u,previous)
            if not row or 'customer_id' not in context['values']:return live.unavailable('Customer'),{},False
            slots.pop('customer_reference');slots['customer']=row['name']
        if context['action']=='invoice' and ('issue' in slots or 'settlement' in slots):
            result=apply_slots(b,u,current,slots,previous)
            return result,{},False
        if context['action']=='record_invoice_payment':
            if 'settlement' in slots:context['settle_full']=True;slots.pop('settlement')
            elif 'amount' in slots:context['settle_full']=False
            if 'customer' in slots:context['values']['invoice_id']=''
        if not {draft.REFERENCES.get(k,k) for k in slots}.issubset(context['values']):return uncertain(),{},False
        return None,slots,False
    if intent=='add_invoice_item' and context['action']=='invoice':
        if set(slots)-{'item_description','quantity','amount'} or not slots.get('item_description'):return uncertain(),{},False
        count=1+sum(bool(re.fullmatch(r'item\d+_description',k)) for k in context['values'])
        if count>=100:return uncertain(),{},False
        values=dict(context['values']);prefix='item'+str(count+1)+'_'
        values.update({prefix+'description':slots['item_description'],prefix+'quantity':slots.get('quantity','1'),prefix+'amount':slots.get('amount','')})
        return flow.review(b,u,dict(context,values=values)),{},False
    if intent in WRITES or intent=='new_command':
        return dict(kind='answer',message='Draft sebelumnya belum disimpan. Balas “batal” untuk membatalkannya sebelum memulai perintah baru.'),{},False
    return uncertain(),{},False
