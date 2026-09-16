"""Authenticated, beta-only Finance UI; all ledger operations stay in finance_service."""
import calendar
from datetime import date
import os
import re
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
import finance_service as finance
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
        initialized=bool(accounts and categories), month=month, direction=direction,
        today=date.today().isoformat(), account_types={'CASH':'Kas','BANK':'Bank','EWALLET':'E-Wallet','OTHER':'Lainnya'})


def mutate(business_id, action, success):
    try:
        action()
    except finance.FinanceError as error:
        if str(error) in ('transaction_unavailable', 'business_unavailable'):
            abort(404)
        flash(ERRORS.get(str(error), 'Data belum valid. Periksa isian dan coba lagi.'), 'error')
    else:
        flash(success, 'success')
    return redirect(url_for('finance.dashboard', business_id=business_id), code=303)


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
