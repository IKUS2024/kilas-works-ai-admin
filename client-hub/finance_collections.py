"""Read-only collection projections; reuse Phase 3 money/date calculations."""
from datetime import date
from itsdangerous import BadData
import db
import finance_branches as branches
import finance_service as finance
import finance_invoice_view as sharing

SORTS = ('overdue','balance','due','customer')
FILTERS = ('all','overdue','soon')
PAGE_SIZE = 50


def position(business_id, user_id=None, customer_id=None, today=None):
    as_of=finance._date(today or date.today())
    rows=finance.get_report_invoices(business_id,as_of,actor_user_id=user_id,
                                     customer_id=customer_id,open_only=True)
    rows=[r for r in rows if r['outstanding_minor']>0]
    aging=finance.receivables_aging_rows(rows)
    aging['open_invoice_count']=sum(b['invoice_count'] for b in aging['buckets'])
    aging['overdue_invoice_count']=sum(b['invoice_count'] for b in aging['buckets'][1:])
    return dict(as_of=as_of,rows=rows,aging=aging)


def queue(data, sort='overdue', view='all', page=1):
    if sort not in SORTS or view not in FILTERS or type(page) is not int or page<1:
        raise ValueError('invalid_filter')
    rows=data['rows']
    if view=='overdue':rows=[r for r in rows if r['overdue']]
    if view=='soon':
        rows=[r for r in rows if 0<=(date.fromisoformat(r['due_date'])-date.fromisoformat(data['as_of'])).days<=7]
    keys={'overdue':lambda r:(-r['days_late'],r['due_date'],r['id']),
          'balance':lambda r:(-r['outstanding_minor'],r['due_date'],r['id']),
          'due':lambda r:(r['due_date'],r['id']),
          'customer':lambda r:((r['customer_name'] or '').casefold(),r['due_date'],r['id'])}
    rows=sorted(rows,key=keys[sort])
    pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
    page=min(page,pages)
    return dict(rows=rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE],page=page,pages=pages,count=len(rows))


def statement(business_id,customer_id,user_id=None):
    customer=finance.get_customer(business_id,customer_id,actor_user_id=user_id)
    if not customer:raise ValueError('unavailable')
    data=position(business_id,user_id,customer_id)
    business=db.query_one('SELECT business_name FROM businesses WHERE id=?',(business_id,))
    # No internal IDs, notes, account/audit/payment metadata in public statements.
    fields=('invoice_number','issue_date','due_date','status','total_minor','paid_minor','outstanding_minor','days_late','overdue')
    if user_id is not None:
        fields += ('id',)  # Authenticated statement navigation only; never public.
    return dict(issuer=business['business_name'],customer={k:customer[k] for k in ('name','email','phone')},
                as_of=data['as_of'],aging=data['aging'],rows=[{k:r[k] for k in fields} for r in data['rows']])


def create_token(business_id,customer_id,user_id):
    __import__("finance_entitlements").require_write(business_id,user_id)
    if not finance.get_customer(business_id,customer_id,actor_user_id=user_id):raise ValueError('unavailable')
    return sharing.signer().dumps(dict(purpose='finance_customer_statement',business_id=business_id,customer_id=customer_id,branch_id=branches.token_branch(business_id)))


def resolve_token(token, include_branch=False):
    if not isinstance(token,str) or len(token)>1024:raise ValueError('unavailable')
    try:data=sharing.signer().loads(token,max_age=sharing.SHARE_TTL)
    except BadData:raise ValueError('unavailable') from None
    if not isinstance(data,dict) or set(data) not in ({'purpose','business_id','customer_id'}, {'purpose','business_id','customer_id','branch_id'}) or data['purpose']!='finance_customer_statement':
        raise ValueError('unavailable')
    for key in ('business_id','customer_id'):finance._id(data[key])
    branch_id = data.get('branch_id')
    if branch_id is not None:
        branches.get(data['business_id'], branch_id)
    result = (data['business_id'],data['customer_id'])
    return result + (branch_id,) if include_branch else result


def reminder(business_id,invoice_id,user_id,tone='friendly'):
    if tone not in ('friendly','firm'):raise ValueError('invalid_tone')
    invoice=finance.get_finance_invoice(business_id,invoice_id,actor_user_id=user_id)
    if not invoice or invoice['status'] not in ('ISSUED','PARTIALLY_PAID'):raise ValueError('unavailable')
    totals=finance.get_invoice_totals(business_id,invoice_id,actor_user_id=user_id)
    if not totals['overdue'] or totals['outstanding_minor']<=0:raise ValueError('unavailable')
    customer=finance.get_customer(business_id,invoice['customer_id'],actor_user_id=user_id)
    amount='Rp'+format(totals['outstanding_minor'],',').replace(',','.')
    intro='pengingat ramah' if tone=='friendly' else 'kami ingin menindaklanjuti'
    return (f"Halo {customer['name']}, {intro} untuk invoice {invoice['invoice_number']} dengan sisa tagihan "
            f"{amount}, jatuh tempo {invoice['due_date']}. Mohon konfirmasi rencana pembayarannya. "
            'Jika sudah membayar, silakan informasikan agar dapat kami cocokkan. Terima kasih.')
