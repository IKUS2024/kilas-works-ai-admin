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
