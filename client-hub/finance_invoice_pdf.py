"""Professional PDF export for a single Kilas Finance invoice.

Input is the privacy-safe document projection from finance_invoice_view.document().
No database access or writes happen here.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


STATUS_LABELS = {
    'DRAFT': 'DRAFT',
    'ISSUED': 'BELUM DIBAYAR',
    'PARTIALLY_PAID': 'DIBAYAR SEBAGIAN',
    'PAID': 'LUNAS',
    'VOID': 'DIBATALKAN',
}


def _safe(value):
    if value is None or value == '':
        return '-'
    return (str(value).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def money(value, currency):
    value = int(value or 0)
    sign = '-' if value < 0 else ''
    amount = abs(value)
    whole, fraction = divmod(amount, 100)
    grouped = f'{whole:,}'.replace(',', '.')
    if currency == 'IDR':
        return f'{sign}Rp{grouped},{fraction:02d}'
    if currency == 'USD':
        prefix = 'US$'
    elif currency == 'SGD':
        prefix = 'S$'
    else:
        prefix = currency + ' '
    return f'{sign}{prefix}{grouped}.{fraction:02d}'


def build(doc):
    invoice = doc['invoice']
    currency = invoice['currency']
    out = BytesIO()
    pdf = SimpleDocTemplate(
        out, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm,
        topMargin=16*mm, bottomMargin=16*mm,
        title=f"{invoice['invoice_number']} - {doc['issuer']}",
        author='Kilas Finance',
    )
    styles = getSampleStyleSheet()
    eyebrow = ParagraphStyle(
        'InvoiceEyebrow', parent=styles['Normal'], fontName='Helvetica-Bold',
        fontSize=8, leading=10, textColor=colors.HexColor('#D86818'),
        spaceAfter=3,
    )
    title = ParagraphStyle(
        'InvoiceTitle', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=24, leading=27, textColor=colors.HexColor('#151515'),
        spaceAfter=3,
    )
    h2 = ParagraphStyle(
        'InvoiceH2', parent=styles['Heading2'], fontName='Helvetica-Bold',
        fontSize=11, leading=14, textColor=colors.HexColor('#202124'),
        spaceBefore=8, spaceAfter=4,
    )
    body = ParagraphStyle(
        'InvoiceBody', parent=styles['BodyText'], fontName='Helvetica',
        fontSize=8.5, leading=12, textColor=colors.HexColor('#3C4043'),
    )
    small = ParagraphStyle(
        'InvoiceSmall', parent=body, fontSize=7.5, leading=10,
        textColor=colors.HexColor('#666666'),
    )
    right = ParagraphStyle('InvoiceRight', parent=body, alignment=TA_RIGHT)

    status = STATUS_LABELS.get(invoice['status'], invoice['status'])
    if doc['totals'].get('overdue') and invoice['status'] in ('ISSUED', 'PARTIALLY_PAID'):
        status += ' - LEWAT JATUH TEMPO'

    sender = doc.get('sender', {})
    sender_lines=[_safe(sender[k]) for k in ('address','phone','email','tax_id','website') if sender.get(k)]
    heading = Table([[
        [Paragraph('DARI',eyebrow),Paragraph(_safe(doc['issuer']),h2),
         Paragraph('<br/>'.join(sender_lines) or '-',body)],
        [Paragraph('INVOICE',ParagraphStyle('InvoiceHeadingRight',parent=title,alignment=TA_RIGHT)),
         Paragraph(_safe(invoice['invoice_number']),right),Paragraph(status,right)]
    ]],colWidths=[108*mm,66*mm])
    heading.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
        ('RIGHTPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),10),
    ]))
    story=[heading,Spacer(1,3*mm)]

    party = [
        [
            Paragraph(
                '<b>Ditagihkan kepada</b><br/>'
                + _safe(doc['customer']['name'])
                + ''.join('<br/>'+_safe(doc['customer'][k]) for k in ('pic','address','tax_id') if doc['customer'].get(k))
                + (f"<br/>{_safe(doc['customer'].get('email'))}" if doc['customer'].get('email') else '')
                + (f"<br/>{_safe(doc['customer'].get('phone'))}" if doc['customer'].get('phone') else ''),
                body,
            ),
            Paragraph(
                f"<b>Tanggal terbit</b><br/>{_safe(invoice['issue_date'])}<br/><br/>"
                f"<b>Jatuh tempo</b><br/>{_safe(invoice['due_date'])}"
                + (f"<br/><b>Referensi / PO</b><br/>{_safe(invoice['reference'])}" if invoice.get('reference') else ''),
                right,
            ),
        ]
    ]
    party_table = Table(party, colWidths=[112*mm, 62*mm])
    party_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#DADCE0')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8F9FA')),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story += [party_table, Spacer(1, 5*mm)]

    item_rows = [['Deskripsi', 'Qty', 'Harga satuan', 'Jumlah']]
    for item in doc['items']:
        item_rows.append([
            Paragraph(_safe(item['description']), body),
            str(item['quantity']),
            money(item['unit_price_minor'], currency),
            money(int(item['quantity']) * int(item['unit_price_minor']), currency),
        ])
    items = Table(item_rows, colWidths=[82*mm, 18*mm, 37*mm, 37*mm], repeatRows=1)
    items.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#202124')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('LEADING', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.35, colors.HexColor('#DADCE0')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story += [items, Spacer(1, 5*mm)]

    totals = doc['totals']
    summary_rows = [
        ['Subtotal', money(totals['total_minor'], currency)],
        ['Total', money(totals['total_minor'], currency)],
        ['Sudah dibayar', money(totals['paid_minor'], currency)],
        ['Sisa tagihan', '-' if invoice['status'] in ('DRAFT','VOID')
         else money(totals['outstanding_minor'], currency)],
    ]
    summary = Table(summary_rows, colWidths=[55*mm, 50*mm], hAlign='RIGHT')
    summary.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('LINEABOVE', (0,-1), (-1,-1), 0.7, colors.HexColor('#202124')),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(summary)

    payment=doc.get('payment',{})
    if any(payment.values()):
        story.append(Paragraph('Pembayaran',h2))
        for key in ('method','bank','account_number','account_holder','instructions'):
            if payment.get(key):
                story.append(Paragraph(('a.n. ' if key=='account_holder' else '')+_safe(payment[key]),body))

    if invoice.get('notes'):
        story += [
            Paragraph('Catatan', h2),
            Paragraph(_safe(invoice['notes']), body),
        ]

    story += [
        Spacer(1, 7*mm),
        Paragraph(
            f"{_safe(doc['issuer'])} - {_safe(invoice['invoice_number'])}. "
            f"Seluruh nominal dalam {currency}. Status sesuai catatan saat PDF dibuat.",
            small,
        ),
    ]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(16*mm, 8*mm, f"Kilas Finance - {invoice['invoice_number']}")
        canvas.drawRightString(A4[0]-16*mm, 8*mm, f"Halaman {document.page}")
        canvas.restoreState()

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
