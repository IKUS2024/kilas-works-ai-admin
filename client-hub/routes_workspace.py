"""Package-aware presentation and explicit product transitions; no business writes."""
from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for
import repo
import security

workspace_bp = Blueprint('workspace', __name__)


def context():
    if hasattr(g, 'kilas_workspace'):
        return g.kilas_workspace
    result = dict(enabled=False, ai=[], finance=[], unavailable=False, active='more')
    g.kilas_workspace = result
    if not session.get('user_id') or session.get('role') == 'KILAS_ADMIN':
        return result
    # Public customer links/documents never acquire owner navigation.
    if request.blueprint == 'public_web' or request.endpoint in (
        'finance.customer_invoice', 'finance.customer_invoice_pdf', 'finance.public_statement'):
        return result
    result['enabled'] = True
    try:
        from routes_products import _finance_business_claimed
        from kilas_core.customers import AI_PACKAGES
        rows = repo.list_businesses_for_user(session['user_id'])
        result['ai'] = [r for r in rows if r.get('package') in AI_PACKAGES]
        result['finance'] = [r for r in rows if _finance_business_claimed(r['id'])]
    except Exception:
        # Presentation failure never grants access or asserts there are no records.
        result['unavailable'] = True
    requested = (request.view_args or {}).get('bid', (request.view_args or {}).get('business_id'))
    for lane in ('ai', 'finance'):
        rows = result[lane]
        preferred = requested if any(r['id'] == requested for r in rows) else session.get('workspace_'+lane+'_business')
        selected = next((r for r in rows if str(r['id']) == str(preferred)), rows[0] if rows else None)
        result['selected_'+lane] = selected['id'] if selected else None
    ep = request.endpoint or ''
    result['active'] = ('home' if ep == 'workspace.home' else
                        'inbox' if ep.startswith('owner_web.') or ep == 'client.inbox_page' else
                        'customers' if ep.startswith('core_customers.') else
                        'jobs' if ep.startswith('core_jobs.') else
                        'finance' if ep.startswith('finance.') else 'more')
    return result


@workspace_bp.app_context_processor
def workspace_context():
    return {'workspace_ui': context()}


@workspace_bp.get('/workspace')
@security.login_required
def home():
    if session.get('role') == 'KILAS_ADMIN':
        return redirect(url_for('admin.dashboard'), code=303)
    session.pop('active_product', None)
    import workspace_presenter
    ui = context()
    if not ui['unavailable']:
        ui['setup'] = {b['id']: workspace_presenter.setup(b) for b in ui['ai']}
        ui['attention'] = {b['id']: workspace_presenter.finance_attention(b, session['user_id']) for b in ui['finance']}
    return render_template('workspace_home.html', user=security.current_user()), (503 if ui['unavailable'] else 200)


@workspace_bp.get('/workspace/more')
@security.login_required
def more():
    return render_template('workspace_more.html', user=security.current_user())


@workspace_bp.get('/workspace/go/<area>')
@security.login_required
def go(area):
    # Closed destinations: neither a supplied URL nor a guessed/foreign business.
    common = {'setup': 'products.product_start', 'services': 'projects.service_catalog_page',
              'projects': 'projects.my_project_list', 'talent': 'talent.talent_list',
              'bills': 'products.account_bills', 'account': 'auth.account_page',
              'ai_setup': 'products.assist_entry', 'finance_setup': 'products.finance_entry'}
    core = {'inbox': 'client.inbox_page', 'customers': 'core_customers.list_page',
            'jobs': 'core_jobs.list_page', 'knowledge': 'client.business_memory',
            'simulate': 'client.simulate_page', 'settings': 'client.business_settings',
            'review': 'client.review_page', 'automations': 'core_operations.settings'}
    if area in common:
        session.pop('active_product', None)
        return redirect(url_for(common[area]), code=303)
    if area not in core and area != 'finance':
        abort(404)
    ui = context()
    if ui['unavailable']:
        return render_template('workspace_home.html', user=security.current_user()), 503
    rows = ui['finance' if area == 'finance' else 'ai']
    requested = request.args.get('business_id')
    if requested and not any(str(r['id']) == requested for r in rows):
        abort(404)
    if not rows:
        return redirect(url_for('products.finance_entry' if area == 'finance' else 'products.assist_entry'), code=303)
    key = 'workspace_finance_business' if area == 'finance' else 'workspace_ai_business'
    bid = requested or session.get(key)
    business = next((r for r in rows if str(r['id']) == str(bid)), rows[0])
    session[key] = business['id']
    session['active_product'] = 'finance' if area == 'finance' else 'brain'
    if area == 'finance':
        return redirect(url_for('finance.workspace_choice', business_id=business['id']), code=303)
    from kilas_core import customers
    from kilas_core.job_routes import available
    from kilas_core import operation_access
    from public_chat.security import available as web_available
    if (area == 'automations' and (not operation_access.enabled() or not web_available(business))) or (area == 'customers' and not customers.enabled()) or (area in ('jobs', 'automations') and not available(business)):
        return render_template('workspace_unavailable.html', business=business), 200
    params = {'bid' if area in ('customers', 'jobs', 'automations') else 'business_id': business['id']}
    if area == 'inbox':
        if web_available(business):
            params['channel'] = 'web'
    return redirect(url_for(core[area], **params), code=303)
