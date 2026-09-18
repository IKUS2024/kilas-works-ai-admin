"""Authenticated, beta-only Finance UI; all ledger operations stay in finance_service."""
import calendar
from datetime import date
import os
import re
import uuid
from functools import wraps
from werkzeug.exceptions import HTTPException

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
import finance_branches as branches
import finance_service as finance
import finance_reports
import finance_invoice_view
import finance_collections
import finance_receipts
import file_utils
import finance_analyst
import finance_operator
import finance_assistant
import finance_ai_safety as ai_safety
from flask import jsonify, current_app, g
import security
import repo

finance_bp = Blueprint('finance', __name__)


def beta_enabled():
    return os.environ.get('KILAS_FINANCE_BETA', '').strip().lower() in ('true', '1', 'yes', 'on')


def finance_access(view):
    @wraps(view)
    @security.login_required
    def wrapped(business_id, **kwargs):
        user = security.current_user()
        import finance_entitlements as entitlement
        if not (beta_enabled() or entitlement.self_service()) and user['role'] != 'KILAS_ADMIN':
            abort(404)
        business = security.require_business_access(business_id, user=user)
        if request.method != 'GET':
            try: entitlement.require_write(business_id,user['id'])
            except finance.FinanceError:
                if request.is_json: return jsonify(error='Finance hanya-baca. Aktifkan trial atau perpanjang langganan.'),403
                flash('Finance hanya-baca. Data tetap tersedia; aktifkan atau perpanjang untuk melanjutkan.','error')
                return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
        branch_list = branches.list_branches(business_id, user['id'])
        choices = request.args.getlist('branch_id') + request.form.getlist('branch_id')
        if len(set(choices)) > 1 or len(request.args.getlist('branch_id')) > 1 or len(request.form.getlist('branch_id')) > 1:
            abort(400)
        selected = choices[0] if choices else None
        if selected is None:
            # Legacy URLs are unambiguous only while there is exactly one branch.
            selected = str(branch_list[0]['id']) if len(branch_list) == 1 else 'all'
        try:
            branch_id = None if selected == 'all' else record_id(selected)
            selected_branch = branches.get(business_id, branch_id) if branch_id is not None else None
        except finance.FinanceError:
            abort(404)
        g.finance_business_id = business_id
        g.finance_branch_id = branch_id
        g.finance_branches = branch_list
        g.finance_branch = selected_branch
        g.finance_branch_read_only = branch_id is None or not selected_branch['is_active']
        if g.finance_branch_read_only and request.method not in ('GET', 'HEAD'):
            # Setup has no historical branch yet; existing entitlement checks still apply.
            if not branch_list and view.__name__ == 'start' and not choices:
                return view(business_id, user, business, **kwargs)
            if request.is_json:
                return jsonify(error='Pilih satu cabang aktif untuk mencatat atau mengubah transaksi.'), 403
            abort(403)
        if g.finance_branch_read_only and view.__name__ in ('assistant', 'operator', 'receipt_new', 'bank_new', 'new_invoice', 'edit_transaction'):
            flash('Pilih satu cabang aktif untuk mencatat atau mengubah transaksi.', 'error')
            return redirect(url_for('finance.dashboard', business_id=business_id))
        with branches.scope(business_id, branch_id, user['id']):
            return view(business_id, user, business, **kwargs)
    return wrapped


ERRORS = {
    'recurring_ledger_managed': 'Biaya rutin tidak dapat diedit langsung. Batalkan transaksi jika keliru; riwayat kejadian tetap tersimpan.',
    'invalid_recurring_limit': 'Batas pemrosesan belum valid.',
    'customer_unavailable': 'Customer tidak tersedia untuk bisnis ini.',
    'invalid_items': 'Isi 1–100 baris dengan deskripsi, jumlah, dan harga yang valid.',
    'invalid_period': 'Tanggal jatuh tempo tidak boleh sebelum tanggal terbit.',
    'invalid_invoice_state': 'Status invoice tidak mengizinkan tindakan ini. Muat ulang halaman.',
    'invoice_cannot_void': 'Invoice yang sudah memiliki pembayaran tidak dapat dibatalkan.',
    'empty_invoice_total': 'Total invoice harus lebih dari nol sebelum diterbitkan.',
    'overpayment': 'Nominal melebihi sisa tagihan. Muat ulang untuk melihat saldo terbaru.',
    'payment_key_conflict': 'Form pembayaran sudah digunakan. Muat ulang untuk pembayaran baru.',
    'invalid_payment_key': 'Form pembayaran tidak valid. Muat ulang halaman.',
    'invoice_ledger_managed': 'Transaksi ini berasal dari pembayaran invoice dan tidak dapat diubah atau dibatalkan langsung.',
    'invalid_money_minor': 'Nominal belum valid. Masukkan angka rupiah yang benar.',
    'account_unavailable': 'Kas / rekening tidak tersedia.',
    'account_currency_mismatch': 'Pilih kas / rekening dalam rupiah untuk transaksi ini.',
    'category_unavailable': 'Kategori tidak tersedia.',
    'category_direction_mismatch': 'Kategori tidak sesuai dengan jenis transaksi.',
    'project_unavailable': 'Proyek tidak tersedia untuk bisnis ini.',
    'account_exists': 'Kas / rekening dengan nama dan jenis tersebut sudah ada.',
    'category_exists': 'Kategori tersebut sudah ada.',
    'invalid_date': 'Tanggal belum valid.',
    'future_date': 'Tanggal tidak boleh melebihi hari ini.',
    'invalid_text': 'Isian terlalu panjang atau tidak valid.',
    'missing_name': 'Nama wajib diisi.',
    'invalid_enum': 'Pilihan belum valid.',
    'invalid_id': 'Pilihan tidak tersedia.',
    'branch_last_active': 'Sisakan minimal satu cabang aktif. Tambahkan cabang baru sebelum menonaktifkan cabang terakhir.',
    'branch_exists': 'Nama cabang sudah digunakan.',
    'branch_unavailable': 'Cabang tidak tersedia.',
    'branch_mismatch': 'Kas / rekening harus berada dalam cabang yang sama.',
}


def whole_idr(value, signed=False):
    pattern = r'-?[0-9]{1,19}' if signed else r'[0-9]{1,19}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise finance.FinanceError('invalid_money_minor')
    amount = int(value)
    if not -(2**63) <= amount <= 2**63-1 or (not signed and amount <= 0):
        raise finance.FinanceError('invalid_money_minor')
    return amount


def record_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,19}', value):
        raise finance.FinanceError('invalid_id')
    return int(value)


def idr(value):
    return ('-' if value < 0 else '') + 'Rp' + format(abs(value), ',').replace(',', '.')


@finance_bp.app_template_filter('finance_idr')
def format_idr(value):
    return idr(value)


def period(value):
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}', value or ''):
        raise ValueError('month')
    year, month = map(int, value.split('-'))
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first.isoformat(), last.isoformat()


@finance_bp.route('/finance')
@security.login_required
def overview():
    """Membership-only, read-only overview; ledgers and write routes remain tenant-scoped."""
    user = security.current_user()
    import finance_entitlements as entitlement
    if not (beta_enabled() or entitlement.self_service()) and user['role'] != 'KILAS_ADMIN':
        abort(404)
    businesses = repo.list_businesses_for_user(user['id'])
    selected = request.args.get('business_id', 'all')
    # Even admins use their memberships here, never the global admin business list.
    business = next((b for b in businesses if str(b['id']) == selected), None)
    if selected != 'all' and business is None:
        abort(404)
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    split_period = 'period_month' in request.args or 'period_year' in request.args
    if split_period:
        month = request.args.get('period_year', '') + '-' + request.args.get('period_month', '')
    try:
        start, end = period(month)
        if month > date.today().strftime('%Y-%m'):
            raise ValueError('future_month')
    except ValueError:
        flash('Periode atau filter belum valid. Bulan masa depan belum dapat dipilih.', 'error')
        return redirect(url_for('finance.overview', business_id=selected))
    if business is not None:
        return redirect(url_for('finance.dashboard', business_id=business['id'], month=month))
    if split_period:
        return redirect(url_for('finance.overview', month=month))
    keys = ('total_income_minor', 'total_expense_minor', 'net_cashflow_minor',
            'total_outstanding_minor', 'total_overdue_minor', 'open_invoice_count', 'overdue_invoice_count')
    totals = dict.fromkeys(keys, 0)
    breakdown = []
    for business in businesses:
        security.require_business_access(business['id'], user=user)
        values = finance.get_finance_summary(business['id'], start, end, actor_user_id=user['id'])
        values.update(finance_collections.position(business['id'], user['id'], today=end)['aging'])
        breakdown.append(dict(business=business, summary=values))
        for key in keys:
            totals[key] += values[key]
    selected_year = int(month[:4])
    current_year, current_month = date.today().year, date.today().month
    period_years = sorted(set(range(max(1, current_year - 10), current_year + 1)) | {selected_year})
    return Response(render_template('finance_overview.html', user=user, businesses=businesses,
        business=None, month=month, period_years=period_years, selected_year=selected_year,
        current_year=current_year, current_month=current_month,
        summary=totals, breakdown=breakdown, as_of=end), headers={'Cache-Control': 'private, no-store'})


@finance_bp.route('/business/<int:business_id>/finance')
@finance_access
def dashboard(business_id, user, business):
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    split_period = 'period_month' in request.args or 'period_year' in request.args
    if split_period:
        month = request.args.get('period_year', '') + '-' + request.args.get('period_month', '')
    direction = request.args.get('direction') or None
    try:
        start, end = period(month)
        if month > date.today().strftime('%Y-%m'):
            raise ValueError('future_month')
        if direction not in (None, 'INCOME', 'EXPENSE'):
            raise ValueError('direction')
    except ValueError:
        flash('Periode atau filter belum valid. Bulan masa depan belum dapat dipilih.', 'error')
        return redirect(url_for('finance.dashboard', business_id=business_id))
    if split_period:
        return redirect(url_for('finance.dashboard', business_id=business_id, month=month, direction=direction))
    selected_year = int(month[:4])
    current_year, current_month = date.today().year, date.today().month
    period_years = sorted(set(range(max(1, current_year - 10), current_year + 1)) | {selected_year})
    actor = {'actor_user_id': user['id']}
    accounts = finance.list_accounts(business_id, include_inactive=True, **actor)
    categories = finance.list_categories(business_id, include_inactive=True, **actor)
    summary = finance.get_finance_summary(business_id, start, end, **actor)
    show_all_transactions = request.args.get('transactions') == 'all'
    transaction_limit = 100 if show_all_transactions else 6
    transactions = finance.list_transactions(business_id, start_date=start, end_date=end,
                                            direction=direction, status='POSTED', limit=transaction_limit, **actor)
    has_more_transactions = not show_all_transactions and len(transactions) > 5
    if not show_all_transactions:
        transactions = transactions[:5]
    balances = finance.get_account_balance_report(business_id, date.today().isoformat(), user['id'])
    breakdown = []
    if g.finance_branch_id is None:
        for item in g.finance_branches:
            with branches.scope(business_id, item['id'], user['id']):
                breakdown.append(dict(branch=item, summary=finance.get_finance_summary(business_id, start, end, **actor)))
        # Derive displayed combined values from the same branch values, even if another
        # request posts between reads. Never show conflicting aggregate/breakdown totals.
        for key in ('total_income_minor', 'total_expense_minor', 'net_cashflow_minor'):
            summary[key] = sum(item['summary'][key] for item in breakdown)
    return render_template('finance_dashboard.html', user=user, business=business,
        period_start=start, period_end=end, balances=balances, balance_total=sum(a['balance_minor'] for a in balances), branch_breakdown=breakdown,
        businesses=repo.list_businesses_for_user(user['id']),
        accounts=accounts, categories=categories, summary=summary, transactions=transactions,
        collection_summary=finance_collections.position(business_id,user['id'])['aging'],
        account_map={a['id']: a for a in accounts}, category_map={c['id']: c for c in categories},
        customers=finance.list_customers(business_id, **actor),
        projects=finance.list_finance_projects(business_id, **actor),
        initialized=bool(accounts and categories), month=month,
        month_label=('Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember')[int(month[5:7])-1] + ' ' + month[:4],
        direction=direction, show_all_transactions=show_all_transactions,
        has_more_transactions=has_more_transactions,
        period_years=period_years, selected_year=selected_year,
        current_year=current_year, current_month=current_month,
        analyst_enabled=finance_analyst.enabled(business_id),
        operator_enabled=finance_operator.enabled(business_id),
        today=date.today().isoformat(), account_types={'CASH':'Tunai','BANK':'Rekening Bank','EWALLET':'E-Wallet','OTHER':'Lainnya'})


def mutate(business_id, action, success, destination=None):
    try:
        action()
    except finance.FinanceError as error:
        if str(error) in ('transaction_unavailable', 'business_unavailable', 'invoice_unavailable', 'recurring_unavailable'):
            abort(404)
        flash(ERRORS.get(str(error), 'Data belum valid. Periksa isian dan coba lagi.'), 'error')
    else:
        flash(success, 'success')
    return redirect(destination or url_for('finance.dashboard', business_id=business_id), code=303)


@finance_bp.route('/business/<int:business_id>/finance/start', methods=['POST'])
@finance_access
def start(business_id, user, business):
    return mutate(business_id, lambda: finance.ensure_finance_defaults(business_id, actor_user_id=user['id']),
                  'Kilas Finance siap digunakan.')


@finance_bp.route('/business/<int:business_id>/finance/transactions', methods=['POST'])
@finance_access
def create_transaction(business_id, user, business):
    def action():
        finance.create_transaction(business_id, request.form.get('direction'), whole_idr(request.form.get('amount')),
            record_id(request.form.get('account_id')), record_id(request.form.get('category_id')),
            request.form.get('occurred_on'), currency='IDR', description=transaction_note(business_id, request.form),
            counterparty_name=request.form.get('counterparty_name'),
            customer_id=record_id(request.form['customer_id']) if request.form.get('customer_id') else None,
            project_id=record_id(request.form['project_id']) if request.form.get('project_id') else None,
            actor_user_id=user['id'])
    return mutate(business_id, action, 'Transaksi dicatat.')


@finance_bp.route('/business/<int:business_id>/finance/transactions/<int:transaction_id>/void', methods=['POST'])
@finance_access
def void_transaction(business_id, user, business, transaction_id):
    return mutate(business_id, lambda: finance.void_transaction(business_id, transaction_id, actor_user_id=user['id']),
                  'Transaksi dihapus dari perhitungan. Riwayat audit tetap tersimpan.')


@finance_bp.route('/business/<int:business_id>/finance/reset', methods=['POST'])
@finance_access
def reset_finance(business_id, user, business):
    if request.form.get('confirmation') != 'RESET':
        flash('Ketik RESET untuk mengonfirmasi reset Finance cabang ini.', 'error')
        return redirect(url_for('finance.dashboard', business_id=business_id), code=303)
    branch_name = g.finance_branch['name']
    return mutate(
        business_id,
        lambda: finance.reset_branch_finance(business_id, actor_user_id=user['id']),
        f'Finance cabang {branch_name} direset ke Rp0. Struktur tetap tersedia dan riwayat audit tetap tersimpan.',
        url_for('finance.dashboard', business_id=business_id, branch_id=g.finance_branch_id))


@finance_bp.route('/business/<int:business_id>/finance/accounts', methods=['POST'])
@finance_access
def create_account(business_id, user, business):
    return mutate(business_id, lambda: finance.create_account(business_id, request.form.get('name'),
        request.form.get('account_type'), currency='IDR',
        opening_balance_minor=whole_idr(request.form.get('opening_balance', '0'), signed=True),
        actor_user_id=user['id']), 'Kas / rekening ditambahkan.')


@finance_bp.route('/business/<int:business_id>/finance/categories', methods=['POST'])
@finance_access
def create_category(business_id, user, business):
    return mutate(business_id, lambda: finance.create_category(business_id, request.form.get('direction'),
        request.form.get('name'), actor_user_id=user['id']), 'Kategori ditambahkan.')


INVOICE_LABELS = {'DRAFT':'Draft','ISSUED':'Belum dibayar','PARTIALLY_PAID':'Dibayar sebagian','PAID':'Lunas','VOID':'Dibatalkan'}


@finance_bp.route('/business/<int:business_id>/finance/receivables')
@finance_access
def receivables(business_id, user, business):
    actor = {'actor_user_id': user['id']}
    section = request.args.get('section', 'summary')
    if section not in ('summary', 'customers', 'add_customer', 'invoices'):
        section = 'summary'
    customers = finance.list_customers(business_id, include_inactive=True, **actor)
    invoices = finance.list_finance_invoices(business_id, **actor)
    totals = {i['id']: finance.get_invoice_totals(business_id, i['id'], **actor) for i in invoices}
    return render_template('finance_receivables.html', user=user, business=business, customers=customers,
        customer_map={c['id']:c for c in customers}, invoices=invoices, totals=totals, section=section,
        summary=finance.get_receivables_summary(business_id, **actor), labels=INVOICE_LABELS)


@finance_bp.route('/business/<int:business_id>/finance/customers', methods=['POST'])
@finance_access
def create_customer(business_id, user, business):
    return mutate(business_id, lambda: finance.create_customer(business_id,request.form.get('name'),
        phone=request.form.get('phone'), email=request.form.get('email'), notes=request.form.get('notes'),
        actor_user_id=user['id']), 'Customer ditambahkan.', url_for('finance.receivables',business_id=business_id))


def nonnegative_idr(value):
    amount = whole_idr(value, signed=True)
    if amount < 0:
        raise finance.FinanceError('invalid_money_minor')
    return amount


@finance_bp.route('/business/<int:business_id>/finance/invoices/new', methods=['GET','POST'])
@finance_access
def new_invoice(business_id, user, business):
    if request.method == 'POST':
        try:
            descriptions = request.form.getlist('item_description')
            quantities = request.form.getlist('quantity')
            prices = request.form.getlist('unit_price')
            if not 1 <= len(descriptions) <= 100 or len(descriptions) != len(quantities) or len(prices) != len(descriptions):
                raise finance.FinanceError('invalid_items')
            items = [dict(description=d,quantity=whole_idr(q),unit_price_minor=nonnegative_idr(p))
                     for d,q,p in zip(descriptions,quantities,prices)]
            invoice_id = finance.create_finance_invoice(business_id, record_id(request.form.get('customer_id')),
                request.form.get('issue_date'),request.form.get('due_date'),items,
                notes=request.form.get('notes'),actor_user_id=user['id'])
        except finance.FinanceError as error:
            flash(ERRORS.get(str(error),'Data invoice belum valid. Periksa isian dan coba lagi.'),'error')
            return redirect(url_for('finance.new_invoice',business_id=business_id),code=303)
        return redirect(url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id),code=303)
    return render_template('finance_invoice_form.html',user=user,business=business,
        customers=finance.list_customers(business_id,actor_user_id=user['id']),today=date.today().isoformat())


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>')
@finance_access
def invoice_detail(business_id, user, business, invoice_id):
    return render_invoice_detail(business_id,user,business,invoice_id)


def render_invoice_detail(business_id,user,business,invoice_id,share_url=None):
    actor = {'actor_user_id':user['id']}
    try: doc=finance_invoice_view.document(business_id,invoice_id,user['id'])
    except ValueError: abort(404)
    invoice=dict(doc['invoice'],id=invoice_id)
    return render_template('finance_invoice_detail.html',user=user,business=business,invoice=invoice,
        doc=doc,share_url=share_url,
        payments=finance.list_invoice_payments(business_id,invoice_id,**actor),
        totals=doc['totals'],
        accounts=finance.list_accounts(business_id,**actor),categories=finance.list_categories(business_id,'INCOME',**actor),
        today=date.today().isoformat(),payment_key=uuid.uuid4().hex,labels=INVOICE_LABELS)


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/issue',methods=['POST'])
@finance_access
def issue_invoice(business_id,user,business,invoice_id):
    return mutate(business_id,lambda: finance.issue_finance_invoice(business_id,invoice_id,actor_user_id=user['id']),
        'Invoice diterbitkan.',url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id))


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/void',methods=['POST'])
@finance_access
def void_invoice(business_id,user,business,invoice_id):
    return mutate(business_id,lambda: finance.void_finance_invoice(business_id,invoice_id,actor_user_id=user['id']),
        'Invoice dibatalkan. Riwayat tetap tersimpan.',url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id))


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/payments',methods=['POST'])
@finance_access
def record_payment(business_id,user,business,invoice_id):
    return mutate(business_id,lambda: finance.record_invoice_payment(business_id,invoice_id,
        whole_idr(request.form.get('amount')),request.form.get('paid_on'),record_id(request.form.get('account_id')),
        record_id(request.form.get('category_id')),note=request.form.get('note'),actor_user_id=user['id'],
        idempotency_key=request.form.get('payment_key')), 'Pembayaran dicatat.',
        url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id))


@finance_bp.route('/business/<int:business_id>/finance/operations')
@finance_access
def operations(business_id,user,business):
    section = request.args.get('section', 'recurring')
    if section not in ('recurring', 'add', 'projects'):
        section = 'recurring'
    month = request.args.get('month',date.today().strftime('%Y-%m'))
    try:
        start,end = period(month)
        if month > date.today().strftime('%Y-%m'):
            raise ValueError('future_month')
    except ValueError:
        flash('Periode belum valid. Bulan masa depan belum dapat dipilih.','error')
        return redirect(url_for('finance.operations',business_id=business_id))
    actor = {'actor_user_id':user['id']}
    rules = finance.list_recurring_expenses(business_id,include_inactive=True,**actor)
    projects = finance.list_finance_projects(business_id,**actor)
    return render_template('finance_operations.html',user=user,business=business,rules=rules,projects=projects,section=section,
        preview=finance.preview_due_recurring_expenses(business_id,date.today(),**actor),
        project_map={p['id']:p for p in projects},
        attention={r['id']:finance.recurring_needs_attention(business_id,r['id'],**actor) for r in rules if r['is_active']},
        accounts=finance.list_accounts(business_id,**actor),categories=finance.list_categories(business_id,'EXPENSE',**actor),
        contributions=finance.get_project_cash_contribution(business_id,start,end,**actor),
        month=month,current_month=date.today().strftime('%Y-%m'),today=date.today().isoformat(),
        max_occurrences=finance.MAX_RECURRING_OCCURRENCES)


@finance_bp.route('/business/<int:business_id>/finance/recurring',methods=['POST'])
@finance_access
def create_recurring(business_id,user,business):
    return mutate(business_id,lambda:finance.create_recurring_expense(business_id,request.form.get('name'),
        whole_idr(request.form.get('amount')),record_id(request.form.get('account_id')),record_id(request.form.get('category_id')),
        request.form.get('cadence'),request.form.get('next_due_on'),end_on=request.form.get('end_on') or None,
        project_id=record_id(request.form['project_id']) if request.form.get('project_id') else None,
        counterparty_name=request.form.get('counterparty_name'),description=request.form.get('description'),actor_user_id=user['id']),
        'Biaya rutin disimpan.',url_for('finance.operations',business_id=business_id))


@finance_bp.route('/business/<int:business_id>/finance/recurring/<int:recurring_id>/deactivate',methods=['POST'])
@finance_access
def deactivate_recurring(business_id,user,business,recurring_id):
    return mutate(business_id,lambda:finance.deactivate_recurring_expense(business_id,recurring_id,actor_user_id=user['id']),
        'Biaya rutin dinonaktifkan. Riwayat tetap tersimpan.',url_for('finance.operations',business_id=business_id))


@finance_bp.route('/business/<int:business_id>/finance/recurring/process',methods=['POST'])
@finance_access
def process_recurring(business_id,user,business):
    if not request.form.getlist('occurrence'):
        flash('Pilih pengeluaran yang sudah dibayar terlebih dahulu.','error')
        return redirect(url_for('finance.operations',business_id=business_id),code=303)
    result = finance.process_due_recurring_expenses(business_id,date.today(),actor_user_id=user['id'],selected=request.form.getlist('occurrence'))
    flash(f"{result['posted_count']} biaya rutin dicatat.",'success')
    if result['needs_attention_count']:
        flash('Ada biaya rutin yang belum dapat dicatat. Periksa akun, kategori, dan proyek. Jadwalnya tetap tersimpan.','error')
    if result['limit_reached']:
        flash('Batas pemrosesan tercapai. Masih ada jadwal jatuh tempo; proses kembali untuk melanjutkan.','error')
    return redirect(url_for('finance.operations',business_id=business_id),code=303)


def report_error(error):
    if str(error) in ('report_limit','forecast_limit'):
        return 'Data laporan terlalu banyak. Persempit rentang tanggal atau komitmen biaya rutin.'
    return 'Filter laporan belum valid. Gunakan tanggal yang benar, maksimal 366 hari dan 12 bulan.'


@finance_bp.route('/business/<int:business_id>/finance/reports')
@finance_access
def reports(business_id,user,business):
    section = request.args.get('section', 'filter')
    if section not in ('filter', 'summary', 'trend', 'categories', 'accounts', 'customers', 'projects', 'receivables', 'commitments'):
        section = 'filter'
    try:
        filters=finance_reports.parse_filters(request.args)
        actor={'actor_user_id':user['id']}
        data={name:finance_reports.report_data(name,business_id,filters,user['id']) for name in finance_reports.REPORT_NAMES if name not in ('transactions','invoices')}
        summary=finance.get_cashflow_report(business_id,filters['start'],filters['end'],**actor)
        trend=finance.get_monthly_cashflow_trend(business_id,filters['start'][:7],filters['end'][:7],
            start_date=filters['start'],end_date=filters['end'],**actor)
    except finance.FinanceError as error:
        return render_template('finance_reports.html',user=user,business=business,error=report_error(error),section=section,today=date.today().isoformat()),400
    response=Response(render_template('finance_reports.html',user=user,business=business,filters=filters,section=section,
        today=date.today().isoformat(),data=data,summary=summary,trend=trend,directions=finance_reports.DIRECTIONS,
        account_types=finance_reports.ACCOUNT_TYPES,export_names=finance_reports.REPORT_NAMES))
    response.headers['Cache-Control']='private, no-store'
    return response


@finance_bp.route('/business/<int:business_id>/finance/reports/export/<report_name>.csv')
@finance_access
def report_csv(business_id,user,business,report_name):
    if report_name not in finance_reports.REPORT_NAMES:abort(404)
    try:
        filters=finance_reports.parse_filters(request.args)
        data=finance_reports.export_csv(report_name,business_id,filters,user['id'])
    except finance.FinanceError as error:
        return Response(report_error(error),status=400,mimetype='text/plain',headers={'Cache-Control':'no-store'})
    return Response(data,content_type='text/csv; charset=utf-8',headers={
        'Content-Disposition':f'attachment; filename="{report_name}-{filters["start"]}_{filters["end"]}.csv"',
        'Cache-Control':'private, no-store'})


@finance_bp.route('/business/<int:business_id>/finance/reports/export/all.zip')
@finance_access
def report_zip(business_id,user,business):
    try:
        filters=finance_reports.parse_filters(request.args)
        data=finance_reports.export_zip(business_id,filters,user['id'])
    except finance.FinanceError as error:
        return Response(report_error(error),status=400,mimetype='text/plain',headers={'Cache-Control':'no-store'})
    return Response(data,content_type='application/zip',headers={
        'Content-Disposition':f'attachment; filename="kilas-finance-laporan-{filters["start"]}_{filters["end"]}.zip"',
        'Cache-Control':'private, no-store'})


@finance_bp.route('/business/<int:business_id>/finance/analyst', methods=['GET', 'POST'])
@ai_safety.endpoint
@finance_access
def analyst(business_id, user, business):
    if not finance_analyst.enabled(business_id):
        ai_safety.event('allowlist_denied'); abort(404)
    if request.method == 'GET':
        return render_template('finance_analyst.html', user=user, business=business,
                               month=date.today().strftime('%Y-%m'),
                               operator_enabled=finance_operator.enabled(business_id))
    payload, error = finance_ai_payload(user['id'],business_id,'ai')
    if error is not None: return error
    try:
        question, start, scope = finance_analyst.validate(payload)
    except (ValueError, TypeError):
        ai_safety.event('invalid_request')
        return jsonify(error='Isi pertanyaan dan pilih periode serta fokus yang valid.'), 400
    try:
        context = finance_analyst.build_context(business_id, user['id'], start, scope)
        result, reason = finance_analyst.generate(question, context, **(dict(business_id=business_id,user_id=user['id']) if __import__('finance_entitlements').self_service() else {}))
        if result is not None:
            ai_safety.event('analyst_success')
            response = jsonify(context=context, analysis=result)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
    except Exception:
        # Never emit exception messages, finance text, query parameters or credentials.
        reason = 'context_unavailable'
    ai_safety.event(reason)
    ai_safety.event('analyst_failure')
    return jsonify(error=finance_analyst.ERROR), 503


@finance_bp.route('/business/<int:business_id>/finance/operator')
@ai_safety.endpoint
@finance_access
def operator(business_id, user, business):
    if not finance_operator.enabled(business_id):
        ai_safety.event('allowlist_denied'); abort(404)
    actor = {'actor_user_id': user['id']}
    invoices = finance.operator_invoice_choices(business_id, **actor)
    return render_template('finance_operator.html', user=user, business=business,
        actions=finance_operator.ACTIONS, today=date.today().isoformat(),
        accounts=[a for a in finance.list_accounts(business_id, **actor) if a['currency']=='IDR'],
        categories=finance.list_categories(business_id, **actor),
        invoices=invoices)


@finance_bp.route('/business/<int:business_id>/finance/operator/<stage>', methods=['POST'])
@ai_safety.endpoint
@finance_access
def operator_action(business_id, user, business, stage):
    if not finance_operator.enabled(business_id):
        ai_safety.event('allowlist_denied'); abort(404)
    if stage not in ('draft','confirm'): abort(404)
    payload, error = finance_ai_payload(user['id'],business_id,'ai' if stage=='draft' else 'confirm')
    if error is not None: return error
    try:
        if stage == 'draft':
            finance_operator.validate_request(payload)
            result = finance_operator.prepare(business_id, user['id'], payload)
            ai_safety.event('draft_generated')
        else:
            if not isinstance(payload,dict) or set(payload)!={'token','confirm'} or payload['confirm'] is not True:
                raise finance_operator.OperatorError('confirmation_required')
            result = finance_operator.confirm(business_id, user['id'], payload['token'])
            ai_safety.event('confirmation_accepted')
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response
    except (finance_operator.OperatorError, finance.FinanceError) as error:
        # Messages are fixed categories, never log submitted fields, tokens or model text.
        ai_safety.event(str(error))
        if stage=='confirm': ai_safety.event('confirmation_rejected')
        unavailable = str(error) in ('not_configured','network_failure','timeout','upstream_failure','invalid_result')
        return jsonify(error=(finance_operator.ERROR if unavailable else
            'Data atau draft tidak valid, kedaluwarsa, tidak didukung, atau sudah berubah. Periksa pilihan dan buat draft baru bila perlu. Nominal serta keterangan harus disebutkan jelas.')), 503 if unavailable else 400
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(error='Hasil belum dapat dipastikan. Jangan buat draft baru; ulangi konfirmasi draft yang sama atau periksa riwayat Finance.'), 503


def finance_ai_payload(user_id, business_id, kind):
    # Scoped only to Finance AI; normal finance routes and global CSRF are unchanged.
    if request.content_length is None or request.content_length > 8192:
        ai_safety.event('invalid_request')
        return None, (jsonify(error='Permintaan terlalu besar.'),413)
    if not request.is_json:
        ai_safety.event('invalid_request')
        return None, (jsonify(error='Gunakan permintaan JSON yang valid.'),415)
    if not ai_safety.allow_attempt(user_id,business_id,kind):
        response=jsonify(error='Terlalu banyak percobaan. Tunggu sebentar; jangan buat draft pengganti untuk konfirmasi yang belum pasti.')
        response.status_code=429;response.headers['Retry-After']='60'
        return None,response
    try:
        payload=ai_safety.json_object(request.get_data().decode('utf-8'))
    except (ValueError,UnicodeError,RecursionError):
        ai_safety.event('invalid_request')
        return None,(jsonify(error='Format permintaan tidak valid.'),400)
    return payload,None


@finance_bp.after_request
def invoice_privacy(response):
    # Every Finance workspace contains sensitive records, including dashboard and
    # operations pages that previously relied on browser cache defaults.
    response.headers['Cache-Control']='private, no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Robots-Tag']='noindex, nofollow, noarchive'
    response.headers['X-Frame-Options']='DENY'
    return response


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/print')
@finance_access
def invoice_print(business_id,user,business,invoice_id):
    try: doc=finance_invoice_view.document(business_id,invoice_id,user['id'])
    except ValueError: abort(404)
    return render_template('finance_invoice_public.html',doc=doc)


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/share',methods=['POST'])
@finance_access
def invoice_share(business_id,user,business,invoice_id):
    invoice=finance.get_finance_invoice(business_id,invoice_id,actor_user_id=user['id'])
    if not invoice or invoice['status'] not in finance_invoice_view.VISIBLE: abort(404)
    try:
        base=finance_invoice_view.base_url()
        token=finance_invoice_view.create_token(business_id,invoice_id,user['id'])
    except ValueError:
        return 'Tautan invoice belum tersedia. Hubungi pengelola aplikasi.',503
    share_url=base+url_for('finance.customer_invoice',token=token)
    return render_invoice_detail(business_id,user,business,invoice_id,share_url)


@finance_bp.route('/finance/invoice-share/<token>')
def customer_invoice(token):
    try:
        business_id,invoice_id=finance_invoice_view.resolve_token(token)
        doc=finance_invoice_view.document(business_id,invoice_id,public=True)
    except (ValueError,TypeError):
        return 'Tautan invoice tidak tersedia atau sudah kedaluwarsa.',404
    except Exception:
        current_app.logger.warning('FINANCE_INVOICE_SHARE: unavailable')
        return 'Invoice belum dapat ditampilkan. Coba lagi nanti.',503
    return render_template('finance_invoice_public.html',doc=doc)


@finance_bp.route('/business/<int:business_id>/finance/collections')
@finance_access
def collections(business_id,user,business):
    section = request.args.get('section', 'summary')
    if section not in ('summary', 'queue'):
        section = 'summary'
    sort=request.args.get('sort','overdue');view=request.args.get('view','all')
    try:
        page=int(request.args.get('page','1'))
        if sort not in finance_collections.SORTS or view not in finance_collections.FILTERS or page<1:raise ValueError()
        data=finance_collections.position(business_id,user['id'])
        queue=finance_collections.queue(data,sort,view,page)
    except finance.FinanceError:
        return 'Daftar piutang belum dapat ditampilkan. Hubungi pengelola aplikasi.',503
    except ValueError:abort(400)
    return render_template('finance_collections.html',user=user,business=business,data=data,queue=queue,section=section,
                           sort=sort,view=view,labels=INVOICE_LABELS)


def render_statement(business_id,user,business,customer_id,standalone=False,share_url=None):
    if not finance.get_customer(business_id,customer_id,actor_user_id=user['id']):abort(404)
    try:doc=finance_collections.statement(business_id,customer_id,user['id'])
    except finance.FinanceError:
        return 'Statement belum dapat ditampilkan. Hubungi pengelola aplikasi.',503
    except ValueError:abort(404)
    return render_template('finance_statement_public.html' if standalone else 'finance_statement.html',
                           doc=doc,user=None if standalone else user,business=business,customer_id=customer_id,share_url=share_url)


@finance_bp.route('/business/<int:business_id>/finance/customers/<int:customer_id>/statement')
@finance_access
def customer_statement(business_id,user,business,customer_id):
    return render_statement(business_id,user,business,customer_id)


@finance_bp.route('/business/<int:business_id>/finance/customers/<int:customer_id>/statement/print')
@finance_access
def statement_print(business_id,user,business,customer_id):
    return render_statement(business_id,user,business,customer_id,standalone=True)


@finance_bp.route('/business/<int:business_id>/finance/customers/<int:customer_id>/statement/share',methods=['POST'])
@finance_access
def statement_share(business_id,user,business,customer_id):
    if not finance.get_customer(business_id,customer_id,actor_user_id=user['id']):abort(404)
    try:
        base=finance_invoice_view.base_url()
        token=finance_collections.create_token(business_id,customer_id,user['id'])
    except ValueError:return 'Tautan statement belum tersedia. Hubungi pengelola aplikasi.',503
    return render_statement(business_id,user,business,customer_id,
                            share_url=base+url_for('finance.public_statement',token=token))


@finance_bp.route('/finance/statement-share/<token>')
def public_statement(token):
    try:
        business_id,customer_id,branch_id=finance_collections.resolve_token(token, include_branch=True)
        with branches.scope(business_id, branch_id):
            doc=finance_collections.statement(business_id,customer_id)
    except (ValueError,TypeError):return 'Tautan statement tidak tersedia atau sudah kedaluwarsa.',404
    except Exception:
        current_app.logger.warning('FINANCE_STATEMENT_SHARE: unavailable')
        return 'Statement belum dapat ditampilkan. Coba lagi nanti.',503
    return render_template('finance_statement_public.html',doc=doc)


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/reminder')
@finance_access
def collection_reminder(business_id,user,business,invoice_id):
    try:text=finance_collections.reminder(business_id,invoice_id,user['id'],request.args.get('tone','friendly'))
    except ValueError:abort(404)
    return render_template('finance_reminder.html',user=user,business=business,invoice_id=invoice_id,reminder=text)


# Receipt analysis and confirmation share the Finance access + AI safety architecture.


def receipt_page(user, business, review=None, error=None, values=None, status=200):
    accounts, categories = finance_receipts.options(business['id'], user['id'])
    return render_template('finance_receipt.html', user=user, business=business, review=review,
                           accounts=accounts, categories=categories, error=error, values=values,
                           today=date.today().isoformat()), status


@finance_bp.route('/business/<int:business_id>/finance/receipts/new')
@ai_safety.endpoint
@finance_access
def receipt_new(business_id, user, business):
    return receipt_page(user, business)


@finance_bp.route('/business/<int:business_id>/finance/receipts/analyze', methods=['POST'])
@ai_safety.endpoint
@finance_access
def receipt_analyze(business_id, user, business):
    uploaded = None
    try:
        if set(request.files) != {'receipt'} or len(request.files.getlist('receipt')) != 1:
            raise file_utils.UploadRejected('Pilih tepat satu struk.')
        uploaded = request.files['receipt']
        raw = uploaded.stream.read(finance_receipts.MAX_BYTES + 1)
        review = finance_receipts.analyze(business_id, user['id'], uploaded.filename, raw)
        # Bytes remain request-local; neither review nor tokens contain the file.
        del raw
        return receipt_page(user, business, review=review)
    except HTTPException:
        raise
    except file_utils.UploadRejected as error:
        return receipt_page(user, business, error=str(error), status=400)
    except finance_receipts.ReceiptError as error:
        ai_safety.receipt_event(str(error))
        return receipt_page(user, business, error=finance_receipts.READ_ERROR, status=503)
    except Exception:
        ai_safety.event('request_failed')
        return receipt_page(user, business, error='Struk belum dapat dianalisis. Gunakan form pengeluaran manual di Finance.', status=503)
    finally:
        if uploaded is not None:
            uploaded.close()


@finance_bp.route('/business/<int:business_id>/finance/receipts/confirm', methods=['POST'])
@ai_safety.endpoint
@finance_access
def receipt_confirm(business_id, user, business):
    if not ai_safety.allow_attempt(user['id'], business_id, 'confirm'):
        return receipt_page(user, business, error='Terlalu banyak percobaan. Coba lagi sebentar.', status=429)
    token = request.form.get('analysis_token', '')
    try:
        data = finance_receipts.resolve_token(token, business_id, user['id'])
    except (ValueError, TypeError):
        return receipt_page(user, business, error='Review tidak valid atau kedaluwarsa. Upload ulang struk.', status=400)
    fields = {key: request.form.get(key, '') for key in ('confirmed', 'currency', 'amount', 'occurred_on',
              'account_id', 'category_id', 'merchant_name', 'description')}
    review = dict(token=token, extraction=data['extraction'], filename=data['filename'], fallback=False, duplicate=False)
    try:
        if any(len(request.form.getlist(key)) != 1 for key in (*fields, 'analysis_token')):
            raise ValueError('invalid_fields')
        finance_receipts.confirm(business_id, user['id'], token, fields)
    except ValueError as error:
        duplicate = str(error) == 'receipt_duplicate_conflict'
        message = ('Struk sudah tercatat atau dibatalkan. Tidak ada pengeluaran baru dibuat.' if duplicate else
                   'Periksa konfirmasi, nominal rupiah, tanggal, akun dan kategori aktif. Belum ada pengeluaran baru dibuat.')
        return receipt_page(user, business, review=review, values=fields, error=message, status=409 if duplicate else 400)
    except Exception:
        ai_safety.event('request_failed')
        return receipt_page(user, business, review=review, values=fields,
                            error='Konfirmasi belum dapat diproses. Periksa catatan sebelum mencoba lagi.', status=503)
    ai_safety.event('confirmation_accepted')
    flash('Pengeluaran struk sudah tercatat. Konfirmasi ulang yang sama tidak menambah catatan.', 'success')
    return redirect(url_for('finance.dashboard', business_id=business_id, month=fields['occurred_on'][:7]))


# Bank imports have staging writes, but only explicit row POST can write ledger money.
import finance_bank_service as bank
import finance_bank_extract as bank_extract


def bank_safe(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except HTTPException:
            raise
        except (ValueError, file_utils.UploadRejected) as error:
            unavailable=str(error) in ('bank_unavailable','bank_row_unavailable','business_unavailable')
            return 'Impor tidak tersedia.' if unavailable else 'Permintaan belum valid atau status telah berubah. Muat ulang dan periksa isian.', 404 if unavailable else 400
        except Exception:
            ai_safety.event('request_failed')
            return 'Impor belum dapat diproses. Muat ulang dan periksa status sebelum mencoba lagi.',503
    return wrapped


def bank_page_number():
    page=int(request.args.get('page','1'))
    if page<1 or page>100000:raise ValueError('page')
    return page


@finance_bp.route('/business/<int:business_id>/finance/bank-imports')
@bank_safe
@finance_access
def bank_index(business_id,user,business):
    page=bank_page_number();imports=bank.list_imports(business_id,user['id'],page)
    return render_template('finance_bank_index.html',user=user,business=business,imports=imports[:50],page=page,more=len(imports)>50)


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/new')
@bank_safe
@finance_access
def bank_new(business_id,user,business):
    accounts=[a for a in finance.list_accounts(business_id,actor_user_id=user['id']) if a['currency']=='IDR']
    return render_template('finance_bank_new.html',user=user,business=business,accounts=accounts)


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/analyze',methods=['POST'])
@bank_safe
@finance_access
def bank_analyze(business_id,user,business):
    uploads=request.files.getlist('sources')
    try:
        if set(request.files)!={'sources'} or not 1<=len(uploads)<=10:raise ValueError('files')
        account_id=record_id(request.form.get('account_id'))
        bank.account(business_id,account_id,user['id'])
        files=[];total=0
        for upload in uploads:
            raw=upload.stream.read(10*1024*1024+1)
            total+=len(raw)
            if total>25*1024*1024:raise ValueError('aggregate')
            files.append((upload.filename,raw))
        import_id,fallback=bank.analyze(business_id,account_id,files,user['id'])
        if fallback:flash('Ekstraksi belum dapat diandalkan. Tambahkan baris secara manual; belum ada transaksi Finance dibuat.','warning')
        return redirect(url_for('finance.bank_detail',business_id=business_id,import_id=import_id))
    finally:
        for upload in uploads:upload.close()


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>')
@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>/review')
@bank_safe
@finance_access
def bank_detail(business_id,user,business,import_id):
    imp=bank.get_import(business_id,import_id,user['id']);all_rows=bank.get_rows(business_id,import_id,user['id'])
    page=min(bank_page_number(),max(1,(len(all_rows)+49)//50))
    candidates={};candidate_error=False
    if imp['status']=='OPEN':
        try:candidates=bank.candidates(business_id,import_id,user['id'])
        except finance.FinanceError:candidate_error=True
    categories=finance.list_categories(business_id,actor_user_id=user['id'])
    counts={state:sum(r['reconciliation_status']==state for r in all_rows) for state in ('UNMATCHED','MATCHED','POSTED','IGNORED')}
    account=next((a for a in finance.list_accounts(business_id,True,actor_user_id=user['id']) if a['id']==imp['account_id']),None)
    return render_template('finance_bank_detail.html',user=user,business=business,imp=imp,account=account,
        rows=all_rows[(page-1)*50:page*50],candidates=candidates,candidate_error=candidate_error,categories=categories,
        counts=counts,page=page,pages=max(1,(len(all_rows)+49)//50),today=date.today().isoformat())


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>/review',methods=['POST'])
@bank_safe
@finance_access
def bank_review(business_id,user,business,import_id):
    allowed={'csrf_token','row_id','revision','transaction_date','description','direction','amount','reference'}
    if set(request.form)-allowed or any(len(request.form.getlist(k))!=1 for k in request.form):raise ValueError('fields')
    row_id=record_id(request.form['row_id']) if request.form.get('row_id') else None
    bank.edit_row(business_id,import_id,row_id,int(request.form.get('revision','-1')),dict(
        transaction_date=request.form.get('transaction_date'),description=request.form.get('description'),
        direction=request.form.get('direction'),amount_minor=whole_idr(request.form.get('amount')),
        reference=request.form.get('reference') or None),user['id'])
    return redirect(url_for('finance.bank_detail',business_id=business_id,import_id=import_id))


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>/open',methods=['POST'])
@bank_safe
@finance_access
def bank_open(business_id,user,business,import_id):
    if request.form.get('confirmed')!='yes':raise ValueError('confirmation')
    bank.open_import(business_id,import_id,int(request.form.get('revision','-1')),user['id'])
    return redirect(url_for('finance.bank_detail',business_id=business_id,import_id=import_id))


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>/cancel',methods=['POST'])
@bank_safe
@finance_access
def bank_cancel(business_id,user,business,import_id):
    if request.form.get('confirmed')!='yes':raise ValueError('confirmation')
    bank.cancel(business_id,import_id,user['id'])
    return redirect(url_for('finance.bank_detail',business_id=business_id,import_id=import_id))


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>/rows/<int:row_id>/<action>',methods=['POST'])
@bank_safe
@finance_access
def bank_decide(business_id,user,business,import_id,row_id,action):
    if request.form.get('confirmed')!='yes':raise ValueError('confirmation')
    expected={'confirmed','csrf_token'}
    if action=='post':expected|={'category_id','occurred_on','description','counterparty_name'}
    elif action=='match':expected.add('transaction_id')
    if set(request.form)-expected or any(len(request.form.getlist(k))!=1 for k in request.form):raise ValueError('fields')
    fields=None
    if action=='post':fields=dict(category_id=record_id(request.form.get('category_id')),occurred_on=request.form.get('occurred_on'),
        description=request.form.get('description',''),counterparty_name=request.form.get('counterparty_name') or None)
    transaction_id=record_id(request.form.get('transaction_id')) if action=='match' else None
    bank.decide(business_id,import_id,row_id,action,user['id'],transaction_id=transaction_id,fields=fields)
    return redirect(url_for('finance.bank_detail',business_id=business_id,import_id=import_id))


@finance_bp.route('/business/<int:business_id>/finance/assistant')
@bank_safe
@finance_access
def assistant(business_id, user, business):
    # Do not accept prompts, tokens or workflow state in URL parameters.
    if set(request.args) - {'branch_id'}:
        return redirect(url_for('finance.assistant', business_id=business_id))
    actor = {'actor_user_id': user['id']}
    operator_enabled = finance_operator.enabled(business_id)
    return render_template('finance_assistant.html', user=user, business=business,
        assistant_embedded=True, analyst_enabled=finance_analyst.enabled(business_id),
        operator_enabled=operator_enabled, actions=finance_operator.ACTIONS,
        today=date.today().isoformat(), month=date.today().strftime('%Y-%m'),
        accounts=[a for a in finance.list_accounts(business_id, **actor) if a['currency']=='IDR'],
        categories=finance.list_categories(business_id, **actor) if operator_enabled else [],
        invoices=finance.operator_invoice_choices(business_id, **actor) if operator_enabled else [])


@finance_bp.route('/business/<int:business_id>/finance/assistant/route', methods=['POST'])
@finance_access
def assistant_route(business_id, user, business):
    # No model calls, staging, financial execution, tokens or prompt storage here.
    if set(request.args) - {'branch_id'}:
        return jsonify(error='Gunakan formulir Assistant tanpa parameter URL.'), 400
    if request.content_length is None or request.content_length > 16 * 1024:
        return jsonify(error='Permintaan terlalu besar.'), 413
    if not request.is_json:
        return jsonify(error='Gunakan teks dan pilihan file dari Assistant.'), 415
    try:
        payload = ai_safety.json_object(request.get_data().decode('utf-8'))
        text, _, _ = finance_assistant.validate(payload)
        result = finance_assistant.propose(payload)
        result['suggested_action'] = (finance_assistant.operator_action(text)
                                      if result['workflow']=='TEXT_OPERATOR' else '')
        return jsonify(result)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        ai_safety.event('invalid_request')
        return jsonify(error='Teks maksimal 2.000 karakter dan maksimal 10 nama file.'), 400
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(workflow='NEEDS_CLARIFICATION', suggested_action='')


@finance_bp.context_processor
def finance_access_notice():
    import finance_entitlements as entitlement
    business_id=(request.view_args or {}).get('business_id')
    if business_id and entitlement.self_service() and security.current_user():
        return {'finance_read_only':entitlement.flag('KILAS_FINANCE_EMERGENCY_DISABLE') or not entitlement.state(business_id)['active'], 'finance_access_business_id':business_id}
    return {}


@finance_bp.errorhandler(finance.FinanceError)
def entitlement_or_service_error(error):
    if str(error)=='finance_configuration':
        return 'Konfigurasi Finance belum siap. Pengelola perlu memeriksa migrasi dan pengaturan akses.',503
    return 'Tindakan Finance belum tersedia. Periksa masa aktif, akses bisnis, dan data pilihan.',400


@finance_bp.app_url_defaults
def finance_branch_urls(endpoint, values):
    if endpoint == 'finance.start' and not getattr(g, 'finance_branches', None):
        return
    if endpoint.startswith('finance.') and values.get('business_id') == getattr(g, 'finance_business_id', None) and values.get('business_id'):
        values.setdefault('branch_id', g.finance_branch_id or 'all')


@finance_bp.context_processor
def finance_branch_context():
    if not getattr(g, 'finance_business_id', None):
        return {}
    return dict(finance_branch_business_id=g.finance_business_id, finance_branches=g.finance_branches,
        selected_branch=g.finance_branch, selected_branch_id=g.finance_branch_id,
        all_branches=g.finance_branch_id is None, branch_read_only=g.finance_branch_read_only)


def transaction_note(business_id, form):
    category = next((c for c in finance.list_categories(business_id, include_inactive=True)
                     if str(c['id']) == form.get('category_id')), None)
    note = finance._text(form.get('description'), 4000)
    if category and category['name'] in ('Lainnya', 'Pendapatan Lain', 'Pengeluaran Lain'):
        other = finance._text(form.get('other_description'), 1000, True)
        note = other + ('\n' + note if note else '')
    return finance._text(note, 4000)


@finance_bp.route('/business/<int:business_id>/finance/branches', methods=['POST'])
@finance_access
def create_branch(business_id, user, business):
    try:
        branch_id = branches.create_branch(business_id, request.form.get('name'), user['id'])
    except finance.FinanceError as error:
        flash(ERRORS.get(str(error), 'Nama cabang belum valid.'), 'error')
        return redirect(url_for('finance.dashboard', business_id=business_id), code=303)
    return redirect(url_for('finance.dashboard', business_id=business_id, branch_id=branch_id), code=303)


@finance_bp.route('/business/<int:business_id>/finance/settings/<kind>/<int:record_id>', methods=['POST'])
@finance_access
def update_setting(business_id, user, business, kind, record_id):
    if kind not in ('branch', 'account', 'category'):
        abort(404)
    deactivate = request.form.get('action') == 'deactivate'
    destination = url_for('finance.dashboard', business_id=business_id, branch_id='all') if kind == 'branch' and deactivate else None
    return mutate(business_id, lambda: branches.update_record(business_id, kind, record_id,
        name=request.form.get('name'), deactivate=deactivate, actor_user_id=user['id']),
        'Perubahan disimpan. Riwayat tetap tersedia.', destination)


@finance_bp.route('/business/<int:business_id>/finance/transactions/<int:transaction_id>/edit', methods=['GET', 'POST'])
@finance_access
def edit_transaction(business_id, user, business, transaction_id):
    transaction = finance.get_transaction(business_id, transaction_id, actor_user_id=user['id'])
    if not transaction:
        abort(404)
    if transaction['status'] != 'POSTED' or transaction['source_type'] not in (None, '', 'MANUAL', 'FINANCE_OPERATOR', 'FINANCE_RECEIPT'):
        abort(403)
    if request.method == 'POST':
        return mutate(business_id, lambda: finance.update_transaction(business_id, transaction_id,
            amount_minor=whole_idr(request.form.get('amount')), occurred_on=request.form.get('occurred_on'),
            account_id=record_id(request.form.get('account_id')), category_id=record_id(request.form.get('category_id')),
            description=transaction_note(business_id, request.form), actor_user_id=user['id']),
            'Transaksi diperbarui. Riwayat perubahan tersimpan.')
    categories = finance.list_categories(business_id, transaction['direction'], actor_user_id=user['id'])
    is_other = any(c['id'] == transaction['category_id'] and c['name'] in ('Lainnya', 'Pendapatan Lain', 'Pengeluaran Lain') for c in categories)
    description = transaction['description'] or ''
    other_description = ''
    if is_other:
        other_description, _, description = description.partition('\n')
    return render_template('finance_transaction_edit.html', business=business, user=user, transaction=transaction,
        initial_description=description, initial_other_description=other_description,
        accounts=finance.list_accounts(business_id, actor_user_id=user['id']),
        categories=finance.list_categories(business_id, transaction['direction'], actor_user_id=user['id']),
        today=date.today().isoformat())
