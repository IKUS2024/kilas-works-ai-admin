"""One constrained semantic fallback for incomplete or unfamiliar Finance wording."""
import uuid
import requests
import finance_ai_safety as safety
from finance_semantics import interpret

INTENTS=('unknown','cashflow','balances','customers','projects','accounts','categories','branches','invoices',
         'receivables','reminder','recurring_list','create_income','create_expense','customer','recurring','invoice',
         'create_account','create_category','create_branch','exchange')
SLOTS=('name','phone','email','notes','amount','currency','date','description','account','category','project','customer',
       'counterparty_name','cadence','end_on','due_date','issue_date','item_description','quantity',
       'period','direction','account_type','opening_balance','from_account','to_account','from_amount','to_amount')


def understand(b,u,text):
    import finance_assistant_flow as flow
    import finance_draft_interpreter as draft
    from finance_query_plan import plan,execute,RESOURCES
    if not safety.allow_attempt(u,b,'ai'):return None
    try:data=interpret(text,INTENTS,SLOTS)
    except (ValueError,requests.RequestException,TypeError,KeyError):return None
    intent=data['intent'];slots=data['slots']
    if intent=='unknown':return None
    resource='recurring' if intent=='recurring_list' else intent
    if resource in RESOURCES and intent!='recurring':
        flow.authorize(b,u,'ANALYST',write=False)
        p=plan(b,u,text);p['resource']=resource
        for key in ('account','customer','project','category'):
            if key in slots:p[key]=slots[key]
        if 'period' in slots:
            from finance_semantics import period_patch
            period=period_patch(slots['period'])
            if period:p['period']=period
        answer=execute(b,u,p);answer['query_context']=flow.seal_query(b,u,{'plan':p});return answer
    try:flow.authorize(b,u,'OPERATOR')
    except flow.f.FinanceError as exc:
        if str(exc) not in ('all_branches_read_only','branch_required'):raise
        return dict(kind='branch_choice',message='Perubahan ini untuk cabang mana?',text=text,
                    branches=[dict(id=r['id'],name=r['name']) for r in flow.branches.list_branches(b,u) if r['is_active']])
    if intent.startswith('create_') and intent not in ('create_income','create_expense') or intent=='exchange':
        from finance_conversation_actions import start
        initial=start(b,u,intent)
    elif intent=='customer':
        initial=flow.review(b,u,dict(action=intent,nonce=uuid.uuid4().hex,values={'name':'','phone':'','email':'','notes':''}))
    elif intent=='invoice':
        from finance_assistant_invoice import start
        initial=start(b,u,'buat invoice')
    else:
        values=dict(amount='',currency='',date='' if intent=='recurring' else flow.proposed_date('hari ini'),
                    account_id='',category_id='',description='',project_id='',counterparty_name='')
        if intent=='recurring':values.update(name='',cadence='',end_on='')
        else:values['customer_id']=''
        initial=flow.review(b,u,dict(action=intent,nonce=uuid.uuid4().hex,values=values))
    context=flow.unseal(b,u,initial['context'],'review')
    allowed={draft.REFERENCES.get(k,k) for k in slots}
    if not allowed.issubset(context['values']):return None
    try:values=draft.resolve(slots,context,initial['fields'])
    except ValueError:return initial
    return flow.review(b,u,context,values)


def pending_turn(b,u,message,context,current,query_context=''):
    """Distinguish a draft edit from an independent intent before slot_reply.

    Reuse the normal query signals and the constrained semantic interpreter.
    A model can select a read plan, never confirmation authority. New writes
    require explicit cancellation of the current draft instead of replacing it.
    """
    import finance_assistant_flow as flow
    import finance_draft_interpreter as draft
    from finance_semantics import normalize
    from finance_query_plan import RESOURCES,plan,execute
    text=normalize(message)
    updates=draft.deterministic(message,context,current['fields'])
    # Exact current select options are data, not independent account/category commands.
    if any(message.strip().casefold() in (o['label'].casefold(),o['label'].split('·')[0].strip().casefold())
           for field in current['fields'] for o in field.get('options',[])):
        return None,updates,True
    # Explicit literal field edits remain edits even when a name contains Finance words.
    literal_edit=(bool(updates) and set(updates)<= {'name','phone','email','notes','description','counterparty_name','end_on'}
                  and updates==draft.deterministic(message,context,current['fields'],anchored=True))
    if not literal_edit and flow.is_read_query(b,u,text,query_context):
        return flow.answer(b,u,text,query_context),{},False
    _,explicit_write,schedule=flow.message_intents(text)
    from finance_conversation_actions import route
    independent_command=bool(route(b,u,text,classify_only=True)) if not literal_edit else False
    independent_command=independent_command or (schedule and context['action']!='recurring')
    amount_in_sentence=set(updates)=={'amount'} and message.strip()!=updates['amount'].strip() and flow.FINANCE_DOMAIN.search(text)
    if updates and not explicit_write and not independent_command and not amount_in_sentence:return None,updates,True
    read_intents=tuple('recurring_list' if r=='recurring' else r for r in RESOURCES)
    reverse={v:k for k,v in draft.REFERENCES.items()}
    slots=tuple(dict.fromkeys(SLOTS+tuple(reverse.get(k,k) for k in context['values'])))
    try:
        if not safety.allow_attempt(u,b,'ai'):raise ValueError('rate_limited')
        data=interpret(message,('unknown','continue_draft','new_command')+read_intents,slots,context={
            'task':'Route the current turn: continue_draft edits the active draft; new_command starts a separate Finance write; resource intents are independent read-only queries. Never treat a report or balance query as a missing field. Confirmation/cancel are handled only by the server.',
            'action':context['action'],'operation':context.get('operation'),
            'awaiting':context.get('awaiting') or current.get('next_field'),
            'editable_fields':[{'name':reverse.get(field['key'],field['key']),'missing':not bool(field['value'])} for field in current['fields']],
        })
    except (ValueError,requests.RequestException,TypeError,KeyError):
        data={'intent':'unknown','slots':{}}
    intent=data['intent']
    if intent in read_intents:
        flow.authorize(b,u,'ANALYST',write=False)
        previous=flow.unseal_query(b,u,query_context).get('plan',{}) if query_context else {}
        p=plan(b,u,text,previous);p['resource']='recurring' if intent=='recurring_list' else intent
        for key in ('account','customer','project','category'):
            if key in data['slots']:p[key]=data['slots'][key]
        if 'period' in data['slots']:
            from finance_semantics import period_patch
            period=period_patch(data['slots']['period'])
            if period:p['period']=period
        result=execute(b,u,p);result['query_context']=flow.seal_query(b,u,{'plan':p})
        return result,{},False
    if intent=='new_command' or (explicit_write or independent_command) and intent!='continue_draft':
        return dict(kind='answer',message='Ini perintah Finance baru. Draft sebelumnya belum disimpan. Balas “batal” untuk membatalkannya, lalu kirim perintah baru tadi.'),{},False
    if intent=='continue_draft':
        allowed={draft.REFERENCES.get(k,k) for k in data['slots']}
        if allowed.issubset(context['values']):return None,data['slots'] or updates,True
    # An unavailable/uncertain model must not pour arbitrary text into a name or amount.
    return None,{},False
