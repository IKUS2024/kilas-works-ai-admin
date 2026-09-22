"""Authenticated, beta-only Finance UI; all ledger operations stay in finance_service."""
import calendar
import hashlib
from pathlib import Path
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import os
import re
import uuid
from functools import wraps
from werkzeug.exceptions import HTTPException

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
import finance_branches as branches
import finance_service as finance
import finance_reports
import finance_report_pdf
import finance_invoice_view
import finance_collections
import finance_receipts
import file_utils
import finance_analyst
import finance_operator
import finance_assistant
import finance_assistant_flow as assistant_flow
# Import the conversation brain at process startup so syntax/import regressions
# fail the deploy instead of surfacing only after the first Assistant message.
import finance_conversation_brain as finance_conversation_brain
import finance_documents
import finance_assistant_recurring as assistant_recurring
import finance_ai_safety as ai_safety
import finance_fx
from flask import jsonify, current_app, g
import security
import repo

finance_bp = Blueprint('finance', __name__)

PERSONAL_DISABLED_VIEWS = {
    # Personal Finance is intentionally manual-only.
    'assistant','assistant_route','assistant_recognize','assistant_recurring_action',
    'assistant_message','assistant_review','assistant_confirm','assistant_document',
    'analyst','operator','operator_action',
    'receipt_new','receipt_analyze','receipt_confirm',
    'bank_index','bank_new','bank_analyze','bank_detail','bank_review','bank_open',
    'bank_cancel','bank_decide',
    # Personal does not use business receivables / invoice workflows.
    'receivables','create_customer','update_customer','delete_customer','new_invoice',
    'invoice_detail','issue_invoice','void_invoice','update_invoice_notes',
    'archive_invoice','restore_invoice','record_payment','invoice_print','invoice_share',
    'collections','customer_statement','statement_print','statement_share',
    'collection_reminder',
}


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
        choices = request.args.getlist('branch_id') + request.form.getlist('branch_id')
        if len(set(choices)) > 1 or len(request.args.getlist('branch_id')) > 1 or len(request.form.getlist('branch_id')) > 1:
            abort(400)
        selected = choices[0] if choices else None
        workspace_type = 'BUSINESS'
        selected_branch = None
        try:
            if selected not in (None, 'all'):
                selected_branch = branches.get(
                    business_id, record_id(selected), actor_user_id=user['id'])
                workspace_type = selected_branch['workspace_type']
            branch_list = branches.list_branches(
                business_id, user['id'], workspace_type=workspace_type)
        except finance.FinanceError:
            abort(404)

        active_branches = [branch for branch in branch_list if branch['is_active']]
        default_branch = next((branch for branch in active_branches if branch['is_default']), None)
        fallback_branch = default_branch or (active_branches[0] if active_branches else None)
        # Legacy URLs without an explicit branch always resolve to Business, so all
        # pre-workspace Finance data stays in Business exactly as before.
        if selected is None or (selected == 'all' and request.method in ('GET', 'HEAD')):
            selected = str(fallback_branch['id']) if fallback_branch else None
            selected_branch = fallback_branch
        if selected == 'all':
            if request.is_json:
                return jsonify(error='Pilih satu cabang aktif. Data antar cabang tidak digabung.'), 403
            abort(403)
        if selected is not None:
            selected_row = next((branch for branch in branch_list if str(branch['id']) == str(selected)), None)
            if selected_row is None:
                abort(404)
            if not selected_row['is_active']:
                if request.method in ('GET','HEAD') and fallback_branch:
                    selected = str(fallback_branch['id'])
                    selected_row = fallback_branch
                else:
                    if request.is_json:
                        return jsonify(error='Cabang tersebut sudah dihapus atau tidak aktif.'), 403
                    abort(403)
            selected_branch = selected_row
        branch_id = record_id(selected) if selected is not None else None
        g.finance_business_id = business_id
        g.finance_branch_id = branch_id
        g.finance_branches = branch_list
        g.finance_branch = selected_branch
        g.finance_workspace_type = workspace_type
        g.finance_workspace_label = 'Pribadi' if workspace_type == 'PERSONAL' else 'Bisnis'
        g.finance_branch_read_only = branch_id is None or not selected_branch['is_active']
        if workspace_type == 'PERSONAL' and view.__name__ in PERSONAL_DISABLED_VIEWS:
            if request.is_json:
                return jsonify(error='Fitur ini hanya tersedia di Finance Bisnis.'), 403
            flash('Fitur ini hanya tersedia di Finance Bisnis. Finance Pribadi memakai pencatatan manual.', 'info')
            return redirect(url_for(
                'finance.dashboard', business_id=business_id, branch_id=branch_id), code=303)
        if g.finance_branch_read_only and request.method not in ('GET', 'HEAD') and view.__name__ not in ('assistant_message','assistant_recognize'):
            # Setup has no historical branch yet; existing entitlement checks still apply.
            if not branch_list and view.__name__ == 'start' and not choices:
                return view(business_id, user, business, **kwargs)
            if request.is_json:
                return jsonify(error='Pilih satu cabang aktif untuk mencatat atau mengubah transaksi.'), 403
            abort(403)
        if g.finance_branch_read_only and view.__name__ in ('operator', 'receipt_new', 'bank_new', 'new_invoice', 'edit_transaction'):
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
    'invoice_archive_requires_paid': 'Hanya invoice yang sudah lunas penuh yang dapat dihapus dari daftar kerja. Pembayaran dan pembukuan tetap dilindungi.',
    'empty_invoice_total': 'Total invoice harus lebih dari nol sebelum diterbitkan.',
    'overpayment': 'Nominal melebihi sisa tagihan. Muat ulang untuk melihat saldo terbaru.',
    'payment_key_conflict': 'Form pembayaran sudah digunakan. Muat ulang untuk pembayaran baru.',
    'invalid_payment_key': 'Form pembayaran tidak valid. Muat ulang halaman.',
    'invoice_ledger_managed': 'Transaksi ini berasal dari pembayaran invoice dan tidak dapat diubah atau dibatalkan langsung.',
    'invalid_money_minor': 'Nominal belum valid. Gunakan angka; maksimal 2 angka desimal dengan titik atau koma.',
    'account_unavailable': 'Akun tidak tersedia.',
    'account_currency_mismatch': 'Mata uang transaksi harus sama dengan mata uang akun yang dipilih.',
    'account_type_unavailable': 'Tipe tempat uang tidak tersedia. Pilih atau tambahkan tipe lain.',
    'unsupported_currency': 'Mata uang belum didukung Kilas Finance.',
    'fx_same_currency': 'Pilih dua akun dengan mata uang berbeda.',
    'fx_exchange_unavailable': 'Penukaran mata uang tidak tersedia.',
    'category_unavailable': 'Kategori tidak tersedia.',
    'category_direction_mismatch': 'Kategori tidak sesuai dengan jenis transaksi.',
    'category_parent_mismatch': 'Hubungan kategori dan subkategori belum valid.',
    'subcategory_required': 'Pilih subkategori untuk kategori ini.',
    'subcategory_unavailable': 'Subkategori tidak tersedia untuk kategori yang dipilih.',
    'category_has_children': 'Hapus subkategori aktif di bawah kategori ini terlebih dahulu.',
    'project_unavailable': 'Proyek tidak tersedia untuk bisnis ini.',
    'payee_unavailable': 'Penerima tidak tersedia.',
    'payee_exists': 'Nama penerima tersebut sudah ada.',
    'payee_in_use': 'Penerima ini masih dipakai tagihan aktif. Edit atau hapus tagihan tersebut terlebih dahulu.',
    'account_exists': 'Akun dengan nama dan jenis tersebut sudah ada.',
    'category_exists': 'Kategori tersebut sudah ada.',
    'invalid_date': 'Tanggal belum valid.',
    'future_date': 'Tanggal tidak boleh melebihi hari ini.',
    'invalid_text': 'Isian terlalu panjang atau tidak valid.',
    'missing_name': 'Nama wajib diisi.',
    'invalid_enum': 'Pilihan belum valid.',
    'invalid_id': 'Pilihan tidak tersedia.',
    'branch_last_active': 'Sisakan minimal satu cabang aktif. Tambahkan cabang baru sebelum menghapus cabang terakhir.',
    'account_last_active': 'Sisakan minimal satu akun aktif di cabang ini.',
    'account_currency_required': 'Rekening ini masih diperlukan karena mata uang tersebut masih memiliki saldo. Pindahkan atau nolkan saldonya dulu.',
    'account_in_use': 'Akun ini masih dipakai biaya rutin aktif. Ubah biaya rutinnya dulu sebelum menghapus.',
    'category_last_active': 'Sisakan minimal satu kategori Pemasukan dan satu kategori Pengeluaran.',
    'category_in_use': 'Kategori ini masih dipakai biaya rutin aktif. Ubah atau hentikan biaya rutinnya dulu sebelum menghapus.',
    'branch_exists': 'Nama cabang sudah digunakan.',
    'branch_unavailable': 'Cabang tidak tersedia.',
    'branch_mismatch': 'Akun harus berada dalam cabang yang sama.',
    'budget_unavailable': 'Anggaran tidak tersedia.',
}


def whole_idr(value, signed=False):
    if not isinstance(value, str):
        raise finance.FinanceError('invalid_money_minor')
    text = value.strip()
    negative = text.startswith('-')
    if negative:
        if not signed:
            raise finance.FinanceError('invalid_money_minor')
        text = text[1:]
    plain = re.fullmatch(r'[0-9]{1,19}', text)
    grouped = re.fullmatch(r'[0-9]{1,3}(?:[., ][0-9]{3})+', text)
    if not (plain or grouped):
        raise finance.FinanceError('invalid_money_minor')
    digits = re.sub(r'[., ]', '', text)
    amount = int(('-' if negative else '') + digits)
    if not -(2**63) <= amount <= 2**63-1 or (not signed and amount <= 0):
        raise finance.FinanceError('invalid_money_minor')
    return amount


def _money_decimal(value, signed=False):
    """Parse localized decimal money safely without float arithmetic.

    Accepts Indonesian/international decimal separators and grouped thousands,
    e.g. 1250.50, 1250,50, 1.250,50, 1,250.50, and 1 250,50.
    """
    if not isinstance(value, str):
        raise finance.FinanceError('invalid_money_minor')
    text=value.strip()
    negative=text.startswith('-')
    if negative:
        if not signed:
            raise finance.FinanceError('invalid_money_minor')
        text=text[1:].strip()
    if not text or len(text)>40 or not re.fullmatch(r'[0-9][0-9., ]*|[.,][0-9]+',text):
        raise finance.FinanceError('invalid_money_minor')
    text=text.replace(' ','')
    if text.startswith(('.',',')):
        text='0'+text

    # A repeated single separator with groups of exactly three digits is a
    # thousands-grouped integer. Otherwise a single separator is decimal.
    grouped_integer = bool(re.fullmatch(r'[0-9]{1,3}(?:[.,][0-9]{3})+',text))
    normalized=None
    if grouped_integer:
        normalized=re.sub(r'[.,]','',text)
    elif '.' in text and ',' in text:
        decimal_sep='.' if text.rfind('.')>text.rfind(',') else ','
        group_sep=',' if decimal_sep=='.' else '.'
        integer_part,fraction=text.rsplit(decimal_sep,1)
        if not re.fullmatch(r'[0-9]{1,3}(?:'+re.escape(group_sep)+r'[0-9]{3})*|[0-9]+',integer_part):
            raise finance.FinanceError('invalid_money_minor')
        if not re.fullmatch(r'[0-9]{1,6}',fraction):
            raise finance.FinanceError('invalid_money_minor')
        normalized=integer_part.replace(group_sep,'')+'.'+fraction
    elif '.' in text or ',' in text:
        sep='.' if '.' in text else ','
        if text.count(sep)!=1:
            raise finance.FinanceError('invalid_money_minor')
        integer_part,fraction=text.split(sep,1)
        if not integer_part.isdigit() or not re.fullmatch(r'[0-9]{1,6}',fraction):
            raise finance.FinanceError('invalid_money_minor')
        normalized=integer_part+'.'+fraction
    elif text.isdigit():
        normalized=text
    else:
        raise finance.FinanceError('invalid_money_minor')

    try:
        amount=Decimal(normalized)
    except InvalidOperation:
        raise finance.FinanceError('invalid_money_minor') from None
    if negative:
        amount=-amount
    if not amount.is_finite():
        raise finance.FinanceError('invalid_money_minor')
    return amount


def currency_amount(value, currency, signed=False):
    """Parse all Finance money inputs as decimals, then round to ledger precision."""
    currency=finance._currency(currency)
    amount=_money_decimal(value,signed=signed)
    scale=Decimal(100)
    with localcontext() as context:
        context.prec=60
        minor=amount*scale
        minor=int(minor.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    if not -(2**63)<=minor<=2**63-1 or (not signed and minor<=0):
        raise finance.FinanceError('invalid_money_minor')
    return minor


def money_label(value,currency):
    return finance_fx.format_money(int(value), finance._currency(currency))


@finance_bp.app_template_filter('finance_money')
def format_money(value,currency):
    return money_label(value,currency)


@finance_bp.app_template_filter('finance_input_money')
def format_input_money(value,currency):
    currency=finance._currency(currency)
    if type(value) is not int:
        raise finance.FinanceError('invalid_money_minor')
    return f'{finance_fx.major(value,currency):.2f}'


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
    """Membership-only, read-only multi-business overview; money stays grouped by currency."""
    user=security.current_user()
    import finance_entitlements as entitlement
    if not (beta_enabled() or entitlement.self_service()) and user['role']!='KILAS_ADMIN':abort(404)
    businesses=repo.list_businesses_for_user(user['id']);selected=request.args.get('business_id','all')
    business=next((b for b in businesses if str(b['id'])==selected),None)
    if selected!='all' and business is None:abort(404)
    month=request.args.get('month',date.today().strftime('%Y-%m'))
    split_period='period_month' in request.args or 'period_year' in request.args
    if split_period:month=request.args.get('period_year','')+'-'+request.args.get('period_month','')
    try:
        start,end=period(month)
        if month>date.today().strftime('%Y-%m'):raise ValueError('future_month')
        end=min(end,date.today().isoformat())
    except ValueError:
        flash('Periode atau filter belum valid. Bulan masa depan belum dapat dipilih.','error')
        return redirect(url_for('finance.overview',business_id=selected))
    if business is not None:return redirect(url_for('finance.dashboard',business_id=business['id'],month=month))
    if split_period:return redirect(url_for('finance.overview',month=month))
    totals={}
    breakdown=[]
    open_count=overdue_count=0
    for business in businesses:
        security.require_business_access(business['id'],user=user)
        business_cash={}
        business_aging={}
        business_open=business_overdue=0
        # Overview is explicitly Business-only. Personal workspaces are never
        # merged into business dashboards or multi-business totals.
        business_branches=branches.list_branches(
            business['id'],user['id'],workspace_type='BUSINESS')
        for branch in business_branches:
            with branches.scope(business['id'],branch['id'],user['id']):
                branch_cash=finance.get_finance_summaries(
                    business['id'],start,end,actor_user_id=user['id'])
                branch_aging=finance_collections.position(
                    business['id'],user['id'],today=end)['aging']
            for row in branch_cash:
                item=business_cash.setdefault(
                    row['currency'],dict(currency=row['currency'],
                        total_income_minor=0,total_expense_minor=0,
                        net_cashflow_minor=0,transaction_count=0))
                item['total_income_minor']+=row['total_income_minor']
                item['total_expense_minor']+=row['total_expense_minor']
                item['net_cashflow_minor']=item['total_income_minor']-item['total_expense_minor']
                item['transaction_count']+=row.get('transaction_count',0)
            business_open+=branch_aging['open_invoice_count']
            business_overdue+=branch_aging['overdue_invoice_count']
            for row in branch_aging['by_currency']:
                item=business_aging.setdefault(
                    row['currency'],dict(currency=row['currency'],
                        total_outstanding_minor=0,total_overdue_minor=0,
                        open_invoice_count=0,overdue_invoice_count=0))
                item['total_outstanding_minor']+=row['total_outstanding_minor']
                item['total_overdue_minor']+=row['total_overdue_minor']
                item['open_invoice_count']+=row.get('open_invoice_count',0)
                item['overdue_invoice_count']+=row.get('overdue_invoice_count',0)
        cash=[business_cash[code] for code in finance.SUPPORTED_CURRENCIES if code in business_cash]
        aging=dict(
            by_currency=[business_aging[code] for code in finance.SUPPORTED_CURRENCIES if code in business_aging],
            open_invoice_count=business_open,overdue_invoice_count=business_overdue)
        breakdown.append(dict(business=business,cash_summaries=cash,receivables=aging))
        for row in cash:
            item=totals.setdefault(row['currency'],dict(currency=row['currency'],total_income_minor=0,total_expense_minor=0,
                net_cashflow_minor=0,total_outstanding_minor=0,total_overdue_minor=0))
            item['total_income_minor']+=row['total_income_minor'];item['total_expense_minor']+=row['total_expense_minor']
            item['net_cashflow_minor']=item['total_income_minor']-item['total_expense_minor']
        for row in aging['by_currency']:
            item=totals.setdefault(row['currency'],dict(currency=row['currency'],total_income_minor=0,total_expense_minor=0,
                net_cashflow_minor=0,total_outstanding_minor=0,total_overdue_minor=0))
            item['total_outstanding_minor']+=row['total_outstanding_minor'];item['total_overdue_minor']+=row['total_overdue_minor']
        open_count+=aging['open_invoice_count'];overdue_count+=aging['overdue_invoice_count']
    totals_by_currency=[totals[c] for c in finance.SUPPORTED_CURRENCIES if c in totals]
    if not totals_by_currency:totals_by_currency=[dict(currency='IDR',total_income_minor=0,total_expense_minor=0,net_cashflow_minor=0,total_outstanding_minor=0,total_overdue_minor=0)]
    selected_year=int(month[:4]);current_year,current_month=date.today().year,date.today().month
    period_years=sorted(set(range(max(1,current_year-10),current_year+1))|{selected_year})
    return Response(render_template('finance_overview.html',user=user,businesses=businesses,business=None,month=month,
        period_years=period_years,selected_year=selected_year,current_year=current_year,current_month=current_month,
        totals_by_currency=totals_by_currency,open_invoice_count=open_count,overdue_invoice_count=overdue_count,
        breakdown=breakdown,as_of=end),headers={'Cache-Control':'private, no-store'})

@finance_bp.route('/business/<int:business_id>/finance/workspaces')
@security.login_required
def workspace_choice(business_id):
    user=security.current_user()
    import finance_entitlements as entitlement
    if not (beta_enabled() or entitlement.self_service()) and user['role']!='KILAS_ADMIN':
        abort(404)
    business=security.require_business_access(business_id,user=user)
    business_branches=branches.list_branches(
        business_id,user['id'],workspace_type='BUSINESS')
    personal_branches=branches.list_branches(
        business_id,user['id'],workspace_type='PERSONAL')
    state=entitlement.state(business_id)
    return render_template(
        'finance_workspace_choice.html',business=business,user=user,
        entitlement=state,
        business_ready=any(row['is_active'] for row in business_branches),
        personal_ready=any(row['is_active'] for row in personal_branches),
    )


@finance_bp.route('/business/<int:business_id>/finance/workspaces/<workspace_type>',methods=['POST'])
@security.login_required
def enter_workspace(business_id,workspace_type):
    user=security.current_user()
    import finance_entitlements as entitlement
    if not (beta_enabled() or entitlement.self_service()) and user['role']!='KILAS_ADMIN':
        abort(404)
    security.require_business_access(business_id,user=user)
    try:
        workspace_type=branches.workspace(workspace_type)
        rows=branches.list_branches(
            business_id,user['id'],workspace_type=workspace_type)
        active=next((row for row in rows if row['is_active'] and row['is_default']),None)
        active=active or next((row for row in rows if row['is_active']),None)
        if active is None:
            entitlement.require_write(business_id,user['id'])
            if workspace_type=='PERSONAL':
                branch_id=branches.ensure_personal(business_id,user['id'])
            else:
                branch_id=branches.default(business_id,user['id'])
            active=branches.get(
                business_id,branch_id,active=True,actor_user_id=user['id'])
        if entitlement.state(business_id)['active']:
            with branches.scope(business_id,active['id'],user['id']):
                finance.ensure_finance_defaults(
                    business_id,actor_user_id=user['id'])
    except finance.FinanceError as error:
        flash(ERRORS.get(str(error),'Workspace Finance belum dapat dibuka.'),'error')
        return redirect(url_for('finance.workspace_choice',business_id=business_id),code=303)
    return redirect(
        url_for('finance.dashboard',business_id=business_id,branch_id=active['id']),
        code=303)


@finance_bp.route('/business/<int:business_id>/finance')
@finance_access
def dashboard(business_id, user, business):
    if g.finance_branch_id is not None and g.finance_branch and not g.finance_branch['is_active']:
        active = next((branch for branch in g.finance_branches if branch['is_active']), None)
        return redirect(url_for('finance.dashboard', business_id=business_id,
                                branch_id=active['id'] if active else 'all'), code=303)
    today_value = finance.business_today(business_id)
    current_value = today_value.strftime('%Y-%m')
    period_mode = request.args.get('period_mode', 'month')
    view = request.args.get('view')
    direction = (request.args.get('direction') or None) if view == 'transactions' else None
    display_currency = request.args.get('display_currency', 'IDR')
    if display_currency not in finance.SUPPORTED_CURRENCIES:
        display_currency = 'IDR'
    split_period = 'period_month' in request.args or 'period_year' in request.args
    split_range = any(key in request.args for key in (
        'range_start_month', 'range_start_year', 'range_end_month', 'range_end_year'))
    month = request.args.get('month', current_value)
    range_start = request.args.get('range_start')
    range_end = request.args.get('range_end')
    if period_mode == 'month' and split_period:
        month = request.args.get('period_year', '') + '-' + request.args.get('period_month', '')
    if period_mode == 'range' and split_range:
        range_start = request.args.get('range_start_year', '') + '-' + request.args.get('range_start_month', '')
        range_end = request.args.get('range_end_year', '') + '-' + request.args.get('range_end_month', '')
    month_names = ('Januari','Februari','Maret','April','Mei','Juni',
                   'Juli','Agustus','September','Oktober','November','Desember')
    label_for = lambda value: month_names[int(value[5:7])-1] + ' ' + value[:4]
    actor = {'actor_user_id': user['id']}
    try:
        if direction not in (None, 'INCOME', 'EXPENSE'):
            raise ValueError('direction')
        if period_mode == 'month':
            start, end = period(month)
            if month > current_value:
                raise ValueError('future_month')
            end = min(end, today_value.isoformat())
            period_label = label_for(month)
            period_query = {'period_mode':'month','month':month,'display_currency':display_currency}
        elif period_mode == 'range':
            range_start = range_start or f'{today_value.year:04d}-01'
            range_end = range_end or current_value
            start, _ = period(range_start)
            _, end = period(range_end)
            if range_start > range_end or range_end > current_value:
                raise ValueError('future_or_reverse_range')
            end = min(end, today_value.isoformat())
            month = range_end
            period_label = label_for(range_start) + ' – ' + label_for(range_end)
            period_query = {'period_mode':'range','range_start':range_start,'range_end':range_end,
                            'display_currency':display_currency}
        elif period_mode == 'all':
            bounds = finance.get_transaction_date_bounds(business_id, **actor)
            start = bounds['first_on'] or today_value.isoformat()
            end = today_value.isoformat()
            month = current_value
            period_label = 'Semua transaksi'
            period_query = {'period_mode':'all','display_currency':display_currency}
        else:
            raise ValueError('period_mode')
    except (ValueError, finance.FinanceError):
        flash('Periode atau filter belum valid. Bulan masa depan belum dapat dipilih.', 'error')
        return redirect(url_for('finance.dashboard', business_id=business_id,
                                branch_id=g.finance_branch_id or 'all'))
    branch_value = g.finance_branch_id or 'all'
    if period_mode == 'month' and split_period:
        return redirect(url_for('finance.dashboard', business_id=business_id, branch_id=branch_value,
                                direction=direction, view=view, **period_query))
    if period_mode == 'range' and split_range:
        return redirect(url_for('finance.dashboard', business_id=business_id, branch_id=branch_value,
                                direction=direction, view=view, **period_query))

    selected_year = int(month[:4])
    current_year, current_month = today_value.year, today_value.month
    range_start_value = range_start if period_mode == 'range' else f'{selected_year:04d}-01'
    range_end_value = range_end if period_mode == 'range' else month
    relevant_years = {selected_year, int(range_start_value[:4]), int(range_end_value[:4])}
    period_years = sorted(set(range(max(1, current_year - 10), current_year + 1)) | relevant_years)
    accounts = finance.list_accounts(business_id, include_inactive=True, **actor)
    categories = finance.list_categories(business_id, include_inactive=True, include_children=True, **actor)
    budget_rows = finance.list_monthly_budgets(business_id, month, **actor)

    # One ledger snapshot feeds every current-balance surface. Archived/deactivated
    # accounts remain available to historical reports, but "Saldo tersedia" is strictly
    # the sum of ACTIVE accounts so a removed account cannot remain in the visible total.
    balances = finance.get_account_balance_report(business_id, today_value.isoformat(), user['id'])
    active_balances = [item for item in balances if item['is_active']]
    balance_totals = finance.aggregate_account_balances_by_currency(active_balances)

    # Period cash flow only shows currencies that actually have transactions in the period.
    # A foreign opening balance belongs to current cash, not to period income/expense.
    summary_map = {row['currency']:dict(row) for row in finance.get_finance_summaries(
        business_id, start, end, **actor)}
    if not summary_map:
        summary_map['IDR'] = dict(currency='IDR', total_income_minor=0, total_expense_minor=0,
                                  net_cashflow_minor=0, transaction_count=0)
    summaries = [summary_map[code] for code in finance.SUPPORTED_CURRENCIES if code in summary_map]
    summary = summary_map.get('IDR', dict(currency='IDR', total_income_minor=0,
        total_expense_minor=0, net_cashflow_minor=0, transaction_count=0))

    display_options = ['IDR']
    display_options += [a['currency'] for a in accounts
                        if a.get('is_active') and a.get('currency') != 'IDR']
    display_options += [row['currency'] for row in summaries if row['currency'] != 'IDR']
    display_options += [row['currency'] for row in budget_rows if row['currency'] != 'IDR']
    display_options = list(dict.fromkeys(display_options))
    if display_currency not in display_options:
        display_currency = 'IDR'
        period_query['display_currency'] = display_currency
    fx = finance_fx.snapshot(display_options)
    balance_displays = finance_fx.balance_displays(balance_totals, fx, display_options)
    estimated_balance_idr = finance_fx.convert_total(balance_totals, 'IDR', fx)
    balance_total_display = balance_displays.get(display_currency, {}).get('value', 'Kurs belum lengkap')
    period_income_minor = finance_fx.convert_total(summaries, display_currency, fx, field='total_income_minor')
    period_expense_minor = finance_fx.convert_total(summaries, display_currency, fx, field='total_expense_minor')
    period_net_minor = finance_fx.convert_total(summaries, display_currency, fx, field='net_cashflow_minor')
    period_income_display = ('Kurs belum lengkap' if period_income_minor is None
                             else finance_fx.format_money(period_income_minor, display_currency))
    period_expense_display = ('Kurs belum lengkap' if period_expense_minor is None
                              else finance_fx.format_money(period_expense_minor, display_currency))
    period_net_display = ('Kurs belum lengkap' if period_net_minor is None
                          else finance_fx.format_money(period_net_minor, display_currency))
    fx_status_label = ('Kurs belum tersedia' if fx.get('source') == 'unavailable'
                       else f"Kurs terbaru {fx.get('source')} · {fx.get('date') or 'tanggal tidak tersedia'}"
                            + (' · data tertunda' if fx.get('stale') else ''))
    budget_total_minor = finance_fx.convert_total(
        [{'currency':row['currency'],'balance_minor':row['amount_minor']} for row in budget_rows],
        display_currency, fx) if budget_rows else 0
    budget_total_display = ('Kurs belum lengkap' if budget_total_minor is None
                            else finance_fx.format_money(budget_total_minor, display_currency))
    budget_remaining_minor = (None if not budget_rows or budget_total_minor is None or period_expense_minor is None
                              else budget_total_minor - period_expense_minor)
    budget_remaining_display = ('Belum diatur' if not budget_rows else
                                ('Kurs belum lengkap' if budget_remaining_minor is None
                                 else finance_fx.format_money(budget_remaining_minor, display_currency)))
    budget_percent = (0 if not budget_rows or not budget_total_minor or period_expense_minor is None else
                      min(999, round(period_expense_minor * 100 / budget_total_minor)))
    balances = [dict(item) for item in balances]
    for item in balances:
        item['idr_estimate_minor'] = finance_fx.to_idr(item['balance_minor'], item['currency'], fx)
        converted = finance_fx.convert_total(
            [{'currency':item['currency'],'balance_minor':item['balance_minor']}],
            display_currency, fx)
        item['display_balance_minor'] = converted
        item['display_balance_value'] = ('Kurs belum lengkap' if converted is None
                                         else finance_fx.format_money(converted, display_currency))

    show_transactions = view == 'transactions'
    show_accounts = view == 'accounts'

    # HomeBudget-style account view only shows active accounts. Archived/deactivated
    # accounts remain in the ledger and totals for audit/accounting, but disappear
    # from the normal account manager as requested.
    account_balance_rows = active_balances
    account_type_options = finance.list_account_type_options(business_id, **actor)
    account_type_group_labels = [item['name'] for item in account_type_options]
    for item in account_balance_rows:
        label = item.get('account_type_label') or finance.LEGACY_ACCOUNT_TYPE_LABELS.get(
            item.get('account_type'), 'Lainnya')
        if label not in account_type_group_labels:
            account_type_group_labels.append(label)
    selected_account = None
    transaction_account_id = None
    raw_account_id = request.args.get('account_id')
    if raw_account_id:
        try:
            candidate_account_id = record_id(raw_account_id)
        except finance.FinanceError:
            candidate_account_id = None
        candidate_account = next(
            (item for item in account_balance_rows if item['id'] == candidate_account_id), None)
        if candidate_account:
            if show_accounts:
                selected_account = candidate_account
            elif show_transactions:
                transaction_account_id = candidate_account['id']
    if show_accounts and selected_account is None:
        selected_account = account_balance_rows[0] if account_balance_rows else None
    transaction_account = next(
        (item for item in account_balance_rows if item['id'] == transaction_account_id), None)

    transaction_page_size = 10
    transaction_page = 1
    transaction_total = 0
    transaction_page_count = 1
    transaction_page_items = [1]
    transactions = []
    if show_transactions:
        try:
            transaction_page = int(request.args.get('page', '1'))
            if transaction_page < 1 or transaction_page > 100000:
                raise ValueError('page')
        except (TypeError, ValueError):
            transaction_page = 1
        transaction_total = finance.count_transactions(
            business_id, start_date=start, end_date=end, direction=direction,
            status='POSTED', account_id=transaction_account_id, **actor)
        transaction_page_count = max(1, (transaction_total + transaction_page_size - 1) // transaction_page_size)
        if transaction_page > transaction_page_count:
            target = transaction_page_count
            args = dict(period_query, branch_id=branch_value, view='transactions', page=target)
            if direction:
                args['direction'] = direction
            if transaction_account_id:
                args['account_id'] = transaction_account_id
            return redirect(url_for('finance.dashboard', business_id=business_id, **args))
        transactions = [dict(row) for row in finance.list_transactions(
            business_id, start_date=start, end_date=end, direction=direction,
            status='POSTED', account_id=transaction_account_id, limit=transaction_page_size,
            offset=(transaction_page - 1) * transaction_page_size, **actor)]
        for row in transactions:
            converted = finance_fx.convert_total(
                [{'currency':row['currency'],'balance_minor':row['amount_minor']}],
                display_currency, fx)
            row['display_amount_minor'] = converted
            row['display_amount_value'] = ('Kurs belum lengkap' if converted is None
                                           else finance_fx.format_money(converted, display_currency))
        if transaction_page_count <= 7:
            transaction_page_items = list(range(1, transaction_page_count + 1))
        else:
            visible = sorted({1, transaction_page_count, transaction_page - 1,
                              transaction_page, transaction_page + 1})
            visible = [page for page in visible if 1 <= page <= transaction_page_count]
            transaction_page_items = []
            previous = None
            for page in visible:
                if previous is not None and page - previous > 1:
                    transaction_page_items.append(None)
                transaction_page_items.append(page)
                previous = page
    transaction_query = dict(period_query, branch_id=branch_value, view='transactions')
    if direction:
        transaction_query['direction'] = direction
    if transaction_account_id:
        transaction_query['account_id'] = transaction_account_id
    breakdown = []
    if g.finance_branch_id is None:
        for branch in g.finance_branches:
            with branches.scope(business_id, branch['id'], user['id']):
                branch_balances = finance.get_account_balance_report(
                    business_id, today_value.isoformat(), user['id'])
                branch_totals = finance.aggregate_account_balances_by_currency(
                    [item for item in branch_balances if item['is_active']])
                branch_map = {row['currency']:dict(row) for row in finance.get_finance_summaries(
                    business_id, start, end, **actor)}
                if not branch_map:
                    branch_map['IDR'] = dict(currency='IDR', total_income_minor=0,
                        total_expense_minor=0, net_cashflow_minor=0, transaction_count=0)
                branch_summaries = [
                    branch_map[code] for code in finance.SUPPORTED_CURRENCIES if code in branch_map]
                breakdown.append(dict(branch=branch, summaries=branch_summaries,
                    summary=branch_map.get('IDR', dict(currency='IDR', total_income_minor=0,
                        total_expense_minor=0, net_cashflow_minor=0, transaction_count=0))))

    # Dashboard presentation reads reuse the existing scoped Finance services.
    month_index = int(month[:4]) * 12 + int(month[5:7]) - 1
    month_at = lambda index: f'{index // 12:04d}-{index % 12 + 1:02d}'
    previous_month, next_month = month_at(month_index - 1), month_at(month_index + 1)
    dashboard_trend = []
    recent_activity = []
    recurring_items = []
    payee_count = 0
    if not show_transactions and not show_accounts:
        native_trend = finance.get_monthly_cashflow_trends(
            business_id, month_at(max(12, month_index - 5)), month,
            end_date=min(period(month)[1], today_value.isoformat()), **actor)
        trend_by_month = {}
        for row in native_trend:
            trend_by_month.setdefault(row['month'], []).append(row)
        for trend_month in sorted(trend_by_month):
            rows = trend_by_month[trend_month]
            income_minor = finance_fx.convert_total(rows, display_currency, fx, field='income_minor')
            expense_minor = finance_fx.convert_total(rows, display_currency, fx, field='expense_minor')
            if income_minor is None or expense_minor is None:
                dashboard_trend = []
                break
            dashboard_trend.append(dict(
                month=trend_month, currency=display_currency,
                income_minor=income_minor, expense_minor=expense_minor))
        recurring_items = finance.list_recurring_expenses(business_id, **actor)
        payee_count = len({
            row['name'].strip().casefold()
            for row in finance.list_payee_summaries(business_id, **actor)
            if row.get('name')
        })

    balance_total = next((row['balance_minor'] for row in balance_totals if row['currency']=='IDR'), 0)
    finance_workspace_personal = getattr(g,'finance_workspace_type','BUSINESS') == 'PERSONAL'
    return render_template('finance_dashboard.html', user=user, business=business,
        period_start=start, period_end=end, period_mode=period_mode, period_label=period_label,
        period_query=period_query, range_start_value=range_start_value, range_end_value=range_end_value,
        transaction_limit=transaction_page_size, transaction_page_size=transaction_page_size,
        transaction_page=transaction_page, transaction_total=transaction_total,
        transaction_page_count=transaction_page_count, transaction_page_items=transaction_page_items,
        transaction_query=transaction_query,
        balances=balances, balance_totals=balance_totals, balance_total=balance_total,
        estimated_balance_idr=estimated_balance_idr, fx=fx, balance_displays=balance_displays,
        balance_total_display=balance_total_display, period_income_display=period_income_display,
        period_expense_display=period_expense_display, period_net_display=period_net_display,
        fx_status_label=fx_status_label,
        budget_rows=budget_rows, budget_total_display=budget_total_display,
        budget_remaining_display=budget_remaining_display, budget_percent=budget_percent,
        display_currency=display_currency, display_options=display_options,
        exchanges=finance.list_currency_exchanges(business_id,user['id'],50),
        supported_currencies=finance.SUPPORTED_CURRENCIES, branch_breakdown=breakdown,
        businesses=repo.list_businesses_for_user(user['id']),
        accounts=accounts, account_balance_rows=account_balance_rows, selected_account=selected_account,
        transaction_account=transaction_account, transaction_account_id=transaction_account_id,
        categories=categories, summary=summary, summaries=summaries,
        transactions=transactions, dashboard_trend=dashboard_trend, recent_activity=recent_activity,
        recurring_items=recurring_items, payee_count=payee_count, previous_month=previous_month,
        next_month=next_month if next_month <= current_value else None,
        collection_summary=finance_collections.position(business_id,user['id'])['aging'],
        account_map={a['id']: a for a in accounts}, category_map={c['id']: c for c in categories},
        customers=[] if finance_workspace_personal else finance.list_customers(business_id, **actor),
        projects=[] if finance_workspace_personal else finance.list_finance_projects(business_id, **actor),
        payee_names=[row['name'] for row in finance.list_payees(business_id, **actor)],
        initialized=bool(accounts and categories), month=month, month_label=period_label,
        direction=direction, view=view, show_transactions=show_transactions, show_accounts=show_accounts,
        period_years=period_years, selected_year=selected_year,
        current_year=current_year, current_month=current_month,
        analyst_enabled=(False if finance_workspace_personal else finance_analyst.enabled(business_id)),
        operator_enabled=(False if finance_workspace_personal else finance_operator.enabled(business_id)),
        account_type_options=account_type_options,
        account_type_group_labels=account_type_group_labels,
        today=today_value.isoformat(), account_types=finance.LEGACY_ACCOUNT_TYPE_LABELS)



@finance_bp.route('/business/<int:business_id>/finance/payees', methods=['GET', 'POST'])
@finance_access
def payees(business_id, user, business):
    display_currency = request.values.get('display_currency', 'IDR')
    if display_currency not in finance.SUPPORTED_CURRENCIES:
        display_currency = 'IDR'
    if request.method == 'POST':
        destination = url_for(
            'finance.payees', business_id=business_id,
            branch_id=g.finance_branch_id, display_currency=display_currency)
        return mutate(
            business_id,
            lambda: finance.create_payee(
                business_id, request.form.get('name'), actor_user_id=user['id']),
            'Penerima ditambahkan.',
            destination)

    native = finance.list_payee_summaries(business_id, actor_user_id=user['id'])
    currencies = ['IDR'] + [row['currency'] for row in native if row['currency'] != 'IDR']
    currencies = list(dict.fromkeys(currencies))
    if display_currency not in currencies:
        currencies.append(display_currency)
    fx = finance_fx.snapshot(currencies)

    grouped = {}
    for row in native:
        name = (row['name'] or '').strip()
        if not name:
            continue
        item = grouped.setdefault(name, dict(
            payee_id=row.get('payee_id'), name=name, native_rows=[],
            transaction_count=0, last_paid_on=row['last_paid_on']))
        if not item.get('payee_id') and row.get('payee_id'):
            item['payee_id'] = row['payee_id']
        item['native_rows'].append(dict(currency=row['currency'], total_minor=int(row['total_minor'])))
        item['transaction_count'] += int(row['transaction_count'])
        if (row['last_paid_on'] or '') > (item['last_paid_on'] or ''):
            item['last_paid_on'] = row['last_paid_on']

    query = (request.args.get('q') or '').strip()[:160]
    items = []
    for item in grouped.values():
        if query and query.casefold() not in item['name'].casefold():
            continue
        total_minor = finance_fx.convert_total(item['native_rows'], display_currency, fx, field='total_minor')
        item['total_display'] = ('Kurs belum lengkap' if total_minor is None
                                 else finance_fx.format_money(total_minor, display_currency))
        item['native_labels'] = [finance_fx.format_money(row['total_minor'], row['currency'])
                                 for row in item['native_rows']]
        items.append(item)
    items.sort(key=lambda item: (item['last_paid_on'] or '', item['name'].casefold()), reverse=True)

    try:
        page = max(1, int(request.args.get('page', '1')))
    except (TypeError, ValueError):
        page = 1
    page_size = 10
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    visible = items[(page - 1) * page_size:page * page_size]
    fx_status_label = ('Kurs belum tersedia' if fx.get('source') == 'unavailable'
                       else f"Kurs terbaru {fx.get('source')} · {fx.get('date') or 'tanggal tidak tersedia'}"
                            + (' · data tertunda' if fx.get('stale') else ''))
    return render_template(
        'finance_payees.html', user=user, business=business, payees=visible,
        payee_total=total, page=page, pages=pages, q=query,
        display_currency=display_currency, display_options=currencies,
        fx_status_label=fx_status_label)


def _payee_destination(business_id):
    query = (request.form.get('q') or '').strip()[:160]
    try:
        page = max(1, int(request.form.get('page') or '1'))
    except (TypeError, ValueError):
        page = 1
    display_currency = request.form.get('display_currency') or 'IDR'
    if display_currency not in finance.SUPPORTED_CURRENCIES:
        display_currency = 'IDR'
    return url_for(
        'finance.payees', business_id=business_id, branch_id=g.finance_branch_id,
        q=query or None, page=page, display_currency=display_currency)


@finance_bp.route('/business/<int:business_id>/finance/payees/<int:payee_id>/edit', methods=['POST'])
@finance_access
def update_payee(business_id, user, business, payee_id):
    return mutate(
        business_id,
        lambda: finance.update_payee(
            business_id, payee_id, request.form.get('name'),
            actor_user_id=user['id']),
        'Penerima diperbarui.',
        _payee_destination(business_id))


@finance_bp.route('/business/<int:business_id>/finance/payees/<int:payee_id>/delete', methods=['POST'])
@finance_access
def delete_payee(business_id, user, business, payee_id):
    return mutate(
        business_id,
        lambda: finance.deactivate_payee(
            business_id, payee_id, actor_user_id=user['id']),
        'Penerima dihapus dari daftar aktif. Riwayat transaksi tetap tersimpan.',
        _payee_destination(business_id))


@finance_bp.route('/business/<int:business_id>/finance/budget', methods=['GET', 'POST'])
@finance_access
def budget(business_id, user, business):
    today_value = finance.business_today(business_id)
    month = request.values.get('month') or today_value.strftime('%Y-%m')
    try:
        start, end = period(month)
    except (ValueError, finance.FinanceError):
        flash('Bulan anggaran belum valid.', 'error')
        return redirect(url_for('finance.budget', business_id=business_id,
                                branch_id=g.finance_branch_id), code=303)

    accounts = finance.list_accounts(business_id, actor_user_id=user['id'])
    existing = finance.list_monthly_budgets(business_id, month, actor_user_id=user['id'])
    display_options = ['IDR']
    display_options += [a['currency'] for a in accounts if a['currency'] != 'IDR']
    display_options += [row['currency'] for row in existing if row['currency'] != 'IDR']
    display_options = list(dict.fromkeys(display_options))
    display_currency = request.values.get('display_currency') or 'IDR'
    if display_currency not in finance.SUPPORTED_CURRENCIES:
        display_currency = 'IDR'
    if display_currency not in display_options:
        display_options.append(display_currency)

    if request.method == 'POST':
        action = request.form.get('action', 'save')
        destination = url_for(
            'finance.budget', business_id=business_id,
            branch_id=g.finance_branch_id, month=month,
            display_currency=display_currency)

        if action == 'create_category':
            return mutate(
                business_id,
                lambda: finance.create_category(
                    business_id, 'EXPENSE', request.form.get('name'),
                    actor_user_id=user['id']),
                'Kategori pengeluaran ditambahkan.',
                destination)

        if action == 'rename_category':
            category_id = record_id(request.form.get('category_id'))

            def rename_expense_category():
                categories = finance.list_categories(
                    business_id, 'EXPENSE', include_inactive=True,
                    actor_user_id=user['id'])
                if not any(category['id'] == category_id for category in categories):
                    raise finance.FinanceError('category_unavailable')
                branches.update_record(
                    business_id, 'category', category_id,
                    name=request.form.get('name'),
                    actor_user_id=user['id'])

            return mutate(
                business_id, rename_expense_category,
                'Nama kategori diperbarui.',
                destination)

        if action == 'delete_category':
            category_id = record_id(request.form.get('category_id'))

            def delete_expense_category():
                categories = finance.list_categories(
                    business_id, 'EXPENSE', include_inactive=True,
                    actor_user_id=user['id'])
                if not any(category['id'] == category_id for category in categories):
                    raise finance.FinanceError('category_unavailable')
                branches.update_record(
                    business_id, 'category', category_id, deactivate=True,
                    actor_user_id=user['id'])

            return mutate(
                business_id, delete_expense_category,
                'Kategori dihapus dari daftar aktif. Riwayat transaksi dan laporan lama tetap tersimpan.',
                destination)

        if action == 'delete':
            return mutate(
                business_id,
                lambda: finance.delete_monthly_budget(
                    business_id, record_id(request.form.get('budget_id')),
                    actor_user_id=user['id']),
                'Anggaran dihapus.',
                destination)

        if action != 'save':
            abort(400)
        currency = request.form.get('currency') or display_currency
        return mutate(
            business_id,
            lambda: finance.set_monthly_budget(
                business_id, month, record_id(request.form.get('category_id')),
                currency_amount(request.form.get('amount'), currency),
                currency=currency, actor_user_id=user['id']),
            'Anggaran disimpan.',
            destination)

    fx = finance_fx.snapshot(display_options)
    categories = finance.list_categories(
        business_id, 'EXPENSE', actor_user_id=user['id'])
    all_expense_categories = finance.list_categories(
        business_id, 'EXPENSE', include_children=True, actor_user_id=user['id'])
    children_by_parent = {}
    for item in all_expense_categories:
        if item.get('parent_category_id'):
            children_by_parent.setdefault(item['parent_category_id'], []).append(item)
    if month > today_value.strftime('%Y-%m'):
        actual_rows = []
    else:
        actual_rows = finance.get_expense_category_totals(
            business_id, start, min(end, today_value.isoformat()),
            actor_user_id=user['id'])
    by_category = {}
    for row in actual_rows:
        by_category.setdefault(row['category_id'], []).append(row)
    budget_map = {row['category_id']: row for row in existing}

    rows = []
    total_budget_rows = []
    total_spent_rows = []
    for category in categories:
        budget_row = budget_map.get(category['id'])
        child_categories = children_by_parent.get(category['id'], [])
        category_ids = [category['id']] + [child['id'] for child in child_categories]
        spend_rows = [
            row for category_id in category_ids
            for row in by_category.get(category_id, [])
        ]
        child_summaries = []
        for child in child_categories:
            child_spend_rows = by_category.get(child['id'], [])
            child_spent_minor = finance_fx.convert_total(
                [{'currency':row['currency'],'balance_minor':int(row['amount_minor'])}
                 for row in child_spend_rows], display_currency, fx) if child_spend_rows else 0
            child_summaries.append(dict(
                category=child,
                spent_display=('Kurs belum lengkap' if child_spent_minor is None
                               else finance_fx.format_money(child_spent_minor, display_currency)),
                transaction_count=sum(int(row.get('transaction_count') or 0) for row in child_spend_rows),
            ))
        spent_minor = finance_fx.convert_total(
            [{'currency':row['currency'],'balance_minor':int(row['amount_minor'])}
             for row in spend_rows], display_currency, fx) if spend_rows else 0
        if budget_row:
            budget_display_minor = finance_fx.convert_total(
                [{'currency':budget_row['currency'],
                  'balance_minor':int(budget_row['amount_minor'])}],
                display_currency, fx)
            input_amount = f"{finance_fx.major(
                int(budget_row['amount_minor']), budget_row['currency']):.2f}"
            input_currency = budget_row['currency']
            total_budget_rows.append(
                {'currency':budget_row['currency'],
                 'balance_minor':int(budget_row['amount_minor'])})
        else:
            budget_display_minor = 0
            input_amount = ''
            input_currency = display_currency
        total_spent_rows.extend(
            {'currency':row['currency'],'balance_minor':int(row['amount_minor'])}
            for row in spend_rows)
        remaining = (None if budget_display_minor is None or spent_minor is None
                     else budget_display_minor - spent_minor)
        percent_used = (0 if not budget_display_minor or spent_minor is None else
                        min(999, round(spent_minor * 100 / budget_display_minor)))
        rows.append(dict(
            category=category, children=child_summaries, budget=budget_row, input_amount=input_amount,
            input_currency=input_currency,
            budget_value_minor=budget_display_minor,
            spent_value_minor=spent_minor,
            remaining_value_minor=remaining,
            budget_display=('Kurs belum lengkap' if budget_display_minor is None
                            else finance_fx.format_money(budget_display_minor, display_currency)),
            spent_display=('Kurs belum lengkap' if spent_minor is None
                           else finance_fx.format_money(spent_minor, display_currency)),
            remaining_display=('Kurs belum lengkap' if remaining is None
                               else finance_fx.format_money(remaining, display_currency)),
            percent_used=percent_used))

    total_budget_minor = finance_fx.convert_total(
        total_budget_rows, display_currency, fx) if total_budget_rows else 0
    total_spent_minor = finance_fx.convert_total(
        total_spent_rows, display_currency, fx) if total_spent_rows else 0
    remaining_minor = (None if total_budget_minor is None or total_spent_minor is None
                       else total_budget_minor - total_spent_minor)
    month_names = ('Januari','Februari','Maret','April','Mei','Juni',
                   'Juli','Agustus','September','Oktober','November','Desember')
    month_label = month_names[int(month[5:7])-1] + ' ' + month[:4]
    month_index = int(month[:4]) * 12 + int(month[5:7]) - 1
    month_at = lambda index: f'{index // 12:04d}-{index % 12 + 1:02d}'
    previous_month = month_at(month_index - 1)
    next_month = month_at(month_index + 1)
    for row in rows:
        row['over_budget'] = (
            row.get('budget_value_minor') is not None and
            row.get('spent_value_minor') is not None and
            row['budget_value_minor'] > 0 and
            row['spent_value_minor'] > row['budget_value_minor']
        )
        row['has_activity'] = bool(
            (row.get('budget_value_minor') or 0) or (row.get('spent_value_minor') or 0)
        )
    return render_template(
        'finance_budget.html', user=user, business=business, month=month,
        month_label=month_label, previous_month=previous_month, next_month=next_month,
        rows=rows, display_currency=display_currency,
        display_options=display_options, supported_currencies=finance.SUPPORTED_CURRENCIES,
        fx_status_label=('Kurs belum tersedia' if fx.get('source') == 'unavailable'
                         else f"Kurs terbaru {fx.get('source')} · {fx.get('date') or 'tanggal tidak tersedia'}"
                              + (' · data tertunda' if fx.get('stale') else '')),
        total_budget_display=('Kurs belum lengkap' if total_budget_minor is None
                              else finance_fx.format_money(total_budget_minor, display_currency)),
        total_spent_display=('Kurs belum lengkap' if total_spent_minor is None
                             else finance_fx.format_money(total_spent_minor, display_currency)),
        remaining_display=('Kurs belum lengkap' if remaining_minor is None
                           else finance_fx.format_money(remaining_minor, display_currency)))


def mutate(business_id, action, success, destination=None):
    try:
        action()
    except finance.FinanceError as error:
        if str(error) in ('transaction_unavailable', 'business_unavailable', 'invoice_unavailable',
                          'recurring_unavailable', 'payee_unavailable'):
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
        account_id=record_id(request.form.get('account_id'))
        account=next((a for a in finance.list_accounts(business_id,actor_user_id=user['id']) if a['id']==account_id),None)
        if not account:raise finance.FinanceError('account_unavailable')
        currency=account['currency']
        direction=request.form.get('direction')
        subcategory_value=request.form.get('subcategory_id')
        subcategory_id=record_id(subcategory_value) if subcategory_value else None
        category_id=finance.resolve_category_selection(
            business_id,direction,record_id(request.form.get('category_id')),
            subcategory_id,actor_user_id=user['id'])
        finance.create_transaction(business_id,direction,currency_amount(request.form.get('amount'),currency),
            account_id,category_id,request.form.get('occurred_on'),currency=currency,
            description=transaction_note(business_id,request.form),counterparty_name=request.form.get('counterparty_name'),
            customer_id=record_id(request.form['customer_id']) if request.form.get('customer_id') else None,
            project_id=record_id(request.form['project_id']) if request.form.get('project_id') else None,actor_user_id=user['id'])
    destination = None
    return_direction = (request.form.get('return_direction') or '').strip()
    return_month = (request.form.get('return_month') or '').strip()
    if return_direction in finance.DIRECTIONS and return_month <= finance.business_today(business_id).strftime('%Y-%m'):
        try:
            period(return_month)
        except (ValueError, finance.FinanceError):
            pass
        else:
            destination = url_for('finance.dashboard', business_id=business_id,
                                  branch_id=g.finance_branch_id or 'all', period_mode='month',
                                  month=return_month, view='transactions', direction=return_direction)
    return mutate(business_id,action,'Transaksi dicatat.',destination)


@finance_bp.route('/business/<int:business_id>/finance/transactions/<int:transaction_id>/void', methods=['POST'])
@finance_access
def void_transaction(business_id, user, business, transaction_id):
    return mutate(business_id, lambda: finance.void_transaction(business_id, transaction_id, actor_user_id=user['id']),
                  'Transaksi dihapus dari perhitungan. Riwayat audit tetap tersimpan.')


@finance_bp.route('/business/<int:business_id>/finance/reset', methods=['POST'])
@finance_access
def reset_finance(business_id, user, business):
    personal = getattr(g,'finance_workspace_type','BUSINESS') == 'PERSONAL'
    if request.form.get('confirmation') != 'RESET':
        flash(
            'Ketik RESET untuk mengonfirmasi reset Finance Pribadi.' if personal
            else 'Ketik RESET untuk mengonfirmasi reset Finance cabang ini.',
            'error')
        return redirect(
            url_for('finance.dashboard', business_id=business_id, branch_id=g.finance_branch_id),
            code=303)
    branch_name = g.finance_branch['name']
    success = (
        'Finance Pribadi direset ke Rp0. Struktur tetap tersedia dan riwayat audit tetap tersimpan.'
        if personal else
        f'Finance cabang {branch_name} direset ke Rp0. Struktur tetap tersedia dan riwayat audit tetap tersimpan.'
    )
    return mutate(
        business_id,
        lambda: finance.reset_branch_finance(business_id, actor_user_id=user['id']),
        success,
        url_for('finance.dashboard', business_id=business_id, branch_id=g.finance_branch_id))


@finance_bp.route('/business/<int:business_id>/finance/accounts', methods=['POST'])
@finance_access
def create_account(business_id,user,business):
    currency=request.form.get('currency','IDR')
    destination = (url_for('finance.dashboard',business_id=business_id,
                           branch_id=g.finance_branch_id or 'all',view='accounts')
                   if request.form.get('return_view') == 'accounts' else None)
    account_type_label = request.form.get('account_type_name')
    return mutate(business_id,lambda:finance.create_account(
        business_id,request.form.get('name'),request.form.get('account_type') or 'CASH',
        currency=currency,
        opening_balance_minor=currency_amount(request.form.get('opening_balance','0'),currency,signed=True),
        account_type_label=account_type_label if account_type_label else None,
        actor_user_id=user['id']),'Akun siap digunakan.',destination)


@finance_bp.route('/business/<int:business_id>/finance/account-types', methods=['POST'])
@finance_access
def manage_account_types(business_id,user,business):
    action=(request.form.get('action') or 'create').strip()
    name=request.form.get('name')
    try:
        if action == 'create':
            finance.create_account_type_option(business_id,name,actor_user_id=user['id'])
        elif action == 'delete':
            finance.delete_account_type_option(business_id,name,actor_user_id=user['id'])
        else:
            abort(400)
    except finance.FinanceError as error:
        message=ERRORS.get(str(error),'Tipe tempat uang belum valid. Periksa nama dan coba lagi.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(error=message),400
        flash(message,'error')
    else:
        message='Tipe tempat uang ditambahkan.' if action=='create' else 'Tipe tempat uang dihapus dari pilihan baru. Akun lama tetap aman.'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(options=[
                {'name': row['name'], 'is_default': bool(row.get('is_default'))}
                for row in finance.list_account_type_options(business_id,actor_user_id=user['id'])
            ],message=message)
        flash(message,'success')
    return redirect(url_for('finance.dashboard',business_id=business_id,
                            branch_id=g.finance_branch_id or 'all',view='accounts'),code=303)


@finance_bp.route('/business/<int:business_id>/finance/accounts/<int:account_id>/balance', methods=['POST'])
@finance_access
def update_account_balance(business_id,user,business,account_id):
    account=finance.get_account(
        business_id,account_id,actor_user_id=user['id'],active=True)
    action=(request.form.get('action') or '').strip()
    if action not in ('opening','current'):
        abort(400)
    amount=currency_amount(
        request.form.get('amount'),account['currency'],signed=True)
    destination=url_for(
        'finance.dashboard',business_id=business_id,
        branch_id=g.finance_branch_id or 'all',view='accounts',
        account_id=account_id,
        display_currency=request.form.get('display_currency','IDR'))
    if action=='opening':
        return mutate(
            business_id,
            lambda: finance.update_account_opening_balance(
                business_id,account_id,amount,actor_user_id=user['id']),
            'Saldo awal diperbarui. Saldo akun dihitung ulang otomatis.',
            destination)
    return mutate(
        business_id,
        lambda: finance.set_account_current_balance(
            business_id,account_id,amount,actor_user_id=user['id']),
        'Saldo sekarang disesuaikan. Transaksi tetap sama; penyesuaian diterapkan ke saldo awal.',
        destination)


@finance_bp.route('/business/<int:business_id>/finance/exchanges',methods=['POST'])
@finance_access
def create_exchange(business_id,user,business):
    from_id=record_id(request.form.get('from_account_id'));to_id=record_id(request.form.get('to_account_id'))
    source=finance.get_account(business_id,from_id,actor_user_id=user['id'],active=True);target=finance.get_account(business_id,to_id,actor_user_id=user['id'],active=True)
    snap=finance_fx.snapshot((source['currency'],target['currency']));reference=finance_fx.reference_pair(source['currency'],target['currency'],snap)
    return mutate(business_id,lambda:finance.record_currency_exchange(business_id,from_id,to_id,
        currency_amount(request.form.get('from_amount'),source['currency']),currency_amount(request.form.get('to_amount'),target['currency']),
        request.form.get('occurred_on'),note=request.form.get('note'),reference_rate=reference,rate_source=snap.get('source'),rate_as_of=snap.get('date'),actor_user_id=user['id']),
        'Penukaran mata uang dicatat.')

@finance_bp.route('/business/<int:business_id>/finance/exchanges/<int:exchange_id>/edit',methods=['POST'])
@finance_access
def edit_exchange(business_id,user,business,exchange_id):
    exchange=finance.get_currency_exchange(
        business_id,exchange_id,actor_user_id=user['id'])
    from_amount=currency_amount(
        request.form.get('from_amount'),exchange['from_currency'])
    to_amount=currency_amount(
        request.form.get('to_amount'),exchange['to_currency'])
    return_account_id=request.form.get('return_account_id')
    destination=url_for(
        'finance.dashboard',business_id=business_id,
        branch_id=g.finance_branch_id or 'all',view='accounts',
        account_id=record_id(return_account_id) if return_account_id else exchange['from_account_id'],
        display_currency=request.form.get('display_currency','IDR'))
    return mutate(
        business_id,
        lambda: finance.update_currency_exchange(
            business_id,exchange_id,from_amount,to_amount,actor_user_id=user['id']),
        'Nominal transfer diperbarui. Saldo kedua akun dihitung ulang otomatis.',
        destination)


@finance_bp.route('/business/<int:business_id>/finance/exchanges/<int:exchange_id>/void',methods=['POST'])
@finance_access
def void_exchange(business_id,user,business,exchange_id):
    return mutate(business_id,lambda:finance.void_currency_exchange(business_id,exchange_id,user['id']),'Penukaran dikeluarkan dari saldo. Riwayat audit tetap tersimpan.')


@finance_bp.route('/business/<int:business_id>/finance/categories', methods=['POST'])
@finance_access
def create_category(business_id, user, business):
    direction = request.form.get('direction')
    action = (request.form.get('action') or 'create').strip()
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def active_options():
        return [
            {
                'id': row['id'],
                'name': row['name'],
                'direction': row['direction'],
                'parent_category_id': row.get('parent_category_id'),
                'parent_name': row.get('parent_name'),
            }
            for row in finance.list_categories(
                business_id, direction, include_children=True,
                actor_user_id=user['id'])
        ]

    try:
        if action == 'create':
            parent_value = request.form.get('parent_category_id')
            parent_category_id = record_id(parent_value) if parent_value else None
            category_id = finance.create_category(
                business_id, direction, request.form.get('name'),
                parent_category_id=parent_category_id,
                actor_user_id=user['id'])
            category = next((
                row for row in finance.list_categories(
                    business_id, direction, include_children=True,
                    actor_user_id=user['id'])
                if row['id'] == category_id
            ), None)
            if category is None:
                raise finance.FinanceError('category_unavailable')
        elif action == 'edit':
            category_id = record_id(request.form.get('category_id'))
            finance.update_category_workspace_setting(
                business_id, category_id, name=request.form.get('name'),
                actor_user_id=user['id'])
            category = next((
                row for row in finance.list_categories(
                    business_id, direction, include_children=True,
                    actor_user_id=user['id'])
                if row['id'] == category_id
            ), None)
            if category is None:
                raise finance.FinanceError('category_unavailable')
        elif action == 'delete':
            category_id = record_id(request.form.get('category_id'))
            category = next((
                row for row in finance.list_categories(
                    business_id, direction, include_inactive=True,
                    include_children=True, actor_user_id=user['id'])
                if row['id'] == category_id
            ), None)
            if category is None:
                raise finance.FinanceError('category_unavailable')
            finance.update_category_workspace_setting(
                business_id, category_id, deactivate=True,
                actor_user_id=user['id'])
        else:
            abort(400)
    except finance.FinanceError as error:
        message = ERRORS.get(
            str(error), 'Kategori belum valid. Periksa pilihan dan coba lagi.')
        if ajax:
            return jsonify(error=message), 400
        flash(message, 'error')
        return redirect(url_for(
            'finance.dashboard', business_id=business_id,
            branch_id=g.finance_branch_id or 'all'), code=303)

    if ajax:
        payload = {'options': active_options()}
        if action in ('create', 'edit'):
            payload['category'] = {
                'id': category['id'],
                'name': category['name'],
                'direction': category['direction'],
                'parent_category_id': category.get('parent_category_id'),
                'parent_name': category.get('parent_name'),
            }
            payload['message'] = (
                'Kategori ditambahkan dan langsung dipilih.'
                if action == 'create' else
                'Nama kategori diperbarui.'
            )
            return jsonify(payload), 201 if action == 'create' else 200
        payload['message'] = 'Kategori dihapus dari daftar aktif. Riwayat lama tetap aman.'
        return jsonify(payload)

    return mutate(
        business_id,
        lambda: None,
        'Kategori siap digunakan.' if action == 'create' else
        ('Perubahan kategori disimpan.' if action == 'edit'
         else 'Kategori dihapus dari daftar aktif.'))


INVOICE_LABELS = {'DRAFT':'Draft','ISSUED':'Belum dibayar','PARTIALLY_PAID':'Dibayar sebagian','PAID':'Lunas','VOID':'Dibatalkan'}


@finance_bp.route('/business/<int:business_id>/finance/receivables')
@finance_access
def receivables(business_id, user, business):
    actor = {'actor_user_id': user['id']}
    section = request.args.get('section', 'summary')
    if section not in ('summary', 'customers', 'add_customer', 'invoices'):
        section = 'summary'

    active_customers = finance.list_customers(business_id, **actor)
    all_customers = finance.list_customers(business_id, include_inactive=True, **actor)
    customer_map = {row['id']: row for row in all_customers}

    # VOID is accounting cancellation. Archive is UI-only and MUST NOT alter
    # receivables, payments, income, balances, reports or historical statements.
    all_invoices = [row for row in finance.list_finance_invoices(business_id, **actor) if row['status'] != 'VOID']
    archived_ids = finance.archived_invoice_ids(business_id, **actor)
    working_invoices = [row for row in all_invoices if row['id'] not in archived_ids]
    recent_invoices = working_invoices[:3]

    q = (request.args.get('q') or '').strip()
    if len(q) > 120: q = q[:120]
    status_filter = (request.args.get('status') or 'all').upper()
    if status_filter not in ('ALL','DRAFT','ISSUED','PARTIALLY_PAID','PAID'):status_filter='ALL'
    archived_view = request.args.get('archived') == '1'

    try:page=max(1,int(request.args.get('page','1')))
    except (TypeError,ValueError):page=1
    page_size=10

    customers=active_customers
    customer_pages=1
    customer_total=len(active_customers)
    if section=='customers':
        if q:
            needle=q.casefold()
            customers=[row for row in active_customers if needle in (row.get('name') or '').casefold()
                or needle in (row.get('phone') or '').casefold() or needle in (row.get('email') or '').casefold()]
        customer_total=len(customers);customer_pages=max(1,(customer_total+page_size-1)//page_size);page=min(page,customer_pages)
        customers=customers[(page-1)*page_size:page*page_size]

    invoice_source=[row for row in all_invoices if row['id'] in archived_ids] if archived_view else working_invoices
    if status_filter!='ALL':invoice_source=[row for row in invoice_source if row['status']==status_filter]
    if q:
        needle=q.casefold()
        invoice_source=[row for row in invoice_source if needle in row['invoice_number'].casefold()
            or needle in (customer_map.get(row['customer_id'],{}).get('name') or '').casefold()]
    invoice_total=len(invoice_source);invoice_pages=max(1,(invoice_total+page_size-1)//page_size)
    invoice_page=min(page,invoice_pages) if section=='invoices' else 1
    invoices=invoice_source[(invoice_page-1)*page_size:invoice_page*page_size] if section=='invoices' else []

    visible={row['id']:row for row in recent_invoices}
    visible.update({row['id']:row for row in invoices})
    totals={ident:finance.get_invoice_totals(business_id,ident,**actor) for ident in visible}

    return render_template('finance_receivables.html', user=user, business=business,
        customers=customers, customer_count=len(active_customers), customer_total=customer_total,
        customer_pages=customer_pages, customer_map=customer_map,
        invoices=invoices, recent_invoices=recent_invoices, totals=totals, section=section,
        invoice_count=len(working_invoices), paid_invoice_count=sum(row['status']=='PAID' for row in all_invoices),
        archived_invoice_count=len(archived_ids), invoice_total=invoice_total, invoice_page=invoice_page,
        invoice_pages=invoice_pages, page=page, q=q, status_filter=status_filter,
        archived_view=archived_view,
        summary=finance.get_receivables_summary(business_id, **actor), labels=INVOICE_LABELS)


@finance_bp.route('/business/<int:business_id>/finance/customers', methods=['POST'])
@finance_access
def create_customer(business_id, user, business):
    return mutate(business_id, lambda: finance.create_customer(business_id,request.form.get('name'),
        phone=request.form.get('phone'), email=request.form.get('email'), notes=request.form.get('notes'),
        actor_user_id=user['id']), 'Customer ditambahkan.', url_for('finance.receivables',business_id=business_id))


@finance_bp.route('/business/<int:business_id>/finance/customers/<int:customer_id>/edit', methods=['POST'])
@finance_access
def update_customer(business_id, user, business, customer_id):
    return mutate(business_id, lambda: finance.update_customer(
        business_id,customer_id,request.form.get('name'),
        phone=request.form.get('phone'),email=request.form.get('email'),notes=request.form.get('notes'),
        actor_user_id=user['id']),
        'Customer diperbarui.',
        url_for('finance.receivables',business_id=business_id,section='customers'))


@finance_bp.route('/business/<int:business_id>/finance/customers/<int:customer_id>/delete', methods=['POST'])
@finance_access
def delete_customer(business_id, user, business, customer_id):
    return mutate(business_id, lambda: finance.delete_customer(
        business_id,customer_id,actor_user_id=user['id']),
        'Customer dihapus dari daftar aktif. Riwayat invoice dan pembayaran tetap aman.',
        url_for('finance.receivables',business_id=business_id,section='customers'))


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
            currency=finance._currency(request.form.get('currency','IDR'))
            items = [dict(description=d,quantity=whole_idr(q),unit_price_minor=currency_amount(p,currency))
                     for d,q,p in zip(descriptions,quantities,prices)]
            invoice_id = finance.create_finance_invoice(business_id, record_id(request.form.get('customer_id')),
                request.form.get('issue_date'),request.form.get('due_date'),items,
                notes=request.form.get('notes'),currency=currency,actor_user_id=user['id'])
        except finance.FinanceError as error:
            flash(ERRORS.get(str(error),'Data invoice belum valid. Periksa isian dan coba lagi.'),'error')
            return redirect(url_for('finance.new_invoice',business_id=business_id),code=303)
        return redirect(url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id),code=303)
    return render_template('finance_invoice_form.html',user=user,business=business,
        customers=finance.list_customers(business_id,actor_user_id=user['id']),today=finance.business_today(business_id).isoformat(),
        supported_currencies=finance.SUPPORTED_CURRENCIES)


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
        totals=doc['totals'],archived=invoice_id in finance.archived_invoice_ids(business_id,**actor),
        accounts=finance.list_accounts(business_id,**actor),categories=finance.list_categories(business_id,'INCOME',**actor),
        today=finance.business_today(business_id).isoformat(),payment_key=uuid.uuid4().hex,labels=INVOICE_LABELS)


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


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/notes',methods=['POST'])
@finance_access
def update_invoice_notes(business_id,user,business,invoice_id):
    return mutate(business_id,lambda: finance.update_finance_invoice_notes(
        business_id,invoice_id,request.form.get('notes'),actor_user_id=user['id']),
        'Catatan invoice diperbarui. Nominal, item dan histori pembayaran tidak berubah.',
        url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id))


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/archive',methods=['POST'])
@finance_access
def archive_invoice(business_id,user,business,invoice_id):
    return mutate(business_id,lambda: finance.archive_finance_invoice(
        business_id,invoice_id,actor_user_id=user['id']),
        'Invoice lunas diarsipkan dari daftar kerja. Pemasukan, pembayaran dan laporan tetap utuh.',
        url_for('finance.receivables',business_id=business_id,section='invoices'))


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/restore',methods=['POST'])
@finance_access
def restore_invoice(business_id,user,business,invoice_id):
    return mutate(business_id,lambda: finance.restore_finance_invoice(
        business_id,invoice_id,actor_user_id=user['id']),
        'Invoice dikembalikan ke daftar kerja. Tidak ada angka Finance yang berubah.',
        url_for('finance.receivables',business_id=business_id,section='invoices',archived=1))


@finance_bp.route('/business/<int:business_id>/finance/invoices/<int:invoice_id>/payments',methods=['POST'])
@finance_access
def record_payment(business_id,user,business,invoice_id):
    invoice=finance.get_finance_invoice(business_id,invoice_id,user['id'])
    if not invoice:abort(404)
    return mutate(business_id,lambda: finance.record_invoice_payment(business_id,invoice_id,
        currency_amount(request.form.get('amount'),invoice['currency']),request.form.get('paid_on'),record_id(request.form.get('account_id')),
        record_id(request.form.get('category_id')),note=request.form.get('note'),actor_user_id=user['id'],
        idempotency_key=request.form.get('payment_key')), 'Pembayaran dicatat.',
        url_for('finance.invoice_detail',business_id=business_id,invoice_id=invoice_id))


def _bill_month_occurrences(business_id, rules, start, end, today_iso, actor_user_id):
    """Read-only HomeBudget-style month projection with paid posting history."""
    rule_map = {row['id']: row for row in rules}
    occurrences = []
    seen = set()

    for row in finance.get_upcoming_recurring_commitments(
            business_id, start, end, actor_user_id=actor_user_id):
        rule = rule_map.get(row.get('recurring_id'))
        if not rule:
            continue
        scheduled = row['scheduled_on']
        if scheduled < today_iso:
            status, status_label = 'overdue', 'Terlambat'
        elif scheduled == today_iso:
            status, status_label = 'today', 'Jatuh tempo hari ini'
        else:
            status, status_label = 'upcoming', 'Akan datang'
        occurrences.append(dict(
            row,
            rule_id=rule['id'],
            status=status,
            status_label=status_label,
            can_mark_paid=bool(rule['is_active'] and scheduled == rule['next_due_on'] and scheduled <= today_iso),
            source='schedule'))
        seen.add((rule['id'], scheduled))

    for rule in rules:
        for posting in finance.list_recurring_postings(
                business_id, rule['id'], actor_user_id=actor_user_id):
            scheduled = posting['scheduled_on']
            key = (rule['id'], scheduled)
            if scheduled < start or scheduled > end or key in seen:
                continue
            transaction = None
            if posting['ledger_transaction_id']:
                transaction = finance.get_transaction(
                    business_id, posting['ledger_transaction_id'],
                    actor_user_id=actor_user_id)
            if transaction and transaction['status'] == 'POSTED':
                status, status_label = 'paid', 'Lunas'
            elif transaction and transaction['status'] == 'VOID':
                status, status_label = 'void', 'Dibatalkan'
            elif scheduled < today_iso:
                status, status_label = 'overdue', 'Terlambat'
            elif scheduled == today_iso:
                status, status_label = 'today', 'Jatuh tempo hari ini'
            else:
                status, status_label = 'upcoming', 'Akan datang'
            occurrences.append(dict(
                recurring_id=rule['id'],
                rule_id=rule['id'],
                branch_name=rule['branch_name'],
                name=rule['name'],
                currency=rule['currency'],
                scheduled_on=scheduled,
                amount_minor=rule['amount_minor'],
                project_name=None,
                account_name=None,
                category_name=None,
                counterparty_name=rule['counterparty_name'],
                description=rule['description'],
                cadence=rule['cadence'],
                end_on=rule['end_on'],
                status=status,
                status_label=status_label,
                can_mark_paid=False,
                source='posting'))
            seen.add(key)

    return sorted(occurrences, key=lambda row: (row['scheduled_on'], row['rule_id'], row['name']))


@finance_bp.route('/business/<int:business_id>/finance/operations')
@finance_access
def operations(business_id,user,business):
    personal = getattr(g,'finance_workspace_type','BUSINESS') == 'PERSONAL'
    raw_section = request.args.get('section', '')
    section = 'projects' if raw_section == 'projects' and not personal else 'bills'
    view = request.args.get('view') or ('recurring' if raw_section == 'recurring' else 'calendar')
    if view not in ('calendar', 'list', 'recurring'):
        view = 'calendar'

    local_today = finance.business_today(business_id)
    current_month = local_today.strftime('%Y-%m')
    month = request.args.get('month', current_month)
    try:
        start, end = period(month)
    except (ValueError, finance.FinanceError):
        flash('Bulan tagihan belum valid.', 'error')
        return redirect(url_for('finance.operations', business_id=business_id), code=303)

    actor = {'actor_user_id': user['id']}
    rules = finance.list_recurring_expenses(business_id, include_inactive=True, **actor)
    for rule in rules:
        rule['input_amount'] = f"{finance_fx.major(int(rule['amount_minor']), rule['currency']):.2f}"
        rule['input_cadence'] = (
            'ONCE' if rule['cadence'] == 'MONTHLY'
            and rule['end_on'] == rule['next_due_on'] else rule['cadence'])
    accounts = finance.list_accounts(business_id, **actor)
    categories = finance.list_categories(business_id, 'EXPENSE', include_children=True, **actor)
    projects = [] if personal else finance.list_finance_projects(business_id, **actor)

    occurrences = _bill_month_occurrences(
        business_id, rules, start, end, local_today.isoformat(), user['id'])

    display_options = ['IDR']
    display_options += [row['currency'] for row in accounts if row['currency'] != 'IDR']
    display_options += [row['currency'] for row in rules if row['currency'] != 'IDR']
    display_options = list(dict.fromkeys(display_options))
    display_currency = request.args.get('display_currency') or 'IDR'
    if display_currency not in finance.SUPPORTED_CURRENCIES:
        display_currency = 'IDR'
    if display_currency not in display_options:
        display_options.append(display_currency)
    fx = finance_fx.snapshot(display_options)

    for row in occurrences:
        converted = finance_fx.convert_total(
            [{'currency': row['currency'], 'balance_minor': int(row['amount_minor'])}],
            display_currency, fx)
        row['display_amount'] = (
            finance_fx.format_money(converted, display_currency)
            if converted is not None
            else finance_fx.format_money(int(row['amount_minor']), row['currency']))
        row['native_amount'] = finance_fx.format_money(int(row['amount_minor']), row['currency'])
        row['show_native'] = row['currency'] != display_currency and converted is not None

    total_rows = [
        {'currency': row['currency'], 'balance_minor': int(row['amount_minor'])}
        for row in occurrences if row['status'] != 'void']
    unpaid_rows = [
        {'currency': row['currency'], 'balance_minor': int(row['amount_minor'])}
        for row in occurrences if row['status'] not in ('paid', 'void')]
    total_minor = finance_fx.convert_total(total_rows, display_currency, fx) if total_rows else 0
    unpaid_minor = finance_fx.convert_total(unpaid_rows, display_currency, fx) if unpaid_rows else 0

    month_names = ('Januari','Februari','Maret','April','Mei','Juni',
                   'Juli','Agustus','September','Oktober','November','Desember')
    year, month_number = map(int, month.split('-'))
    month_label = month_names[month_number - 1] + ' ' + str(year)
    month_index = year * 12 + month_number - 1
    month_at = lambda index: f'{index // 12:04d}-{index % 12 + 1:02d}'
    previous_month = month_at(month_index - 1)
    next_month = month_at(month_index + 1)

    selected = request.args.get('day')
    try:
        selected_date = date.fromisoformat(selected) if selected else None
    except ValueError:
        selected_date = None
    if not selected_date or selected_date.strftime('%Y-%m') != month:
        if month == current_month:
            selected_date = local_today
        elif occurrences:
            selected_date = date.fromisoformat(occurrences[0]['scheduled_on'])
        else:
            selected_date = date(year, month_number, 1)
    selected_day = selected_date.isoformat()
    selected_day_label = f'{selected_date.day} {month_names[selected_date.month - 1]} {selected_date.year}'
    selected_occurrences = [row for row in occurrences if row['scheduled_on'] == selected_day]

    by_day = {}
    for row in occurrences:
        by_day.setdefault(row['scheduled_on'], []).append(row)
    calendar_weeks = []
    for week in calendar.Calendar(firstweekday=6).monthdatescalendar(year, month_number):
        cells = []
        for calendar_date in week:
            iso = calendar_date.isoformat()
            day_rows = by_day.get(iso, [])
            states = {row['status'] for row in day_rows}
            state = ('overdue' if 'overdue' in states else
                     'today' if 'today' in states else
                     'upcoming' if 'upcoming' in states else
                     'paid' if 'paid' in states else
                     'void' if 'void' in states else '')
            cells.append(dict(
                date=iso, day=calendar_date.day,
                outside=calendar_date.month != month_number,
                selected=iso == selected_day,
                count=len(day_rows), state=state))
        calendar_weeks.append(cells)

    contributions = finance.get_project_cash_contribution(
        business_id, start, end, **actor) if section == 'projects' else []

    return render_template(
        'finance_operations.html',
        user=user, business=business, rules=rules, projects=projects, section=section, view=view,
        occurrences=occurrences, selected_occurrences=selected_occurrences,
        calendar_weeks=calendar_weeks, weekday_labels=('Min','Sen','Sel','Rab','Kam','Jum','Sab'),
        selected_day=selected_day, selected_day_label=selected_day_label,
        accounts=accounts, categories=categories,
        contributions=contributions, month=month, month_label=month_label,
        previous_month=previous_month, next_month=next_month,
        current_month=current_month, today=local_today.isoformat(),
        display_currency=display_currency, display_options=display_options,
        total_bills_display=('Kurs belum lengkap' if total_minor is None
                             else finance_fx.format_money(total_minor, display_currency)),
        unpaid_bills_display=('Kurs belum lengkap' if unpaid_minor is None
                              else finance_fx.format_money(unpaid_minor, display_currency)),
        unpaid_count=len(unpaid_rows), rules_count=sum(1 for row in rules if row['is_active']),
        max_occurrences=finance.MAX_RECURRING_OCCURRENCES)


@finance_bp.route('/business/<int:business_id>/finance/recurring',methods=['POST'])
@finance_access
def create_recurring(business_id,user,business):
    month = request.form.get('month') or finance.business_today(business_id).strftime('%Y-%m')
    destination = url_for(
        'finance.operations', business_id=business_id, branch_id=g.finance_branch_id,
        month=month, view='calendar')
    def action():
        account_id = record_id(request.form.get('account_id'))
        account = finance.get_account(
            business_id, account_id, actor_user_id=user['id'], active=True)
        if not account:
            raise finance.FinanceError('account_unavailable')
        requested_cadence = request.form.get('cadence') or 'MONTHLY'
        next_due_on = request.form.get('next_due_on')
        if requested_cadence == 'ONCE':
            cadence = 'MONTHLY'
            end_on = next_due_on
        elif requested_cadence in ('WEEKLY', 'MONTHLY'):
            cadence = requested_cadence
            end_on = request.form.get('end_on') or None
        else:
            raise finance.FinanceError('invalid_enum')
        return finance.create_recurring_expense(
            business_id, request.form.get('name'),
            currency_amount(request.form.get('amount'), account['currency']),
            account_id, record_id(request.form.get('category_id')),
            cadence, next_due_on, end_on=end_on,
            project_id=record_id(request.form['project_id']) if request.form.get('project_id') else None,
            counterparty_name=request.form.get('counterparty_name'),
            description=request.form.get('description'),
            actor_user_id=user['id'])
    return mutate(business_id, action, 'Tagihan disimpan.', destination)


@finance_bp.route('/business/<int:business_id>/finance/recurring/<int:recurring_id>/edit',methods=['POST'])
@finance_access
def update_recurring(business_id,user,business,recurring_id):
    month = request.form.get('month') or finance.business_today(business_id).strftime('%Y-%m')
    display_currency = request.form.get('display_currency') or 'IDR'
    if display_currency not in finance.SUPPORTED_CURRENCIES:
        display_currency = 'IDR'
    destination = url_for(
        'finance.operations', business_id=business_id, branch_id=g.finance_branch_id,
        month=month, view='recurring', display_currency=display_currency)

    def action():
        account_id = record_id(request.form.get('account_id'))
        account = finance.get_account(
            business_id, account_id, actor_user_id=user['id'], active=True)
        if not account:
            raise finance.FinanceError('account_unavailable')
        requested_cadence = request.form.get('cadence') or 'MONTHLY'
        next_due_on = request.form.get('next_due_on')
        if requested_cadence == 'ONCE':
            cadence = 'MONTHLY'
            end_on = next_due_on
        elif requested_cadence in ('WEEKLY', 'MONTHLY'):
            cadence = requested_cadence
            end_on = request.form.get('end_on') or None
        else:
            raise finance.FinanceError('invalid_enum')
        return finance.update_recurring_expense(
            business_id, recurring_id, request.form.get('name'),
            currency_amount(request.form.get('amount'), account['currency']),
            account_id, record_id(request.form.get('category_id')),
            cadence, next_due_on, end_on=end_on,
            project_id=record_id(request.form['project_id']) if request.form.get('project_id') else None,
            counterparty_name=request.form.get('counterparty_name'),
            description=request.form.get('description'),
            actor_user_id=user['id'], expected_currency=account['currency'])

    return mutate(business_id, action, 'Tagihan diperbarui. Riwayat pembayaran lama tidak berubah.', destination)


@finance_bp.route('/business/<int:business_id>/finance/recurring/<int:recurring_id>/deactivate',methods=['POST'])
@finance_access
def deactivate_recurring(business_id,user,business,recurring_id):
    month = request.form.get('month') or finance.business_today(business_id).strftime('%Y-%m')
    return mutate(
        business_id,
        lambda: finance.deactivate_recurring_expense(
            business_id, recurring_id, actor_user_id=user['id']),
        'Jadwal tagihan dihapus dari daftar aktif. Riwayat tetap tersimpan.',
        url_for('finance.operations', business_id=business_id,
                branch_id=g.finance_branch_id, month=month, view='recurring'))


@finance_bp.route('/business/<int:business_id>/finance/recurring/process',methods=['POST'])
@finance_access
def process_recurring(business_id,user,business):
    selected = request.form.getlist('occurrence')
    month = request.form.get('month') or finance.business_today(business_id).strftime('%Y-%m')
    day = request.form.get('day') or None
    view = request.form.get('view') if request.form.get('view') in ('calendar','list') else 'calendar'
    destination = url_for(
        'finance.operations', business_id=business_id, branch_id=g.finance_branch_id,
        month=month, day=day, view=view)
    if not selected:
        flash('Pilih tagihan yang sudah dibayar terlebih dahulu.', 'error')
        return redirect(destination, code=303)
    result = finance.process_due_recurring_expenses(
        business_id, finance.business_today(business_id),
        actor_user_id=user['id'], selected=selected)
    flash(f"{result['posted_count']} tagihan dicatat sebagai pengeluaran.", 'success')
    if result['needs_attention_count']:
        flash('Ada tagihan yang belum dapat dicatat. Periksa akun, kategori, dan proyek. Jadwalnya tetap tersimpan.', 'error')
    if result['limit_reached']:
        flash('Batas pemrosesan tercapai. Masih ada tagihan jatuh tempo; proses kembali untuk melanjutkan.', 'error')
    return redirect(destination, code=303)

def report_error(error):
    if str(error) in ('report_limit','forecast_limit'):
        return 'Data laporan terlalu banyak. Persempit rentang tanggal atau komitmen biaya rutin.'
    return 'Filter laporan belum valid. Gunakan tanggal yang benar, maksimal 366 hari dan 12 bulan.'


@finance_bp.route('/business/<int:business_id>/finance/reports')
@finance_access
def reports(business_id,user,business):
    personal = getattr(g,'finance_workspace_type','BUSINESS') == 'PERSONAL'
    section = request.args.get('section', 'summary')
    if section not in ('filter', 'summary', 'trend', 'accounts', 'receivables', 'analysis', 'categories', 'customers', 'projects', 'commitments'):
        section = 'filter'
    if personal and section in ('receivables','analysis','customers','projects'):
        section = 'summary'
    try:
        filters=finance_reports.parse_filters(request.args,today=finance.business_today(business_id))
        actor={'actor_user_id':user['id']}
        allowed = (
            ('category_breakdown','accounts','recurring_commitments')
            if personal else
            tuple(name for name in finance_reports.REPORT_NAMES if name not in ('transactions','invoices'))
        )
        data={name:finance_reports.report_data(name,business_id,filters,user['id']) for name in allowed}
        for name in ('category_breakdown','accounts','customers','projects','receivables_aging','recurring_commitments'):
            data.setdefault(name,[])
        summary=finance.get_cashflow_reports(business_id,filters['start'],filters['end'],**actor)
        trend=finance.get_monthly_cashflow_trends(business_id,filters['start'][:7],filters['end'][:7],
            start_date=filters['start'],end_date=filters['end'],**actor)
    except finance.FinanceError as error:
        return render_template('finance_reports.html',user=user,business=business,error=report_error(error),section=section,today=finance.business_today(business_id).isoformat()),400
    response=Response(render_template('finance_reports.html',user=user,business=business,filters=filters,section=section,
        today=finance.business_today(business_id).isoformat(),data=data,summary=summary,trend=trend,directions=finance_reports.DIRECTIONS,
        account_types=finance_reports.ACCOUNT_TYPES,export_names=finance_reports.REPORT_NAMES))
    response.headers['Cache-Control']='private, no-store'
    return response


@finance_bp.route('/business/<int:business_id>/finance/reports/export/report.pdf')
@finance_access
def report_pdf(business_id,user,business):
    personal = getattr(g,'finance_workspace_type','BUSINESS') == 'PERSONAL'
    try:
        filters=finance_reports.parse_filters(request.args,today=finance.business_today(business_id))
        actor={'actor_user_id':user['id']}
        allowed = (
            ('category_breakdown','accounts','recurring_commitments')
            if personal else
            tuple(name for name in finance_reports.REPORT_NAMES if name not in ('transactions','invoices'))
        )
        data={name:finance_reports.report_data(name,business_id,filters,user['id']) for name in allowed}
        summary=finance.get_cashflow_reports(business_id,filters['start'],filters['end'],**actor)
        trend=finance.get_monthly_cashflow_trends(business_id,filters['start'][:7],filters['end'][:7],
            start_date=filters['start'],end_date=filters['end'],**actor)
        pdf=finance_report_pdf.build(
            business_name=('Pribadi' if personal else business['business_name']),
            branch_name=('Pribadi' if personal else g.finance_branch['name']),
            filters=filters,summary=summary,trend=trend,data=data)
    except finance.FinanceError as error:
        return Response(report_error(error),status=400,mimetype='text/plain',headers={'Cache-Control':'no-store'})
    filename='kilas-finance-'+filters['start']+'_'+filters['end']+'.pdf'
    return Response(pdf,content_type='application/pdf',headers={
        'Content-Disposition':f'attachment; filename="{filename}"',
        'Cache-Control':'private, no-store'})


@finance_bp.route('/business/<int:business_id>/finance/reports/export/<report_name>.csv')
@finance_access
def report_csv(business_id,user,business,report_name):
    if report_name not in finance_reports.REPORT_NAMES:abort(404)
    if (getattr(g,'finance_workspace_type','BUSINESS') == 'PERSONAL'
            and report_name in ('invoices','customers','projects','receivables_aging')):
        abort(404)
    try:
        filters=finance_reports.parse_filters(request.args,today=finance.business_today(business_id))
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
        filters=finance_reports.parse_filters(request.args,today=finance.business_today(business_id))
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
                               month=finance.business_today(business_id).strftime('%Y-%m'), current_month=finance.business_today(business_id).strftime('%Y-%m'),
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
        actions=finance_operator.ACTIONS, today=finance.business_today(business_id).isoformat(),
        accounts=finance.list_accounts(business_id, **actor),
        categories=finance.list_categories(business_id, include_children=True, **actor),
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
                           supported_currencies=finance.SUPPORTED_CURRENCIES,today=finance.business_today(business['id']).isoformat()), status


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
        ai_safety.upload_event(error.code)
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
                   'Periksa konfirmasi, mata uang, nominal, tanggal, akun dan kategori aktif. Belum ada pengeluaran baru dibuat.')
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
        except bank_extract.BankError as error:
            return bank_extract.ERROR_MESSAGES.get(str(error),('Permintaan impor belum valid. Periksa isian.',400))
        except file_utils.UploadRejected as error:
            return str(error),400
        except (ValueError, file_utils.UploadRejected) as error:
            ai_safety.upload_event(error.code if isinstance(error,file_utils.UploadRejected) else str(error))
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
    accounts=finance.list_accounts(business_id,actor_user_id=user['id'])
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
            raw=upload.stream.read(file_utils.FINANCE_IMAGE_INPUT_BYTES+1)
            total+=len(raw)
            if total>25*1024*1024:raise ValueError('aggregate')
            files.append((upload.filename,raw))
        if len(request.form.getlist('document_kind'))>1:raise ValueError('document_kind')
        import_id,fallback=bank.analyze(business_id,account_id,files,user['id'],
                                      document_kind=request.form.get('document_kind','bank'))
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
    categories=finance.list_categories(business_id,include_children=True,actor_user_id=user['id'])
    counts={state:sum(r['reconciliation_status']==state for r in all_rows) for state in ('UNMATCHED','MATCHED','POSTED','IGNORED')}
    account=next((a for a in finance.list_accounts(business_id,True,actor_user_id=user['id']) if a['id']==imp['account_id']),None)
    return render_template('finance_bank_detail.html',user=user,business=business,imp=imp,account=account,
        rows=all_rows[(page-1)*50:page*50],candidates=candidates,candidate_error=candidate_error,categories=categories,
        counts=counts,page=page,pages=max(1,(len(all_rows)+49)//50),today=finance.business_today(business_id).isoformat())


@finance_bp.route('/business/<int:business_id>/finance/bank-imports/<int:import_id>/review',methods=['POST'])
@bank_safe
@finance_access
def bank_review(business_id,user,business,import_id):
    allowed={'csrf_token','row_id','revision','transaction_date','description','direction','amount','reference'}
    if set(request.form)-allowed or any(len(request.form.getlist(k))!=1 for k in request.form):raise ValueError('fields')
    row_id=record_id(request.form['row_id']) if request.form.get('row_id') else None
    bank.edit_row(business_id,import_id,row_id,int(request.form.get('revision','-1')),dict(
        transaction_date=request.form.get('transaction_date'),description=request.form.get('description'),
        direction=request.form.get('direction'),amount_minor=currency_amount(request.form.get('amount'),
            bank.account(business_id,bank.get_import(business_id,import_id,user['id'])['account_id'],user['id'])['currency']),
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
    local_today=finance.business_today(business_id)
    return render_template('finance_assistant.html', user=user, business=business,
        assistant_asset_version=hashlib.sha256((Path(current_app.static_folder)/'finance_assistant.js').read_bytes()).hexdigest()[:16],
        assistant_embedded=True, analyst_enabled=finance_analyst.enabled(business_id),
        operator_enabled=operator_enabled, actions=finance_operator.ACTIONS,
        today=local_today.isoformat(), month=local_today.strftime('%Y-%m'),
        current_month=local_today.strftime('%Y-%m'),
        accounts=[a for a in finance.list_accounts(business_id, **actor) if a['is_active']],
        categories=finance.list_categories(business_id, include_children=True, **actor) if operator_enabled else [],
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
        if result['workflow']=='RECURRING_DRAFT':
            result['suggestions']=assistant_recurring.suggest(text)
        return jsonify(result)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        ai_safety.event('invalid_request')
        return jsonify(error='Teks maksimal 2.000 karakter dan maksimal 10 nama file.'), 400
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(workflow='NEEDS_CLARIFICATION', suggested_action='')


@finance_bp.route('/business/<int:business_id>/finance/assistant/recognize', methods=['POST'])
@ai_safety.endpoint
@finance_access
def assistant_recognize(business_id,user,business):
    if g.finance_branch_id is None:
        return jsonify(kind='branch_choice',message='Dokumen ini untuk cabang mana?',document=True,
                       branches=[dict(id=r['id'],name=r['name']) for r in branches.list_branches(business_id,user['id']) if r['is_active']])
    uploads=request.files.getlist('sources')
    try:
        if (set(request.files)!={'sources'} or not 1<=len(uploads)<=10
                or set(request.form)-{'csrf_token','text','branch_id'}
                or any(len(request.form.getlist(k))!=1 for k in request.form)):
            raise ValueError('invalid_fields')
        files=[];total=0
        for upload in uploads:
            raw=upload.stream.read(file_utils.FINANCE_IMAGE_INPUT_BYTES+1);total+=len(raw)
            if total>25*1024*1024:raise ValueError('aggregate')
            files.append((upload.filename,raw))
        workflow=finance_documents.recognize(business_id,user['id'],files,request.form.get('text',''),detailed=True)
        return jsonify(workflow if isinstance(workflow,dict) else dict(workflow=workflow))
    except HTTPException:raise
    except (ValueError,file_utils.UploadRejected) as error:
        return assistant_error(error)
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(workflow='NEEDS_CLARIFICATION')
    finally:
        for upload in uploads:upload.close()


@finance_bp.route('/business/<int:business_id>/finance/assistant/recurring/<stage>',methods=['POST'])
@ai_safety.endpoint
@finance_access
def assistant_recurring_action(business_id,user,business,stage):
    if not finance_operator.enabled(business_id):abort(404)
    if stage not in ('draft','confirm'):abort(404)
    payload,error=finance_ai_payload(user['id'],business_id,'ai' if stage=='draft' else 'confirm')
    if error is not None:return error
    try:
        if stage=='draft':
            result=assistant_recurring.prepare(business_id,user['id'],payload)
        else:
            if set(payload)!={'token','confirm'} or payload['confirm'] is not True:raise ValueError('confirmation')
            result=assistant_recurring.confirm(business_id,user['id'],payload['token'])
        ai_safety.event('draft_generated' if stage=='draft' else 'confirmation_accepted')
        return jsonify(result)
    except ValueError:
        return jsonify(error='Periksa nominal, jadwal, kas/rekening, dan kategori. Draft harus valid dan belum kedaluwarsa.'),400
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(error='Konfirmasi belum dapat dipastikan. Ulangi draft yang sama atau periksa Biaya Rutin sebelum membuat draft baru.'),503


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
        if getattr(g, 'finance_branch_id', None):
            values.setdefault('branch_id', g.finance_branch_id)


@finance_bp.context_processor
def finance_branch_context():
    if not getattr(g, 'finance_business_id', None):
        return {}
    return dict(finance_branch_business_id=g.finance_business_id, finance_branches=g.finance_branches,
        selected_branch=g.finance_branch, selected_branch_id=g.finance_branch_id,
        all_branches=g.finance_branch_id is None, branch_read_only=g.finance_branch_read_only,
        finance_workspace_type=getattr(g,'finance_workspace_type','BUSINESS'),
        finance_workspace_label=getattr(g,'finance_workspace_label','Bisnis'),
        finance_workspace_personal=getattr(g,'finance_workspace_type','BUSINESS')=='PERSONAL')


def transaction_note(business_id, form):
    chosen_category_id = form.get('subcategory_id') or form.get('category_id')
    category = next((c for c in finance.list_categories(
        business_id, include_inactive=True, include_children=True)
                     if str(c['id']) == chosen_category_id), None)
    note = finance._text(form.get('description'), 4000)
    if category and category['name'] in ('Lainnya', 'Pendapatan Lain', 'Pengeluaran Lain'):
        other = finance._text(form.get('other_description'), 1000, True)
        note = other + ('\n' + note if note else '')
    return finance._text(note, 4000)


@finance_bp.route('/business/<int:business_id>/finance/branches', methods=['POST'])
@finance_access
def create_branch(business_id, user, business):
    if getattr(g,'finance_workspace_type','BUSINESS') != 'BUSINESS':
        abort(403)
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
    if kind == 'branch' and getattr(g,'finance_workspace_type','BUSINESS') != 'BUSINESS':
        abort(403)
    deactivate = request.form.get('action') == 'deactivate'
    destination = url_for('finance.dashboard', business_id=business_id, branch_id='all') if kind == 'branch' and deactivate else None
    if kind == 'account' and request.form.get('return_view') == 'accounts':
        display_currency = request.form.get('display_currency', 'IDR')
        if display_currency not in finance.SUPPORTED_CURRENCIES:
            display_currency = 'IDR'
        destination = url_for(
            'finance.dashboard', business_id=business_id,
            branch_id=g.finance_branch_id or 'all', view='accounts',
            display_currency=display_currency)
    message = 'Dihapus dari daftar aktif. Riwayat lama tetap tersedia.' if deactivate else 'Perubahan disimpan. Riwayat tetap tersedia.'
    action = (
        (lambda: finance.update_category_workspace_setting(
            business_id, record_id, name=request.form.get('name'),
            deactivate=deactivate, actor_user_id=user['id']))
        if kind == 'category' else
        (lambda: branches.update_record(
            business_id, kind, record_id, name=request.form.get('name'),
            deactivate=deactivate, actor_user_id=user['id']))
    )
    return mutate(business_id, action, message, destination)


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
            amount_minor=currency_amount(request.form.get('amount'),transaction['currency']), occurred_on=request.form.get('occurred_on'),
            account_id=record_id(request.form.get('account_id')), category_id=record_id(request.form.get('category_id')),
            description=transaction_note(business_id, request.form), actor_user_id=user['id']),
            'Transaksi diperbarui. Riwayat perubahan tersimpan.')
    categories = finance.list_categories(
        business_id, transaction['direction'], include_children=True, actor_user_id=user['id'])
    is_other = any(c['id'] == transaction['category_id'] and c['name'] in ('Lainnya', 'Pendapatan Lain', 'Pengeluaran Lain') for c in categories)
    description = transaction['description'] or ''
    other_description = ''
    if is_other:
        other_description, _, description = description.partition('\n')
    return render_template('finance_transaction_edit.html', business=business, user=user, transaction=transaction,
        initial_description=description, initial_other_description=other_description,
        accounts=finance.list_accounts(business_id, actor_user_id=user['id']),
        categories=finance.list_categories(
            business_id, transaction['direction'], include_children=True, actor_user_id=user['id']),
        today=finance.business_today(business_id).isoformat())


# Structured Assistant boundary; legacy module pages remain independently usable.
_ASSISTANT_JSON_ENDPOINTS = {'finance.assistant_message','finance.assistant_review','finance.assistant_confirm',
                             'finance.assistant_document','finance.assistant_recognize'}


@finance_bp.after_request
def assistant_json_errors(response):
    if request.endpoint not in _ASSISTANT_JSON_ENDPOINTS or response.is_json:
        return response
    if response.status_code >= 400 or 300 <= response.status_code < 400:
        code=response.status_code
        message={400:'Permintaan belum valid. Periksa isian atau muat ulang halaman.',
                 401:'Silakan masuk lagi untuk melanjutkan.',403:'Akses Finance atau cabang ini belum tersedia.',
                 404:'Data atau akses bisnis tidak tersedia.',413:'Lampiran terlalu besar. Maksimal 20 MiB per foto dan 25 MiB total.',
                 429:'Terlalu banyak percobaan. Tunggu sebentar.'}.get(code,'Permintaan belum dapat diproses. Coba lagi sebentar.')
        if 300 <= code < 400:code=401;message='Silakan masuk dan periksa masa aktif Finance untuk melanjutkan.'
        result=jsonify(error=message);result.status_code=code;result.headers['Cache-Control']='private, no-store'
        return result
    return response


def assistant_error(error):
    if isinstance(error,bank_extract.BankError) and str(error) in bank_extract.ERROR_MESSAGES:
        message,status=bank_extract.ERROR_MESSAGES[str(error)]
        return jsonify(error=message),status
    if isinstance(error,finance_documents.DocumentProviderError):
        message,status=bank_extract.ERROR_MESSAGES.get(str(error),bank_extract.ERROR_MESSAGES['upstream_failure'])
        return jsonify(error=message),status
    if isinstance(error,file_utils.UploadRejected):
        ai_safety.upload_event(error.code)
        return jsonify(error=str(error)),400
    messages={'invalid_draft':'Review sudah kedaluwarsa atau tidak valid. Siapkan ulang review.',
              'account_unavailable':'Pilih rekening aktif yang sesuai dengan cabang dan mata uang.',
              'category_unavailable':'Pilih kategori aktif yang sesuai.',
              'invoice_unavailable':'Invoice tidak tersedia pada bisnis/cabang ini. Pilih invoice yang benar.',
              'invalid_invoice_payment':'Nominal pembayaran melebihi sisa tagihan atau invoice sudah ditutup.',
              'invalid_amount':'Nominal belum jelas. Gunakan satu nominal dan mata uang yang sesuai.',
              'invalid_email':'Periksa alamat email customer.', 'future_date':'Tanggal transaksi tidak boleh di masa depan.',
              'unsupported_file':'Tipe file belum didukung. Gunakan JPG, PNG, WEBP, PDF atau CSV.',
              'invalid_csv':'CSV rusak atau susunan kolom tidak valid.',
              'source_count':'Gunakan satu PDF/CSV atau maksimal 10 foto.',
              'aggregate':'Total lampiran maksimal 25 MiB.'}
    reason=str(error)
    ai_safety.upload_event(reason if reason in messages else 'invalid_fields')
    return jsonify(error=messages.get(reason,'Data belum jelas atau pilihan sudah tidak tersedia. Periksa nominal, tanggal, mata uang, dan pilihan pada review.')),400


@finance_bp.route('/business/<int:business_id>/finance/assistant/message',methods=['POST'])
@ai_safety.endpoint
@finance_access
def assistant_message(business_id,user,business):
    payload,error=finance_ai_payload(user['id'],business_id,'confirm')
    if error is not None:return error
    try:
        if set(payload) not in ({'text'}, {'text','query_context'}, {'text','context','confirmation'}, {'text','context','confirmation','query_context'}):raise ValueError('invalid_fields')
        if 'context' in payload:
            return jsonify(assistant_flow.follow_up(business_id,user['id'],payload['context'],payload['text'],payload['confirmation'],payload.get('query_context','')))
        return jsonify(assistant_flow.text_message(business_id,user['id'],payload['text'],payload.get('query_context','')))
    except ValueError as error:return assistant_error(error)
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(error='Assistant belum dapat memproses permintaan ini dengan aman saat ini. Belum ada data yang diubah. Mohon lakukan melalui menu Finance secara manual, atau coba lagi nanti.'),503


@finance_bp.route('/business/<int:business_id>/finance/assistant/review',methods=['POST'])
@ai_safety.endpoint
@finance_access
def assistant_review(business_id,user,business):
    payload,error=finance_ai_payload(user['id'],business_id,'ai')
    if error is not None:return error
    try:
        if set(payload)!={'context','values'}:raise ValueError('invalid_fields')
        return jsonify(assistant_flow.revise(business_id,user['id'],payload['context'],payload['values']))
    except ValueError as error:return assistant_error(error)
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(error='Review belum dapat dipastikan dengan aman. Belum ada data yang diubah. Mohon lakukan tindakan ini melalui menu Finance secara manual jika perlu segera diproses.'),503


@finance_bp.route('/business/<int:business_id>/finance/assistant/confirm',methods=['POST'])
@ai_safety.endpoint
@finance_access
def assistant_confirm(business_id,user,business):
    payload,error=finance_ai_payload(user['id'],business_id,'confirm')
    if error is not None:return error
    try:
        if set(payload)!={'token','confirm'} or payload['confirm'] is not True:raise ValueError('invalid_fields')
        return jsonify(assistant_flow.confirm(business_id,user['id'],payload['token']))
    except ValueError as error:return assistant_error(error)
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(error='Konfirmasi belum dapat dipastikan. Periksa catatan Finance secara manual sebelum mencoba lagi agar tidak terjadi pencatatan ganda.'),503


@finance_bp.route('/business/<int:business_id>/finance/assistant/document',methods=['POST'])
@ai_safety.endpoint
@finance_access
def assistant_document(business_id,user,business):
    uploads=request.files.getlist('sources')
    try:
        if (set(request.files)!={'sources'} or not 1<=len(uploads)<=10
                or set(request.form)-{'csrf_token','branch_id','text','workflow','account_id','document_context'}
                or any(len(request.form.getlist(k))!=1 for k in request.form)):
            raise ValueError('invalid_fields')
        assistant_flow.authorize(business_id,user['id'])
        files=[];total=0
        for upload in uploads:
            raw=upload.stream.read(file_utils.FINANCE_IMAGE_INPUT_BYTES+1);total+=len(raw)
            if total>25*1024*1024:raise ValueError('aggregate')
            files.append((upload.filename,raw))
        return jsonify(assistant_flow.document(business_id,user['id'],files,request.form.get('text',''),
            request.form.get('workflow',''),request.form.get('account_id',''),request.form.get('document_context','')))
    except HTTPException:raise
    except (ValueError,file_utils.UploadRejected) as error:return assistant_error(error)
    except Exception:
        ai_safety.event('request_failed')
        return jsonify(error='Dokumen belum berhasil diproses. Coba lagi atau gunakan foto/PDF yang lebih jelas. Belum ada pencatatan.'),503
    finally:
        for upload in uploads:upload.close()
