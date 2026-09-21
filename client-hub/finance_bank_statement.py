"""Conservative text-table adapter; unfamiliar/inconsistent layouts go to visual review.

No account inference. Decimal statement amounts remain exact until the staging boundary.
Only complete, reconciled sections qualify for deterministic extraction.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

CURRENCY = re.compile(r'(?im)^\s*(?:MATA\s+UANG|CURRENCY)\s*:\s*([A-Z]{3})\b')
MONTHS = {'JANUARI':1,'FEBRUARI':2,'MARET':3,'APRIL':4,'MEI':5,'JUNI':6,
          'JULI':7,'AGUSTUS':8,'SEPTEMBER':9,'OKTOBER':10,'NOVEMBER':11,'DESEMBER':12,
          'JANUARY':1,'FEBRUARY':2,'MARCH':3,'MAY':5,'JUNE':6,'JULY':7,'AUGUST':8,
          'OCTOBER':10,'DECEMBER':12}
MONEY = r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\.[0-9]{2}'
TAIL = re.compile(r'(?<![\w./])('+MONEY+r')(?:\s+(DB|CR))?(?:\s+('+MONEY+r'))?\s*$')
SUMMARY = re.compile(r'^(SALDO AWAL|SALDO AKHIR|MUTASI CR|MUTASI DB)\s*:\s*('+MONEY+r')(?:\s+(\d+))?\s*$')
START = re.compile(r'^(\d{2})/(\d{2})\s+(.+)$')
FX_WORDS = re.compile(r'\b(?:POKET\s+VALAS|FOREIGN\s+CURRENCY\s+POCKET|KONVERSI|CURRENCY\s+EXCHANGE|FX\s+TRANSFER)\b',re.I)


def sections(text):
    """Split explicit currency sections, retaining physical page numbers and all text.

    Headerless continuation pages inherit only the preceding explicit section currency.
    An unknown leading page remains unknown and prevents deterministic acceptance.
    """
    result=[]; inherited=None
    for page_no,page in enumerate((text or '').split('\f'),1):
        markers=list(CURRENCY.finditer(page))
        if not markers:
            result.append(dict(page=page_no,currency=inherited,text=page));continue
        for n,marker in enumerate(markers):
            inherited=marker[1].upper()
            start=0 if n==0 else marker.start()
            end=markers[n+1].start() if n+1<len(markers) else len(page)
            result.append(dict(page=page_no,currency=inherited,text=page[start:end]))
    return result


def decimal_amount(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',value):
        raise ValueError('invalid_amount')
    amount=Decimal(value)
    if not 0<amount<Decimal(2**63):raise ValueError('invalid_amount')
    return amount


def review_amount(amount,currency):
    """Every Finance currency is stored at two decimal places."""
    exact=decimal_amount(amount)
    units=exact*100
    rounded=max(1,int(units.to_integral_value(rounding=ROUND_HALF_UP)))
    if rounded>=2**63:raise ValueError('invalid_amount')
    return rounded,{}


def possible_fx(description,currency):
    if FX_WORDS.search(description):return True
    # A transfer with an explicitly different currency is held, even without its other leg.
    return bool(re.search(r'\b(?:TRSF|TRANSFER|EXCHANGE|KONVERSI)\b',description,re.I)
                and any(code!=currency for code in re.findall(r'\b([A-Z]{3})\s*\d+[.,]\d+',description)))


def parse(text):
    parts=sections(text)
    if not text or any(not p['currency'] for p in parts):return None
    # Currency sections may span pages, but a currency that reappears after another section
    # remains a separate statement. Never reconcile two accounts merely by currency.
    groups=[]
    for part in parts:
        if groups and groups[-1]['currency']==part['currency']:
            groups[-1]['text']+='\n'+part['text']
        else:groups.append(dict(part))
    output=[]
    for section in groups:
        body=section['text'];currency=section['currency']
        periods=re.findall(r'(?im)^\s*(?:PERIODE|PERIOD)\s*:\s*([A-Z]+)\s+(\d{4})\s*$',body)
        if not periods or len(set(periods))!=1 or periods[0][0] not in MONTHS:return None
        month,year=MONTHS[periods[0][0]],int(periods[0][1])
        if not re.search(r'TANGGAL\s+KETERANGAN\s+CBG\s+MUTASI\s+SALDO',body):return None
        rows=[];summary={};block=None;in_table=False

        def finish():
            if block is None:return
            if block['description'][0].startswith(('SALDO AWAL','SALDO AKHIR')):return
            if block['amount'] is None:raise ValueError('uncertain_table')
            description=' '.join(block['description']).strip()
            rows.append(dict(transaction_date=block['date'],description=description,
                direction=block['direction'],amount=block['amount'],currency=currency,reference=None))

        try:
            for raw in body.splitlines():
                line=raw.strip()
                if re.search(r'TANGGAL\s+KETERANGAN\s+CBG\s+MUTASI\s+SALDO',line):
                    in_table=True;continue
                found=SUMMARY.fullmatch(line)
                if found:
                    finish();block=None;in_table=False
                    if found[1] in summary:return None
                    summary[found[1]]=(Decimal(found[2].replace(',','')),int(found[3]) if found[3] else None)
                    continue
                start=START.match(line)
                if start and in_table:
                    finish()
                    day,mm=int(start[1]),int(start[2])
                    if mm!=month:return None
                    block=dict(date=date(year,mm,day).isoformat(),description=[],amount=None,direction=None)
                    line=start[3]
                elif not in_table or block is None:continue
                # Repeated page headers and footers are not description continuations.
                if re.match(r'^(?:Bersambung|REKENING |CATATAN:|HALAMAN|PERIODE|MATA UANG)',line):
                    finish();block=None;in_table=False;continue
                match=TAIL.search(line)
                if match:
                    if block['amount'] is not None:return None
                    block['amount']=match[1].replace(',','')
                    block['direction']='EXPENSE' if match[2]=='DB' else 'INCOME'
                    line=line[:match.start()].strip()
                    line=re.sub(r'(?:^|\s)\d{4}$','',line).strip()  # optional CBG code
                if line:block['description'].append(line)
            finish()
            if set(summary)!={'SALDO AWAL','SALDO AKHIR','MUTASI CR','MUTASI DB'}:return None
            for label,direction in (('MUTASI CR','INCOME'),('MUTASI DB','EXPENSE')):
                selected=[r for r in rows if r['direction']==direction]
                if (len(selected)!=summary[label][1] or
                        sum((Decimal(r['amount']) for r in selected),Decimal(0))!=summary[label][0]):return None
            if summary['SALDO AWAL'][0]+summary['MUTASI CR'][0]-summary['MUTASI DB'][0]!=summary['SALDO AKHIR'][0]:return None
        except (ValueError,IndexError):return None
        output.extend(rows)
    return output if len(output)<=1000 else None
