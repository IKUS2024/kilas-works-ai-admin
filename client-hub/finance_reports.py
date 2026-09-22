"""Read-only export/presentation builders. Standard library, no files or DB mutations."""
import csv
from datetime import date, timedelta
import io
import zipfile
import finance_service as finance
import finance_fx

MAX_CSV_BYTES=16*1024*1024
MAX_BUNDLE_BYTES=64*1024*1024
REPORT_NAMES=('transactions','invoices','category_breakdown','accounts','customers','projects','receivables_aging','recurring_commitments')
DIRECTIONS={'INCOME':'Pemasukan','EXPENSE':'Pengeluaran'}
STATUSES={'DRAFT':'Draft','ISSUED':'Belum dibayar','PARTIALLY_PAID':'Dibayar sebagian','PAID':'Lunas','VOID':'Dibatalkan','POSTED':'Tercatat'}
SOURCES={'FINANCE_INVOICE_PAYMENT':'Pembayaran Invoice','FINANCE_RECURRING_EXPENSE':'Biaya Rutin'}
ACCOUNT_TYPES={'CASH':'Kas','BANK':'Bank','EWALLET':'E-Wallet','OTHER':'Lainnya'}


def parse_filters(args, today=None, business_id=None, actor_user_id=None):
    today=today or date.today()
    today_iso=today.isoformat()
    preset=args.get('preset','month')
    allowed=('today','month','last_month','three','six','year','all','custom')
    if preset not in allowed:
        raise finance.FinanceError('report_range')

    start=today.replace(day=1)
    end=today
    if preset=='today':
        start=end=today
    elif preset=='last_month':
        first_this=today.replace(day=1)
        end=first_this-timedelta(days=1)
        start=end.replace(day=1)
    elif preset in ('three','six'):
        months_back=2 if preset=='three' else 5
        ordinal=today.year*12+today.month-1-months_back
        start=date(ordinal//12,ordinal%12+1,1)
    elif preset=='year':
        start=today.replace(month=1,day=1)
    elif preset=='all':
        if business_id is None:
            raise finance.FinanceError('report_range')
        bounds=finance.get_report_date_bounds(
            business_id,actor_user_id=actor_user_id)
        start=date.fromisoformat(bounds['first_on']) if bounds['first_on'] else today
        end=today
    elif preset=='custom':
        # Custom dates are validated below; defaults keep the form usable if
        # one field is omitted by a stale/bookmarked URL.
        start=today.replace(day=1)
        end=today

    first,last=finance.report_period(
        args.get('start',start.isoformat()),
        args.get('end',end.isoformat()))
    finance.report_months(first[:7],last[:7])
    as_of=finance._date(args.get('as_of',last))
    if last > today_iso or as_of > today_iso:
        raise finance.FinanceError('report_range')
    try:
        future_start=args.get('commitment_start',today_iso)
        future_end=args.get('commitment_end',(today+timedelta(days=29)).isoformat())
        future_start,future_end=finance.report_period(future_start,future_end)
    except (ValueError,OverflowError):
        raise finance.FinanceError('report_range') from None
    return dict(
        preset=preset,start=first,end=last,as_of=as_of,
        commitment_start=future_start,commitment_end=future_end)


def money_csv(value,currency):
    return f'{finance_fx.major(int(value or 0),currency):.2f}'


def csv_cell(value):
    if value is None:return ''
    if type(value) is int:return str(value)  # numeric negatives remain numeric
    text=str(value)
    if text.lstrip().startswith(('=','+','-','@')):return "'"+text
    return text


def csv_bytes(headers, rows):
    output=io.BytesIO();output.write(b'\xef\xbb\xbf')
    line=io.StringIO(newline='');writer=csv.writer(line,lineterminator='\r\n')
    def write(row):
        line.seek(0);line.truncate(0);writer.writerow([csv_cell(v) for v in row])
        data=line.getvalue().encode('utf-8')
        if output.tell()+len(data)>MAX_CSV_BYTES:raise finance.FinanceError('report_limit')
        output.write(data)
    write(headers)
    for count,row in enumerate(rows,1):
        if count>finance.MAX_REPORT_ROWS:raise finance.FinanceError('report_limit')
        write(row)
    return output.getvalue()


def report_data(name,business_id,filters,actor_user_id):
    actor={'actor_user_id':actor_user_id};start,end=filters['start'],filters['end']
    if name=='transactions':return finance.get_report_transactions(business_id,start,end,include_void=True,**actor)
    if name=='invoices':return finance.get_report_invoices(business_id,filters['as_of'],start,end,**actor)
    if name=='category_breakdown':return finance.get_category_breakdown(business_id,start,end,**actor)
    if name=='accounts':return finance.get_account_balance_report(business_id,filters['as_of'],**actor)
    if name=='customers':return finance.get_customer_contribution_report(business_id,start,end,**actor)
    if name=='projects':return finance.get_project_contribution_report(business_id,start,end,**actor)
    if name=='receivables_aging':
        aging=finance.get_receivables_aging(business_id,filters['as_of'],**actor)
        return [dict(bucket,currency=group['currency']) for group in aging['by_currency'] for bucket in group['buckets']]
    if name=='recurring_commitments':return finance.get_upcoming_recurring_commitments(business_id,filters['commitment_start'],filters['commitment_end'],**actor)
    raise finance.FinanceError('report_unavailable')


def export_csv(name,business_id,filters,actor_user_id):
    data=report_data(name,business_id,filters,actor_user_id)
    if name=='transactions':
        headers=('Branch','tanggal','jenis','mata_uang','nominal','akun','kategori','customer','proyek','pihak_lawan','deskripsi','status','sumber')
        rows=((r['branch_name'],r['occurred_on'],DIRECTIONS[r['direction']],r['currency'],money_csv(r['amount_minor'],r['currency']),r['account_name'],
               r['category_name'],r['customer_name'],r['project_name'],r['counterparty_name'],r['description'],
               STATUSES[r['status']],SOURCES.get(r['source_type'],'Manual')) for r in data)
    elif name=='invoices':
        headers=('Branch','nomor_invoice','customer','tanggal_terbit','jatuh_tempo','status','mata_uang','total','sudah_dibayar','sisa','hari_terlambat','overdue')
        rows=((r['branch_name'],r['invoice_number'],r['customer_name'],r['issue_date'],r['due_date'],STATUSES[r['status']],
               r['currency'],money_csv(r['total_minor'],r['currency']),money_csv(r['paid_minor'],r['currency']),money_csv(r['outstanding_minor'],r['currency']),r['days_late'],'Ya' if r['overdue'] else 'Tidak') for r in data)
    elif name=='category_breakdown':
        headers=('mata_uang','jenis','kategori','nominal','jumlah_transaksi','persentase')
        rows=((r['currency'],DIRECTIONS[r['direction']],r['name'],money_csv(r['amount_minor'],r['currency']),r['transaction_count'],r['percentage']) for r in data)
    elif name=='accounts':
        headers=('Branch','akun','jenis','mata_uang','status','saldo_awal','pemasukan','pengeluaran','penukaran_masuk','penukaran_keluar','saldo')
        rows=((r['branch_name'],r['name'],r.get('account_type_label') or ACCOUNT_TYPES.get(r['account_type'],r['account_type']),r['currency'],'Aktif' if r['is_active'] else 'Nonaktif',
               money_csv(r['opening_balance_minor'],r['currency']),money_csv(r['income_minor'],r['currency']),money_csv(r['expense_minor'],r['currency']),money_csv(r.get('exchange_in_minor',0),r['currency']),money_csv(r.get('exchange_out_minor',0),r['currency']),money_csv(r['balance_minor'],r['currency'])) for r in data)
    elif name in ('customers','projects'):
        headers=(('customer' if name=='customers' else 'proyek'),'mata_uang','pemasukan','pengeluaran','kontribusi_kas','jumlah_transaksi')
        rows=((r['name'] if name=='customers' else r['title'],r['currency'],money_csv(r['income_minor'],r['currency']),money_csv(r['expense_minor'],r['currency']),
               money_csv(r['net_cash_contribution_minor'],r['currency']),r['transaction_count']) for r in data)
    elif name=='receivables_aging':
        headers=('mata_uang','kelompok','nominal','jumlah_invoice')
        rows=((r['currency'],r['label'],money_csv(r['amount_minor'],r['currency']),r['invoice_count']) for r in data)
    else:
        headers=('Branch','biaya_rutin','tanggal_jatuh_tempo','mata_uang','nominal','proyek','akun','kategori')
        rows=((r['branch_name'],r['name'],r['scheduled_on'],r['currency'],money_csv(r['amount_minor'],r['currency']),r['project_name'],r['account_name'],r['category_name']) for r in data)
    return csv_bytes(headers,rows)


def export_zip(business_id,filters,actor_user_id):
    output=io.BytesIO();total=0
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in REPORT_NAMES:
            data=export_csv(name,business_id,filters,actor_user_id)
            total+=len(data)
            if total>MAX_BUNDLE_BYTES:raise finance.FinanceError('report_limit')
            archive.writestr(name+'.csv',data)
    return output.getvalue()
