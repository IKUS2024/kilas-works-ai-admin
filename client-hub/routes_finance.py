"""Authenticated, beta-only Finance UI; all ledger operations stay in finance_service."""
import calendar
from datetime import date
import os
import re
import uuid
from functools import wraps

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
import finance_service as finance
import finance_reports
import finance_analyst
from flask import jsonify, current_app
import security

finance_bp = Blueprint('finance', __name__)


def beta_enabled():
    return os.environ.get('KILAS_FINANCE_BETA', '').strip().lower() in ('true', '1', 'yes', 'on')


def finance_access(view):
    @wraps(view)
    @security.login_required
    def wrapped(business_id, **kwargs):
        user = security.current_user()
        if not beta_enabled() and user['role'] != 'KILAS_ADMIN':
            abort(404)
        business = security.require_business_access(business_id, user=user)
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
    'account_unavailable': 'Akun keuangan tidak tersedia.',
    'account_currency_mismatch': 'Pilih akun dalam rupiah untuk transaksi ini.',
    'category_unavailable': 'Kategori tidak tersedia.',
    'category_direction_mismatch': 'Kategori tidak sesuai dengan jenis transaksi.',
    'project_unavailable': 'Proyek tidak tersedia untuk bisnis ini.',
    'account_exists': 'Akun dengan nama dan jenis tersebut sudah ada.',
    'category_exists': 'Kategori tersebut sudah ada.',
    'invalid_date': 'Tanggal belum valid.',
    'invalid_text': 'Isian terlalu panjang atau tidak valid.',
    'missing_name': 'Nama wajib diisi.',
    'invalid_enum': 'Pilihan belum valid.',
    'invalid_id': 'Pilihan tidak tersedia.',
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


@finance_bp.route('/business/<int:business_id>/finance')
@finance_access
def dashboard(business_id, user, business):
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    direction = request.args.get('direction') or None
    try:
        start, end = period(month)
        if direction not in (None, 'INCOME', 'EXPENSE'):
            raise ValueError('direction')
    except ValueError:
        flash('Periode atau filter belum valid. Pilih kembali.', 'error')
        return redirect(url_for('finance.dashboard', business_id=business_id))
    actor = {'actor_user_id': user['id']}
    accounts = finance.list_accounts(business_id, include_inactive=True, **actor)
    categories = finance.list_categories(business_id, include_inactive=True, **actor)
    summary = finance.get_finance_summary(business_id, start, end, **actor)
    transactions = finance.list_transactions(business_id, start_date=start, end_date=end,
                                            direction=direction, limit=100, **actor)
    return render_template('finance_dashboard.html', user=user, business=business,
        accounts=accounts, categories=categories, summary=summary, transactions=transactions,
        account_map={a['id']: a for a in accounts}, category_map={c['id']: c for c in categories},
        customers=finance.list_customers(business_id, **actor),
        projects=finance.list_finance_projects(business_id, **actor),
        initialized=bool(accounts and categories), month=month, direction=direction,
        analyst_enabled=finance_analyst.enabled(business_id),
        today=date.today().isoformat(), account_types={'CASH':'Kas','BANK':'Bank','EWALLET':'E-Wallet','OTHER':'Lainnya'})


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
            request.form.get('occurred_on'), currency='IDR', description=request.form.get('description'),
            counterparty_name=request.form.get('counterparty_name'),
            customer_id=record_id(request.form['customer_id']) if request.form.get('customer_id') else None,
            project_id=record_id(request.form['project_id']) if request.form.get('project_id') else None,
            actor_user_id=user['id'])
    return mutate(business_id, action, 'Transaksi dicatat.')


@finance_bp.route('/business/<int:business_id>/finance/transactions/<int:transaction_id>/void', methods=['POST'])
@finance_access
def void_transaction(business_id, user, business, transaction_id):
    return mutate(business_id, lambda: finance.void_transaction(business_id, transaction_id, actor_user_id=user['id']),
                  'Transaksi dibatalkan. Riwayat tetap tersimpan.')


@finance_bp.route('/business/<int:business_id>/finance/accounts', methods=['POST'])
@finance_access
def create_account(business_id, user, business):
    return mutate(business_id, lambda: finance.create_account(business_id, request.form.get('name'),
        request.form.get('account_type'), currency='IDR',
        opening_balance_minor=whole_idr(request.form.get('opening_balance', '0'), signed=True),
        actor_user_id=user['id']), 'Akun keuangan ditambahkan.')


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
    customers = finance.list_customers(business_id, include_inactive=True, **actor)
    invoices = finance.list_finance_invoices(business_id, **actor)
    totals = {i['id']: finance.get_invoice_totals(business_id, i['id'], **actor) for i in invoices}
    return render_template('finance_receivables.html', user=user, business=business, customers=customers,
        customer_map={c['id']:c for c in customers}, invoices=invoices, totals=totals,
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
    actor = {'actor_user_id':user['id']}
    invoice = finance.get_finance_invoice(business_id,invoice_id,**actor)
    if not invoice:
        abort(404)
    return render_template('finance_invoice_detail.html',user=user,business=business,invoice=invoice,
        customer=finance.get_customer(business_id,invoice['customer_id'],**actor),
        items=finance.list_invoice_items(business_id,invoice_id,**actor),
        payments=finance.list_invoice_payments(business_id,invoice_id,**actor),
        totals=finance.get_invoice_totals(business_id,invoice_id,**actor),
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
    month = request.args.get('month',date.today().strftime('%Y-%m'))
    try:
        start,end = period(month)
    except ValueError:
        flash('Periode belum valid. Pilih kembali.','error')
        return redirect(url_for('finance.operations',business_id=business_id))
    actor = {'actor_user_id':user['id']}
    rules = finance.list_recurring_expenses(business_id,include_inactive=True,**actor)
    projects = finance.list_finance_projects(business_id,**actor)
    return render_template('finance_operations.html',user=user,business=business,rules=rules,projects=projects,
        project_map={p['id']:p for p in projects},
        attention={r['id']:finance.recurring_needs_attention(business_id,r['id'],**actor) for r in rules if r['is_active']},
        accounts=finance.list_accounts(business_id,**actor),categories=finance.list_categories(business_id,'EXPENSE',**actor),
        contributions=finance.get_project_cash_contribution(business_id,start,end,**actor),
        month=month,today=date.today().isoformat(),max_occurrences=finance.MAX_RECURRING_OCCURRENCES)


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
    result = finance.process_due_recurring_expenses(business_id,date.today(),actor_user_id=user['id'])
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
    try:
        filters=finance_reports.parse_filters(request.args)
        actor={'actor_user_id':user['id']}
        data={name:finance_reports.report_data(name,business_id,filters,user['id']) for name in finance_reports.REPORT_NAMES if name not in ('transactions','invoices')}
        summary=finance.get_cashflow_report(business_id,filters['start'],filters['end'],**actor)
        trend=finance.get_monthly_cashflow_trend(business_id,filters['start'][:7],filters['end'][:7],
            start_date=filters['start'],end_date=filters['end'],**actor)
    except finance.FinanceError as error:
        return render_template('finance_reports.html',user=user,business=business,error=report_error(error)),400
    response=Response(render_template('finance_reports.html',user=user,business=business,filters=filters,
        data=data,summary=summary,trend=trend,directions=finance_reports.DIRECTIONS,
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
@finance_access
def analyst(business_id, user, business):
    if not finance_analyst.enabled(business_id):
        abort(404)
    if request.method == 'GET':
        return render_template('finance_analyst.html', user=user, business=business,
                               month=date.today().strftime('%Y-%m'))
    if request.content_length is None or request.content_length > 8192:
        return jsonify(error='Permintaan terlalu besar.'), 413
    try:
        question, start, scope = finance_analyst.validate(request.get_json(silent=True))
    except (ValueError, TypeError):
        return jsonify(error='Isi pertanyaan dan pilih periode serta fokus yang valid.'), 400
    if not finance_analyst.allow_click(user['id']):
        return jsonify(error='Tunggu sebentar sebelum meminta analisis lagi.'), 429
    try:
        context = finance_analyst.build_context(business_id, user['id'], start, scope)
        result, reason = finance_analyst.generate(question, context)
        if result is not None:
            response = jsonify(context=context, analysis=result)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
    except Exception:
        # Never emit exception messages, finance text, query parameters or credentials.
        reason = 'context_unavailable'
    current_app.logger.warning('FINANCE_ANALYST: %s', reason)
    return jsonify(error=finance_analyst.ERROR), 503
