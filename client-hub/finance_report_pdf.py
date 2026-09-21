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
        prefix = 'US

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
        ['Acuan piutang', filters['as_of']],
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

    story.append(Paragraph('Kas & Rekening', h2))
    account_rows=[['Rekening','Jenis','Mata uang','Saldo']]
    for row in data.get('accounts',[]):
        account_rows.append([
            _safe(row['name']), _safe(row.get('account_type_label') or row.get('account_type')), row['currency'],
            money(row['balance_minor'],row['currency'])
        ])
    story.append(_table(account_rows,[63*mm,34*mm,26*mm,52*mm],header=True,empty='Belum ada rekening.'))

    story.append(Paragraph('Piutang', h2))
    receivable_rows=[['Mata uang','Umur piutang','Nominal','Invoice']]
    for row in data.get('receivables_aging',[]):
        receivable_rows.append([
            row['currency'], _safe(row['label']), money(row['amount_minor'],row['currency']),
            str(row['invoice_count'])
        ])
    story.append(_table(receivable_rows,[27*mm,66*mm,53*mm,29*mm],header=True,empty='Tidak ada piutang terbuka.'))

    story.append(PageBreak())
    story.append(Paragraph('Arus Kas Bulanan', h2))
    trend_rows=[['Bulan','Mata uang','Pemasukan','Pengeluaran','Selisih']]
    for row in trend:
        cur=row['currency']
        trend_rows.append([
            _safe(row['month']),cur,money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['net_cashflow_minor'],cur)
        ])
    story.append(_table(trend_rows,[28*mm,24*mm,41*mm,41*mm,41*mm],header=True))

    story.append(Paragraph('Analisis Kategori', h2))
    category_rows=[['Jenis','Kategori','Mata uang','Nominal','%']]
    for row in data.get('category_breakdown',[]):
        category_rows.append([
            'Pemasukan' if row['direction']=='INCOME' else 'Pengeluaran',
            _safe(row['name']),row['currency'],money(row['amount_minor'],row['currency']),
            f"{row.get('percentage',0)}%"
        ])
    story.append(_table(category_rows,[33*mm,59*mm,25*mm,43*mm,15*mm],header=True))

    story.append(Paragraph('Customer', h2))
    customer_rows=[['Customer','Mata uang','Pemasukan','Pengeluaran','Kontribusi']]
    for row in data.get('customers',[]):
        cur=row['currency']
        customer_rows.append([
            _safe(row['name']),cur,money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['net_cash_contribution_minor'],cur)
        ])
    story.append(_table(customer_rows,[51*mm,24*mm,34*mm,34*mm,32*mm],header=True,empty='Belum ada transaksi yang dikaitkan ke customer.'))

    story.append(Paragraph('Proyek', h2))
    project_rows=[['Proyek','Mata uang','Pemasukan','Pengeluaran','Selisih']]
    for row in data.get('projects',[]):
        cur=row['currency']
        project_rows.append([
            _safe(row['title']),cur,money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['net_cash_contribution_minor'],cur)
        ])
    story.append(_table(project_rows,[51*mm,24*mm,34*mm,34*mm,32*mm],header=True,empty='Belum ada transaksi yang dikaitkan ke proyek.'))

    story.append(Paragraph('Komitmen Biaya Rutin Mendatang', h2))
    commitment_rows=[['Tanggal','Biaya rutin','Mata uang','Nominal','Rekening']]
    for row in data.get('recurring_commitments',[]):
        commitment_rows.append([
            _safe(row['scheduled_on']),_safe(row['name']),row['currency'],
            money(row['amount_minor'],row['currency']),_safe(row.get('account_name'))
        ])
    story.append(_table(commitment_rows,[29*mm,54*mm,24*mm,38*mm,30*mm],header=True,empty='Tidak ada komitmen biaya rutin pada rentang mendatang.'))

    story += [
        Spacer(1, 6*mm),
        Paragraph('<b>Catatan:</b> laporan ini berbasis pencatatan kas di Kilas Finance, bukan laporan laba rugi akrual. '
                  'Saldo tercatat dapat berbeda dari saldo bank aktual sebelum rekonsiliasi. '
                  'Setiap mata uang disajikan terpisah.', small)
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
        ['Acuan piutang', filters['as_of']],
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

    story.append(Paragraph('Kas & Rekening', h2))
    account_rows=[['Rekening','Jenis','Mata uang','Saldo']]
    for row in data.get('accounts',[]):
        account_rows.append([
            _safe(row['name']), _safe(row.get('account_type_label') or row.get('account_type')), row['currency'],
            money(row['balance_minor'],row['currency'])
        ])
    story.append(_table(account_rows,[63*mm,34*mm,26*mm,52*mm],header=True,empty='Belum ada rekening.'))

    story.append(Paragraph('Piutang', h2))
    receivable_rows=[['Mata uang','Umur piutang','Nominal','Invoice']]
    for row in data.get('receivables_aging',[]):
        receivable_rows.append([
            row['currency'], _safe(row['label']), money(row['amount_minor'],row['currency']),
            str(row['invoice_count'])
        ])
    story.append(_table(receivable_rows,[27*mm,66*mm,53*mm,29*mm],header=True,empty='Tidak ada piutang terbuka.'))

    story.append(PageBreak())
    story.append(Paragraph('Arus Kas Bulanan', h2))
    trend_rows=[['Bulan','Mata uang','Pemasukan','Pengeluaran','Selisih']]
    for row in trend:
        cur=row['currency']
        trend_rows.append([
            _safe(row['month']),cur,money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['net_cashflow_minor'],cur)
        ])
    story.append(_table(trend_rows,[28*mm,24*mm,41*mm,41*mm,41*mm],header=True))

    story.append(Paragraph('Analisis Kategori', h2))
    category_rows=[['Jenis','Kategori','Mata uang','Nominal','%']]
    for row in data.get('category_breakdown',[]):
        category_rows.append([
            'Pemasukan' if row['direction']=='INCOME' else 'Pengeluaran',
            _safe(row['name']),row['currency'],money(row['amount_minor'],row['currency']),
            f"{row.get('percentage',0)}%"
        ])
    story.append(_table(category_rows,[33*mm,59*mm,25*mm,43*mm,15*mm],header=True))

    story.append(Paragraph('Customer', h2))
    customer_rows=[['Customer','Mata uang','Pemasukan','Pengeluaran','Kontribusi']]
    for row in data.get('customers',[]):
        cur=row['currency']
        customer_rows.append([
            _safe(row['name']),cur,money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['net_cash_contribution_minor'],cur)
        ])
    story.append(_table(customer_rows,[51*mm,24*mm,34*mm,34*mm,32*mm],header=True,empty='Belum ada transaksi yang dikaitkan ke customer.'))

    story.append(Paragraph('Proyek', h2))
    project_rows=[['Proyek','Mata uang','Pemasukan','Pengeluaran','Selisih']]
    for row in data.get('projects',[]):
        cur=row['currency']
        project_rows.append([
            _safe(row['title']),cur,money(row['income_minor'],cur),
            money(row['expense_minor'],cur),money(row['net_cash_contribution_minor'],cur)
        ])
    story.append(_table(project_rows,[51*mm,24*mm,34*mm,34*mm,32*mm],header=True,empty='Belum ada transaksi yang dikaitkan ke proyek.'))

    story.append(Paragraph('Komitmen Biaya Rutin Mendatang', h2))
    commitment_rows=[['Tanggal','Biaya rutin','Mata uang','Nominal','Rekening']]
    for row in data.get('recurring_commitments',[]):
        commitment_rows.append([
            _safe(row['scheduled_on']),_safe(row['name']),row['currency'],
            money(row['amount_minor'],row['currency']),_safe(row.get('account_name'))
        ])
    story.append(_table(commitment_rows,[29*mm,54*mm,24*mm,38*mm,30*mm],header=True,empty='Tidak ada komitmen biaya rutin pada rentang mendatang.'))

    story += [
        Spacer(1, 6*mm),
        Paragraph('<b>Catatan:</b> laporan ini berbasis pencatatan kas di Kilas Finance, bukan laporan laba rugi akrual. '
                  'Saldo tercatat dapat berbeda dari saldo bank aktual sebelum rekonsiliasi. '
                  'Setiap mata uang disajikan terpisah.', small)
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
