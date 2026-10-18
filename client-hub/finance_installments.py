"""Finite cash-basis purchase plans. Save schedules only; paid bills debit once."""
import calendar,hashlib,json,re
from datetime import date
import db,finance_service as finance,finance_branches as branches


def month_date(first,offset):
    value=date.fromisoformat(first);months=value.year*12+value.month-1+offset
    year,month=divmod(months,12);month+=1
    try:return date(year,month,min(31 if value.day==calendar.monthrange(value.year,value.month)[1] else value.day,calendar.monthrange(year,month)[1])).isoformat()
    except (ValueError,OverflowError):raise finance.FinanceError('installment_schedule_invalid') from None


def schedule(total,*,duration,unit,frequency,first_date,count=None,per_payment=None,custom_dates=None):
    finance._money(total,positive=True)
    try:duration=int(duration)
    except (ValueError,TypeError):raise finance.FinanceError('installment_schedule_invalid') from None
    if unit not in ('MONTHS','YEARS') or not 1<=duration<=120:raise finance.FinanceError('installment_schedule_invalid')
    months=duration*(12 if unit=='YEARS' else 1)
    if months>120:raise finance.FinanceError('installment_schedule_invalid')
    first=finance._date(first_date)
    if frequency=='CUSTOM':
        if not isinstance(custom_dates,list) or not 2<=len(custom_dates)<=120:raise finance.FinanceError('installment_schedule_invalid')
        dates=[finance._date(v) for v in custom_dates]
        if dates!=sorted(set(dates)) or dates[0]!=first or dates[-1]>=month_date(first,months):raise finance.FinanceError('installment_schedule_invalid')
    else:
        interval={'MONTHLY':1,'QUARTERLY':3,'YEARLY':12}.get(frequency)
        if not interval:raise finance.FinanceError('installment_schedule_invalid')
        dates=[month_date(first,n) for n in range(0,months,interval)]
    if not 2<=len(dates)<=120 or (count not in (None,'') and str(count)!=str(len(dates))):raise finance.FinanceError('installment_schedule_invalid')
    base=finance._money(per_payment,positive=True) if per_payment is not None else total//len(dates)
    final=total-base*(len(dates)-1)
    if base<1 or final<1:raise finance.FinanceError('installment_amount_invalid')
    return months,[{'due_on':day,'amount_minor':final if i==len(dates)-1 else base} for i,day in enumerate(dates)]


def allocate_payments(splits,payments):
    remaining=[dict(v) for v in splits];result=[]
    for payment in payments:
        total=sum(v['amount_minor'] for v in remaining);amount=payment['amount_minor']
        values=[amount*v['amount_minor']//total for v in remaining]
        extra=amount-sum(values)
        order=sorted(range(len(values)),key=lambda i:(-(amount*remaining[i]['amount_minor']%total),i))
        for i in order[:extra]:values[i]+=1
        result.append([dict(category_id=v['category_id'],amount_minor=values[i]) for i,v in enumerate(remaining) if values[i]])
        for i,value in enumerate(values):remaining[i]['amount_minor']-=value
    if any(v['amount_minor'] for v in remaining):raise finance.FinanceError('installment_amount_invalid')
    return result


def get(business_id,ident,actor):
    finance._scope(business_id,actor)
    return db.query_one('SELECT * FROM finance_installment_plans WHERE business_id=?'+branches.predicate('')+' AND id=?',(business_id,finance._id(ident)))


def create(business_id,actor,*,amount_minor,currency,account_id,category_id,purchase_on,submission_key,
           duration,unit,frequency,first_date,count=None,per_payment=None,custom_dates=None,
           splits=None,notes=None,payee=None,receipt=None):
    import finance_expense_entries as expense
    if not isinstance(submission_key,str) or not re.fullmatch('[a-f0-9]{32}',submission_key):raise finance.FinanceError('expense_submission_invalid')
    months,payments=schedule(amount_minor,duration=duration,unit=unit,frequency=frequency,first_date=first_date,count=count,per_payment=per_payment,custom_dates=custom_dates)
    purchase_on=finance._date(purchase_on)
    if purchase_on>finance.business_today(business_id).isoformat() or payments[0]['due_on']<purchase_on:raise finance.FinanceError('installment_schedule_invalid')
    notes=finance._text(notes,4000);payee=finance._text(payee,160)
    with finance._write(business_id,actor):
        account=finance.get_account(business_id,finance._id(account_id),actor_user_id=actor,active=True)
        if not account or account['currency']!=currency:raise finance.FinanceError('account_currency_mismatch')
        parts=expense.validate(business_id,amount_minor,splits,actor) if splits else [dict(category_id=finance._id(category_id),amount_minor=amount_minor)]
        visible=next((v for v in finance.list_categories(business_id,'EXPENSE',include_children=True,actor_user_id=actor) if v['id']==parts[0]['category_id']),None)
        if not visible or not visible.get('parent_category_id') and finance.list_category_children(business_id,parts[0]['category_id'],actor_user_id=actor):raise finance.FinanceError('subcategory_required')
        payload=dict(total=amount_minor,currency=currency,account=account_id,purchase_on=purchase_on,splits=parts,payments=payments,months=months,frequency=frequency,notes=notes,payee=payee,receipt=receipt['digest'] if receipt else None)
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        prior=db.query_one('SELECT id,actor_user_id,payload_hash FROM finance_installment_plans WHERE business_id=? AND submission_key=?',(business_id,submission_key))
        if prior:
            if prior['actor_user_id']!=actor or prior['payload_hash']!=digest or not get(business_id,prior['id'],actor):raise finance.FinanceError('expense_submission_conflict')
            return prior['id']
        if db.query_one('SELECT 1 FROM finance_expense_entries WHERE business_id=? AND submission_key=?',(business_id,submission_key)):raise finance.FinanceError('expense_submission_conflict')
        branch=branches.write_branch(business_id,actor)
        ident=db.insert_returning_id('INSERT INTO finance_installment_plans(business_id,branch_id,actor_user_id,submission_key,payload_hash,total_minor,currency,account_id,category_id,purchase_on,notes,payee,splits_json,duration_months,schedule,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(business_id,branch,actor,submission_key,digest,amount_minor,currency,account_id,parts[0]['category_id'],purchase_on,notes,payee,json.dumps(parts),months,frequency,finance.repo._now()))
        for index,(payment,allocation) in enumerate(zip(payments,allocate_payments(parts,payments))):
            rule=finance.create_recurring_expense(business_id,f'Cicilan {index+1}/{len(payments)}',payment['amount_minor'],account_id,allocation[0]['category_id'],'MONTHLY',payment['due_on'],end_on=payment['due_on'],counterparty_name=payee,description=notes,actor_user_id=actor,expected_currency=currency)
            db.execute('INSERT INTO finance_installment_items VALUES (?,?,?,?,?,?)',(ident,index,rule,payment['amount_minor'],payment['due_on'],json.dumps(allocation)))
        if receipt:
            expense.receipt_capacity(business_id,len(receipt['raw']))
            db.execute('INSERT INTO finance_installment_receipts VALUES (?,?,?,?,?,?)',(ident,receipt['name'],receipt['mime'],receipt['raw'],len(receipt['raw']),receipt['digest']))
        finance._audit(business_id,actor,'FINANCE_INSTALLMENT_PLAN_CREATED',ident)
        return ident


def apply_payment(business_id,rule_id,transaction_id,actor):
    import finance_expense_entries as expense
    row=db.query_one('SELECT i.allocations_json,p.notes FROM finance_installment_items i JOIN finance_installment_plans p ON p.id=i.plan_id WHERE i.recurring_id=? AND p.business_id=?',(rule_id,business_id))
    if not row:return
    values=json.loads(row['allocations_json'])
    expense.replace(business_id,transaction_id,values if len(values)>1 else [],actor)
    db.execute('UPDATE finance_transactions SET notes=? WHERE id=?',(row['notes'],transaction_id))


def require_rule_amount(rule_id,amount,category_id=None,due_on=None,cadence=None,end_on=None):
    row=db.query_one('SELECT amount_minor,due_on,allocations_json FROM finance_installment_items WHERE recurring_id=?',(rule_id,))
    if row and (row['amount_minor']!=amount or due_on is not None and row['due_on']!=due_on or category_id is not None and category_id!=json.loads(row['allocations_json'])[0]['category_id'] or cadence is not None and (cadence!='MONTHLY' or end_on!=row['due_on'])):raise finance.FinanceError('installment_payment_locked')
