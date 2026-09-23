"""Live, scoped reference resolution; conversation tokens remember identity only."""
import finance_service as f
import finance_branches as branches


def unavailable(kind='Data'):
    return dict(kind='clarification',message=kind+' yang tadi sudah tidak tersedia atau tidak aktif di cabang ini. Pilih data aktif yang dimaksud; belum ada perubahan.')


def customer(b,u,previous):
    plan=previous.get('plan',{})
    if plan.get('customer') and not plan.get('entity_refs',{}).get('customer'):return None
    ref=plan.get('entity_refs',{}).get('customer') or previous.get('customer_ref')
    if not ref:
        last=previous.get('last_record',{})
        if last.get('kind')=='customer':ref=last.get('id')
        elif last.get('kind')=='invoice':
            row=f.get_finance_invoice(b,last['id'],u)
            if row:ref=row['customer_id']
        elif last.get('kind')=='transaction':
            row=f.get_transaction(b,last['id'],actor_user_id=u)
            if row and row.get('customer_id'):ref=row['customer_id']
    if not ref:return None
    row=f.get_customer(b,ref,u)
    return row if row and row['is_active'] else None


def open_invoices(b,u,customer_id=None):
    customers={r['id'] for r in f.list_customers(b,actor_user_id=u)}
    rows=f.list_finance_invoices(b,customer_id=customer_id,actor_user_id=u)
    result=[]
    for row in rows:
        if row['customer_id'] not in customers or row['status'] not in ('ISSUED','PARTIALLY_PAID'):continue
        totals=f.get_invoice_totals(b,row['id'],u)
        if totals['outstanding_minor']>0:result.append(dict(row,**totals))
    return result


def no_receivable(b,u,customer_id=None):
    row=f.get_customer(b,customer_id,u) if customer_id else None
    name=' untuk '+row['name'] if row else ''
    remaining=open_invoices(b,u,customer_id)
    if remaining:
        return dict(kind='answer',title='Piutang saat ini',message='Tidak ada invoice aktif yang cocok dengan pilihan/filter tadi'+name+'. Masih ada invoice belum lunas berikut.',
            preview=[[r['invoice_number'],__import__('finance_fx').format_money(r['outstanding_minor'],r['currency'])] for r in remaining[:50]])
    message='Saat ini tidak ada piutang aktif'+name+' yang belum lunas.'
    if customer_id and any(i['status']=='VOID' for i in f.list_finance_invoices(b,customer_id=customer_id,actor_user_id=u)):
        message+=' Invoice lama sudah dibatalkan/direset dan tidak dihitung sebagai piutang.'
    return dict(kind='answer',title='Piutang saat ini',message=message,preview=[])


def refresh_values(b,u,values):
    """Clear unavailable draft choices, never select a replacement silently."""
    pools={'customer_id':f.list_customers(b,actor_user_id=u),
           'account_id':f.list_accounts(b,actor_user_id=u),
           'category_id':f.list_categories(b,include_children=True,actor_user_id=u),
           'project_id':f.list_finance_projects(b,actor_user_id=u)}
    changed=[]
    for key,rows in pools.items():
        if values.get(key) and not any(str(r['id'])==str(values[key]) for r in rows):
            values[key]='';changed.append(key)
    return changed
