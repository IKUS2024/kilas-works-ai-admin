"""Professional read-only PDF export for Kilas Finance reports.

The PDF summarizes the same branch-scoped, cash-basis data shown in Finance Reporting.
No writes, no currency mixing, and no raw document/source payloads are included.
"""
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def money(value, currency):
    value = int(value or 0)
    sign = '-' if value < 0 else ''
    amount = abs(value)
    whole, fraction = divmod(amount, 100)
    grouped = f'{whole:,}'.replace(',', '.')
    if currency == 'IDR':
        return f'{sign}Rp{grouped},{fraction:02d}'
    if currency == 'USD':
        prefix = 'US' + '$'
    else:
        prefix = currency + ' '
    return f'{sign}{prefix}{grouped},{fraction:02d}'


def _safe(value):
    if value is None or value == '':
        return '—'
    return str(value).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')


def build(*, business_name, branch_name, filters, summary, trend, data):
    out = BytesIO()
    doc = SimpleDocTemplate(
        out, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm,
        topMargin=15*mm, bottomMargin=16*mm,
        title=f'Laporan Finance - {business_name}',
        author='Kilas Finance'
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle('KilasTitle', parent=styles['Title'], fontName='Helvetica-Bold',
                           fontSize=20, leading=23, textColor=colors.HexColor('#151515'), spaceAfter=4)
    eyebrow = ParagraphStyle('KilasEyebrow', parent=styles['Normal'], fontName='Helvetica-Bold',
                             fontSize=8, leading=10, textColor=colors.HexColor('#D86818'),
                             spaceAfter=3)
    h2 = ParagraphStyle('KilasH2', parent=styles['Heading2'], fontName='Helvetica-Bold',
                        fontSize=12, leading=15, textColor=colors.HexColor('#202124'),
                        spaceBefore=9, spaceAfter=5)
    body = ParagraphStyle('KilasBody', parent=styles['BodyText'], fontName='Helvetica',
                          fontSize=8.5, leading=12, textColor=colors.HexColor('#3C4043'))
    small = ParagraphStyle('KilasSmall', parent=body, fontSize=7.5, leading=10,
                           textColor=colors.HexColor('#666666'))
    right = ParagraphStyle('KilasRight', parent=body, alignment=TA_RIGHT)

    story = [
        Paragraph('KILAS FINANCE', eyebrow),
        Paragraph('Laporan Finance', title),
        Paragraph(f'<b>{_safe(business_name)}</b> · Cabang {_safe(branch_name)}', body),
        Spacer(1, 5*mm),
    ]

    meta = [
        ['Periode', f"{filters['start']} – {filters['end']}"],
        ['Jenis laporan', 'Ringkasan keseluruhan Finance'],
        ['Basis laporan', 'Kas / cash basis'],
        ['Mata uang', 'Ditampilkan terpisah, tanpa penggabungan kurs'],
    ]
    story.append(_table(meta, [37*mm, 138*mm], header=False))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph('Ringkasan Eksekutif', h2))
    summary_rows = [['Mata uang','Pemasukan','Pengeluaran','Selisih','Transaksi']]
    for row in summary:
        cur=row['currency']
        summary_rows.append([
            cur, money(row['total_income_minor'],cur), money(row['total_expense_minor'],cur),
            money(row['net_cashflow_minor'],cur), str(row.get('transaction_count',0))
        ])
    story.append(_table(summary_rows, [25*mm,42*mm,42*mm,42*mm,24*mm], header=True))

    story.append(Paragraph('Pemasukan', h2))
    income_rows=[['Kategori','Mata uang','Nominal','Transaksi','%']]
    for row in data.get('income_categories',[]):
        income_rows.append([
            _safe(row['name']),row['currency'],money(row['amount_minor'],row['currency']),
            str(row.get('transaction_count',0)),f"{row.get('percentage',0)}%"
        ])
    story.append(_table(income_rows,[68*mm,25*mm,45*mm,22*mm,15*mm],header=True,
                        empty='Belum ada pemasukan pada periode ini.'))

    story.append(Paragraph('Pengeluaran', h2))
    expense_rows=[['Kategori','Mata uang','Nominal','Transaksi','%']]
    for row in data.get('expense_categories',[]):
        expense_rows.append([
            _safe(row['name']),row['currency'],money(row['amount_minor'],row['currency']),
            str(row.get('transaction_count',0)),f"{row.get('percentage',0)}%"
        ])
    story.append(_table(expense_rows,[68*mm,25*mm,45*mm,22*mm,15*mm],header=True,
                        empty='Belum ada pengeluaran pada periode ini.'))

    story.append(Paragraph('Anggaran', h2))
    budget_rows=[['Bulan','Kategori','Mata uang','Anggaran']]
    for row in data.get('budgets',[]):
        budget_rows.append([
            _safe(row['month']),_safe(row['category_name']),row['currency'],
            money(row['amount_minor'],row['currency'])
        ])
    story.append(_table(budget_rows,[30*mm,75*mm,28*mm,42*mm],header=True,
                        empty='Belum ada anggaran pada periode ini.'))

    story.append(PageBreak())
    story.append(Paragraph('Tagihan', h2))
    recurring_rows=[['Nama','Jadwal berikutnya','Frekuensi','Mata uang','Nominal','Akun']]
    for row in data.get('recurring_rules',[]):
        recurring_rows.append([
            _safe(row['name']),_safe(row['next_due_on']),_safe(row['cadence_label']),
            row['currency'],money(row['amount_minor'],row['currency']),_safe(row.get('account_name'))
        ])
    story.append(_table(recurring_rows,[43*mm,31*mm,27*mm,22*mm,30*mm,22*mm],header=True,
                        empty='Tidak ada tagihan rutin aktif.'))

    story.append(Paragraph('Akun', h2))
    account_rows=[['Akun','Jenis','Mata uang','Saldo awal','Pemasukan','Pengeluaran','Saldo']]
    for row in data.get('accounts',[]):
        cur=row['currency']
        account_rows.append([
            _safe(row['name']),_safe(row.get('account_type_label') or row.get('account_type')),
            cur,money(row['opening_balance_minor'],cur),money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['balance_minor'],cur)
        ])
    story.append(_table(account_rows,[34*mm,27*mm,19*mm,25*mm,25*mm,25*mm,25*mm],
                        header=True,empty='Belum ada akun aktif.'))

    story.append(Paragraph('Penerima', h2))
    payee_rows=[['Penerima','Mata uang','Total dibayar','Transaksi','Terakhir dibayar']]
    for row in data.get('payees',[]):
        payee_rows.append([
            _safe(row['name']),row['currency'],money(row['total_minor'],row['currency']),
            str(row.get('transaction_count',0)),_safe(row.get('last_paid_on'))
        ])
    story.append(_table(payee_rows,[65*mm,27*mm,40*mm,20*mm,33*mm],header=True,
                        empty='Belum ada penerima pada periode ini.'))

    story += [
        Spacer(1, 6*mm),
        Paragraph('<b>Catatan:</b> laporan ini menyatukan Pemasukan, Pengeluaran, Anggaran, Tagihan, Akun, dan Penerima dari data Kilas Finance yang sama. '
                  'Laporan bisnis berbasis pencatatan kas, bukan laporan laba rugi akrual. '
                  'Setiap mata uang disajikan sesuai pencatatannya.', small)
    ]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica',7)
        canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(15*mm,8*mm,f'Kilas Finance · {branch_name}')
        canvas.drawRightString(A4[0]-15*mm,8*mm,f'Halaman {doc.page}')
        canvas.restoreState()

    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()


def _table(rows,widths,header=True,empty='Belum ada data pada periode ini.'):
    if len(rows)==1 and header:
        rows = [rows[0], [empty] + ['']*(len(rows[0])-1)]
    table=Table(rows,colWidths=widths,repeatRows=1 if header else 0,hAlign='LEFT')
    style=[
        ('FONTNAME',(0,0),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),7.3),
        ('LEADING',(0,0),(-1,-1),9),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#DADCE0')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8F9FA')]),
        ('LEFTPADDING',(0,0),(-1,-1),4),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
        ('TOPPADDING',(0,0),(-1,-1),4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
    ]
    if header:
        style += [
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#202124')),
            ('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ]
    table.setStyle(TableStyle(style))
    return table
