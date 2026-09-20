"""Offline provider fixtures for the pre-existing adapter regression vocabulary.

These simulate model responses, NOT a production fallback or language-quality
benchmark. The brain contract tests supply explicit independent JSON responses.
"""
import json
import re
from unittest.mock import Mock,patch
import finance_semantics as language
import finance_assistant_flow as flow
import finance_draft_interpreter as draft
import finance_conversation_actions as commands
import finance_query_plan as queries


def install(case):
    original=case.response
    def response(*args,**kwargs):
        body=kwargs.get('json',{})
        if 'Interpret Indonesian/English Finance language' not in body.get('system',''):return original
        supplied=original.json.return_value
        payload=json.loads(supplied['content'][0]['text'])
        # Explicit malicious, failure and model-patch fixtures retain their exact payload.
        if payload!=case.result:return original
        request=json.loads(body['messages'][0]['content'])
        result=interpret(case,request['message'],request['context'])
        model=Mock(status_code=200)
        model.json.return_value={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(result)}]}
        return model
    case.http.side_effect=response


def interpret(case,message,state):
    text=language.normalize(message);low=text.lower();slots={}
    def result(intent):return dict(intent=intent,slots={k:v for k,v in slots.items() if v and v.casefold() in message.casefold()})
    def literal(value):
        if value and value.casefold() in message.casefold():return message[message.casefold().index(value.casefold()):message.casefold().index(value.casefold())+len(value)]
        return None
    if re.search('cuaca|presiden|puisi|resep|joke|politik|resep|bitcoin besok',low):return result('unknown')
    if re.search('kamu bisa|hai|halo',low):return result('capabilities')
    question,write,schedule=flow.message_intents(text)
    reading=flow.is_read_query(case.b,case.uid,text) or (state.get('previous_query') and __import__('finance_assistant_queries').is_contextual_followup(text))
    if state.get('previous_query') and low=='berikutnya':
        slots['page']=message;return result('continue_query')
    if state.get('action')=='invoice' and re.match(r'tambah item',low):
        item=re.search(r'tambah item (.+?)\s+(\d+(?:[.,]\d+)*\s*(?:ribu|rb|juta|jt))',message,re.I)
        if item:
            slots.update(item_description=item[1],amount=item[2]);qty=re.search(r'qty (\d+)',message,re.I)
            if qty:slots['quantity']=qty[1]
            return result('add_invoice_item')
    if state.get('action') and not reading:
        # Fixture vocabulary mirrors the explicitly expected edits in old tests.
        fields=[];values={}
        for f in state['fields']:
            key=draft.REFERENCES.get(f['name'],f['name']);values[key]=f['value']
            fields.append(dict(key=key,options=[dict(value=o,label=o) for o in f['options']]))
        context=dict(action=state['action'],values=values)
        slots.update(draft.deterministic(message,context,fields))
        if state['action']=='customer':
            match=re.match(r'(?:nama(?:nya)?(?: customernya)?|atas nama)(?: jadi| adalah)?\s+(.+)',message,re.I)
            if match:slots['name']=match[1]
            phone=re.search(r'(\+?\d[\d -]{4,62})',message)
            if phone and re.search(r'nom|hp|wa|telepon',low):slots={'phone':phone[1]}
        for key in ('date','due_date','issue_date'):
            if key in slots and not literal(slots[key]):slots[key]=message
        if slots:return result('continue_draft')
        missing=state.get('missing_field')
        if missing in ('name','phone','item_description'):slots[missing]=message;return result('continue_draft')
        return result('new_command' if write else 'unknown')
    if state.get('previous_query',{}).get('awaiting') and not write and not reading:
        key=state['previous_query']['awaiting'];slots[key]=message;return result('continue_query')
    if reading:
        previous=state.get('previous_query',{})
        def scope(b,u,msg,candidate,key='account'):
            return None if re.search(r'namanya|weh|kita|siapa|apa aja',candidate) else candidate
        with patch.object(queries,'ambiguous_entity_scope',side_effect=scope):p=queries.plan(case.b,case.uid,text,previous)
        for key in ('account','customer','category','project','branch','invoice'):
            if p.get(key):slots[key]=literal(p[key])
        # Preserve unknown/typo entity spellings rather than fixture DB names.
        for key,label in [('customer','customer|pelanggan|piutang'),('project','proyek'),('account','rekening|akun'),('branch','cabang')]:
            if key in p and not slots.get(key):
                match=re.search(r'(?:'+label+r')\s+([\w-]+)',text,re.I)
                if match:slots[key]=literal(match[1])
        if language.period_patch(text):slots['period']=message
        if flow.currency_hint(text):slots['currency']=message
        for word in ('pemasukan','pendapatan','pengeluaran','arus kas'):
            if word in low:slots['direction']=literal(word) or literal(word+'nya')
        if p.get('group_by'):
            slots['group_by']=literal({'project':'proyek','category':'kategori','customer':'customer','branch':'cabang'}[p['group_by']])
        for key in ('overdue','aging','due_week'):
            if p.get(key):slots[key]=message
        if re.search('semua cabang',low):slots['branch']=literal('semua cabang')
        resource='recurring_list' if p['resource']=='recurring' else p['resource']
        return result('continue_query' if previous and __import__('finance_assistant_queries').is_contextual_followup(text) else resource)
    op=commands.route(case.b,case.uid,text,classify_only=True)
    if op:
        if op.startswith('create_'):
            match=re.search(r'(?:rekening|akun|kategori|cabang)\s*(.*)',text,re.I);raw=match[1] if match else ''
            if op=='create_category':
                typ=re.search(r'pemasukan|pendapatan|pengeluaran',raw,re.I)
                if typ:slots['direction']=literal(typ[0]);raw=raw.replace(typ[0],'').strip()
            if op=='create_account':
                typ=re.search(r'\b(bank|cash|tunai|ewallet)\b',raw,re.I)
                if typ:slots['account_type']=literal(typ[0]);raw=raw.replace(typ[0],'').strip()
                currency=flow.currency_hint(raw)
                if currency:slots['currency']=literal(currency);raw=re.sub(currency,'',raw,flags=re.I).strip()
                opening=re.search(r'saldo awal\s+(.+)',raw,re.I)
                if opening:slots['opening_balance']=literal(opening[1]);raw=raw[:opening.start()].strip()
            slots['name']=literal(raw)
        elif op=='exchange':
            amounts=list(flow.AMOUNT.finditer(message))
            if len(amounts)==2:slots.update(from_amount=amounts[0][0],to_amount=amounts[1][0])
            for key,pattern in [('from_account',r'dari (.+?)(?= ke |$)'),('to_account',r'ke (.+?)(?= jadi |$)')]:
                m=re.search(pattern,message,re.I)
                if m:slots[key]=m[1]
        else:
            if re.search(r'yang tadi|transaksi tadi|itu',low):slots['target_reference']=message
            else:
                kind=op.split('_',1)[1]
                for row in commands.targets(case.b,case.uid,kind):
                    if literal(row['name']):slots['target']=literal(row['name']);break
                if not slots.get('target'):
                    m=re.search(r'(?:transaksi|invoice|rutin|rekening|akun|kategori|cabang|customer|pelanggan|fx)\s+(.+)',text,re.I)
                    if m:slots['target']=literal(m[1])
            rename=re.search(r'\s+jadi\s+(.+)',text,re.I)
            if rename:slots['name']=literal(rename[1])
        return result(op)
    customer=re.search(r'(?:tambah|buat)\s+customer\s+(.+)',text,re.I)
    if customer:
        raw=customer[1];name=re.split(r',|\s+(?:nomor|email|catatan|whatsapp|wa|telepon)',raw,flags=re.I)[0]
        name=re.sub(r'^(?:atas nama|bernama|namanya|nama)\s+','',name,flags=re.I)
        name=re.sub(r'\s+(?:ya|dong|weh)$','',name,flags=re.I)
        if name.lower()!='baru':slots['name']=literal(name)
        phone=re.search(r'(\+?\d[\d -]{4,62})',raw)
        if phone:slots['phone']=literal(phone[1].strip())
        email=re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',raw)
        if email:slots['email']=literal(email[0])
        return result('customer')
    invoice=bool(re.search(r'(?:buat|tambah)\s+invoice',text,re.I))
    intent='invoice' if invoice else 'recurring' if schedule else 'record_invoice_payment' if 'invoice' in low else 'create_income' if re.search('pemasukan|pendapatan|terima|dibayar|bayaran',low) else 'create_expense' if re.search('pengeluaran|beli|bayar|catat|makan|bensin|software|internet',low) else 'unknown'
    amounts=list(flow.AMOUNT.finditer(message)) or list(flow.BARE_AMOUNT.finditer(message))
    if len(amounts)>1:return result('unknown')
    if amounts:slots['amount']=amounts[0][0]
    if flow.proposed_date(text,scheduled=True) or re.search(r'besok',text,re.I):slots['date' if not invoice else 'issue_date']=message
    if flow.currency_hint(text):slots['currency']=message
    for key,rows,label in [('account',flow.f.list_accounts(case.b), 'name'),('customer',flow.f.list_customers(case.b),'name'),('project',flow.f.list_finance_projects(case.b),'title')]:
        for row in rows:
            if literal(row[label]):slots[key]=literal(row[label]);break
    if intent=='record_invoice_payment':
        slots.pop('customer',None)
        settlement=re.search(r'\b(lunas|lunasi|pelunasan)\b',message,re.I)
        if settlement:slots['settlement']=settlement[0]
        num=re.search(r'(?:KFIN|INV)-[\w-]+',message,re.I)
        if num:slots['invoice']=num[0]
    elif invoice:
        if 'date' in slots:slots['issue_date']=slots.pop('date')
        due=re.search(r'jatuh tempo\s+(.+)',message,re.I)
        if due:slots['due_date']=due[1];slots.pop('issue_date',None)
        desc=re.sub(r'^.*?invoice\s*','',text,flags=re.I)
        if slots.get('customer'):desc=desc.replace(slots['customer'],'').strip()
        if amounts:desc=desc.split(amounts[0][0])[0].strip()
        if desc:slots['item_description']=literal(desc)
    else:
        if intent=='create_income':direction='INCOME'
        else:direction='EXPENSE'
        categories=flow.f.list_categories(case.b,direction)
        selected=flow.category_choice(categories,text)
        if selected:
            name=next(r['name'] for r in categories if r['id']==selected)
            candidates=[w for w in re.findall(r'[\w/]+',name) if len(w)>2 and literal(w)]
            if literal(name):slots['category']=literal(name)
            elif candidates:slots['category']=literal(max(candidates,key=len))
            elif name=='Software / API' and literal('AI'):slots['category']=literal('AI')
        if schedule:
            cadence=re.search(r'bulanan|mingguan|(?:tiap|setiap|per)\s+(?:bulan|minggu)',message,re.I)
            if not cadence:cadence=re.search(r'(?:tiap|setiap) tanggal \d{1,2}',message,re.I)
            if cadence:slots['cadence']=cadence[0]
            label=re.search(r'(?:untuk|bayar)\s+(.+?)(?=\s+\d|\s+(?:tanggal|mulai|pakai)|$)',message,re.I)
            if label:slots['name']=label[1]
            else:
                name=re.sub(r'^(?:tambah |biaya |rutin )+','',text).split(slots.get('amount','\0'))[0].strip()
                slots['name']=literal(name)
            vendor=re.search(r'\bke\s+(.+?)(?=\s+tanggal|$)',message,re.I)
            if vendor:slots['counterparty_name']=vendor[1]
        slots['description']=message
    return result(intent)
