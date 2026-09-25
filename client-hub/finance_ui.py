"""Shared Finance navigation context; no financial writes or alternate calculations."""
import re
from flask import g, request, session
import finance_service as finance

PAGE_ENDPOINTS = {'dashboard','operations','budget','payees','receivables','new_invoice','edit_invoice',
    'invoice_detail','invoice_settings','reports','assistant','receipt_new','edit_transaction',
    'collections','customer_statement','collection_reminder','bank_index','bank_new','bank_detail',
    'analyst','operator','operator_action','receipt_analyze','receipt_confirm'}


def context(business_id, user):
    today = finance.business_today(business_id)
    raw = request.values.get('month') or request.args.get('range_end') or request.args.get('end','')[:7]
    month = raw if re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', raw or '') and raw[:4]!='0000' else today.strftime('%Y-%m')
    if month > today.strftime('%Y-%m') and (request.endpoint or '').split('.')[-1] not in ('budget', 'operations'):
        month = today.strftime('%Y-%m')
    currency = request.values.get('display_currency', 'IDR')
    if currency not in finance.SUPPORTED_CURRENCIES:
        currency = 'IDR'
    endpoint = (request.endpoint or '').split('.')[-1]
    view = request.args.get('view')
    area = ('transactions' if view=='transactions' else 'accounts' if view=='accounts' else 'dashboard') if endpoint=='dashboard' else {
        'operations':'bills','budget':'budget','payees':'payees','receivables':'invoices',
        'new_invoice':'invoices','edit_invoice':'invoices','invoice_detail':'invoices','invoice_settings':'invoices',
        'reports':'reports','assistant':'assistant','receipt_new':'assistant','collections':'invoices',
        'customer_statement':'invoices','collection_reminder':'invoices','edit_transaction':'transactions',
        'bank_index':'transactions','bank_new':'transactions','bank_detail':'transactions',
        'analyst':'reports','operator':'assistant','operator_action':'assistant','receipt_analyze':'assistant','receipt_confirm':'assistant'}.get(endpoint,'dashboard')
    if request.method == 'GET' and endpoint in PAGE_ENDPOINTS and user['role'] != 'KILAS_ADMIN':
        # Runs after finance_access has validated membership and branch ownership.
        session['workspace_finance_business'] = business_id
        remembered = dict(session.get('workspace_finance_branches', {}))
        remembered[str(business_id)] = g.finance_branch_id
        session['workspace_finance_branches'] = remembered
        session['active_product'] = 'finance'
    from routes_products import _product_businesses
    return dict(enabled=endpoint in PAGE_ENDPOINTS, month=month, currency=currency, area=area,
                home=endpoint=='dashboard' and not view, businesses=_product_businesses(user['id'], 'finance') if endpoint in PAGE_ENDPOINTS else [],
                currencies=finance.SUPPORTED_CURRENCIES)
