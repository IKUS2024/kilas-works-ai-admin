"""Read-only export/presentation builders. Standard library, no files or DB mutations."""
import csv
from datetime import date, timedelta
import io
import zipfile
import finance_service as finance

MAX_CSV_BYTES=16*1024*1024
MAX_BUNDLE_BYTES=64*1024*1024
REPORT_NAMES=('transactions','invoices','category_breakdown','accounts','customers','projects','receivables_aging','recurring_commitments')
DIRECTIONS={'INCOME':'Pemasukan','EXPENSE':'Pengeluaran'}
STATUSES={'DRAFT':'Draft','ISSUED':'Belum dibayar','PARTIALLY_PAID':'Dibayar sebagian','PAID':'Lunas','VOID':'Dibatalkan','POSTED':'Tercatat'}
SOURCES={'FINANCE_INVOICE_PAYMENT':'Pembayaran Invoice','FINANCE_RECURRING_EXPENSE':'Biaya Rutin'}
ACCOUNT_TYPES={'CASH':'Kas','BANK':'Bank','EWALLET':'E-Wallet','OTHER':'Lainnya'}


def parse_filters(args, today=None):
    today=today or date.today()
    preset=args.get('preset','month')
    if preset not in ('month','three','year'):raise finance.FinanceError('report_range')
    start=today.replace(day=1)
    if preset=='year':start=today.replace(month=1,day=1)
    if preset=='three':
        ordinal=today.year*12+today.month-1-2
        start=date(ordinal//12,ordinal%12+1,1)
    first,last=finance.report_period(args.get('start',start.isoformat()),args.get('end',today.isoformat()))
    finance.report_months(first[:7],last[:7])
    as_of=finance._date(args.get('as_of',last))
    try:
        future_start=args.get('commitment_start',today.isoformat())
        future_end=args.get('commitment_end',(today+timedelta(days=29)).isoformat())
        future_start,future_end=finance.report_period(future_start,future_end)
    except (ValueError,OverflowError):raise finance.FinanceError('report_range') from None
    return dict(start=first,end=last,as_of=as_of,commitment_start=future_start,commitment_end=future_end)


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
    if name=='receivables_aging':return finance.get_receivables_aging(business_id,filters['as_of'],**actor)['buckets']
    if name=='recurring_commitments':return finance.get_upcoming_recurring_commitments(business_id,filters['commitment_start'],filters['commitment_end'],**actor)
    raise finance.FinanceError('report_unavailable')


def export_csv(name,business_id,filters,actor_user_id):
    data=report_data(name,business_id,filters,actor_user_id)
    if name=='transactions':
        headers=('Branch','tanggal','jenis','nominal_rupiah','akun','kategori','customer','proyek','pihak_lawan','deskripsi','status','sumber')
        rows=((r['branch_name'],r['occurred_on'],DIRECTIONS[r['direction']],r['amount_minor'],r['account_name'],r['category_name'],r['customer_name'],r['project_name'],r['counterparty_name'],r['description'],STATUSES[r['status']],SOURCES.get(r['source_type'],'Manual')) for r in data)
    elif name=='invoices':
        headers=('Branch','nomor_invoice','customer','tanggal_terbit','jatuh_tempo','status','total_rupiah','sudah_dibayar_rupiah','sisa_rupiah','hari_terlambat','overdue')
        rows=((r['branch_name'],r['invoice_number'],r['customer_name'],r['issue_date'],r['due_date'],STATUSES[r['status']],r['total_minor'],r['paid_minor'],r['outstanding_minor'],r['days_late'],'Ya' if r['overdue'] else 'Tidak') for r in data)
    elif name=='category_breakdown':
        headers=('jenis','kategori','nominal_rupiah','jumlah_transaksi','persentase')
        rows=((DIRECTIONS[r['direction']],r['name'],r['amount_minor'],r['transaction_count'],r['percentage']) for r in data)
    elif name=='accounts':
        headers=('Branch','akun','jenis','status','saldo_awal_rupiah','pemasukan_rupiah','pengeluaran_rupiah','saldo_rupiah')
        rows=((r['branch_name'],r['name'],ACCOUNT_TYPES[r['account_type']],'Aktif' if r['is_active'] else 'Nonaktif',r['opening_balance_minor'],r['income_minor'],r['expense_minor'],r['balance_minor']) for r in data)
    elif name in ('customers','projects'):
        headers=('customer' if name=='customers' else 'proyek','pemasukan_rupiah','pengeluaran_rupiah','kontribusi_kas_rupiah','jumlah_transaksi')
        rows=((r['name'] if name=='customers' else r['title'],r['income_minor'],r['expense_minor'],r['net_cash_contribution_minor'],r['transaction_count']) for r in data)
    elif name=='receivables_aging':
        headers=('kelompok','nominal_rupiah','jumlah_invoice');rows=((r['label'],r['amount_minor'],r['invoice_count']) for r in data)
    else:
        headers=('Branch','biaya_rutin','tanggal_jatuh_tempo','nominal_rupiah','proyek','akun','kategori')
        rows=((r['branch_name'],r['name'],r['scheduled_on'],r['amount_minor'],r['project_name'],r['account_name'],r['category_name']) for r in data)
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
