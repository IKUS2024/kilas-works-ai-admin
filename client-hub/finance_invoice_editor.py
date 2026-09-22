"""Invoice-only snapshots/defaults and revisions; never posts or rewrites payments."""
import json
import db
import repo
import finance_service as f
import account_profile_service as account_profiles

SENDER = ('name','address','phone','email','tax_id','website')
RECIPIENT = ('name','pic','address','phone','email','tax_id')
PAYMENT = ('method','bank','account_number','account_holder','instructions')
GROUPS = {'sender': SENDER, 'recipient': RECIPIENT, 'payment': PAYMENT}


def _owner_email(business_id):
    """Canonical non-editable sender email for new Finance invoices."""
    return repo.get_business_owner_email(business_id) or ''


def _workspace_identity(business_id, actor_user_id=None):
    """Return the current scoped workspace and its sender identity."""
    branch_id = f.branches.write_branch(business_id, actor_user_id)
    branch = f.branches.get(
        business_id, branch_id, active=True, actor_user_id=actor_user_id)
    workspace_type = branch.get('workspace_type') or 'BUSINESS'
    if workspace_type == 'PERSONAL':
        user = repo.get_user_by_id(actor_user_id) if actor_user_id is not None else None
        email = (user or {}).get('email') or _owner_email(business_id)
        name = (user or {}).get('full_name') or (email.split('@')[0] if email else 'Pribadi')
        return workspace_type, name, email
    business = db.query_one('SELECT business_name FROM businesses WHERE id=?',(business_id,))
    return workspace_type, business['business_name'], _owner_email(business_id)


def clean_document(data):
    if not isinstance(data, dict) or set(data) - {*GROUPS, 'reference'}:
        raise f.FinanceError('invalid_invoice_document')
    result = {}
    for group, keys in GROUPS.items():
        values = data.get(group, {})
        if not isinstance(values, dict) or set(values) - set(keys):
            raise f.FinanceError('invalid_invoice_document')
        result[group] = {k: f._text(values.get(k), 2000 if k in ('address','instructions') else 254,
                                     k == 'name') or '' for k in keys}
    result['reference'] = f._text(data.get('reference'),254) or ''
    return result


def defaults(business_id, actor_user_id=None):
    f._scope(business_id, actor_user_id)
    branch_id = f.branches.write_branch(business_id, actor_user_id)
    workspace_type, sender_name, sender_email = _workspace_identity(
        business_id, actor_user_id)
    row = db.query_one('SELECT defaults_json FROM finance_invoice_settings WHERE business_id=? AND branch_id=?',
                       (business_id, branch_id))
    if workspace_type == 'PERSONAL':
        # Account → Pribadi is the canonical profile for future personal invoices.
        # Legacy per-branch defaults are still used as a fallback until the customer
        # saves the new personal profile once, so no old contact/payment data disappears.
        profile = account_profiles.get_personal_profile(actor_user_id)
        canonical = account_profiles.has_personal_profile(actor_user_id)
        if row and not canonical:
            values = json.loads(row['defaults_json'])
            sender = values.setdefault('sender', {})
            sender['name'] = sender_name
            sender['email'] = sender_email
            return values
        return {
            'sender': dict(
                name=sender_name,
                address=profile.get('address') or '',
                phone=profile.get('phone') or '',
                email=sender_email,
                tax_id=profile.get('tax_id') or '',
                website=profile.get('website') or '',
            ),
            'payment': dict(
                method=profile.get('payment_method') or '',
                bank=profile.get('payment_bank_name') or '',
                account_number=profile.get('payment_account_number') or '',
                account_holder=profile.get('payment_account_name') or '',
                instructions=profile.get('payment_instructions') or '',
            ),
        }
    if row:
        values = json.loads(row['defaults_json'])
        values.setdefault('sender', {})['email'] = sender_email
        return values
    p = db.query_one('SELECT * FROM business_profiles WHERE business_id=?',(business_id,)) or {}
    return {'sender':dict(name=sender_name,address=p.get('address') or '',
                         phone=p.get('business_phone') or '',email=sender_email,tax_id='',website=''),
            'payment':dict(method='Transfer Bank' if p.get('payment_bank_name') else '',
                          bank=p.get('payment_bank_name') or '',account_number=p.get('payment_account_number') or '',
                          account_holder=p.get('payment_account_name') or '',instructions=p.get('payment_instructions') or '')}


def save_defaults(business_id, data, actor_user_id=None):
    values = clean_document(dict(data,recipient={'name':'-'}))
    workspace_type, sender_name, sender_email = _workspace_identity(
        business_id, actor_user_id)
    values['sender']['email'] = sender_email
    personal_profile = None
    if workspace_type == 'PERSONAL':
        values['sender']['name'] = sender_name
        personal_profile = {
            'phone': values['sender']['phone'],
            'address': values['sender']['address'],
            'tax_id': values['sender']['tax_id'],
            'website': values['sender']['website'],
            'payment_method': values['payment']['method'],
            'payment_bank_name': values['payment']['bank'],
            'payment_account_number': values['payment']['account_number'],
            'payment_account_name': values['payment']['account_holder'],
            'payment_instructions': values['payment']['instructions'],
        }
    elif not values['sender']['address'] or not values['sender']['phone']:
        raise f.FinanceError('invoice_sender_required')
    values = {k:values[k] for k in ('sender','payment')}
    with f._write(business_id,actor_user_id):
        branch_id=f.branches.write_branch(business_id,actor_user_id)
        db.execute('''INSERT INTO finance_invoice_settings (business_id,branch_id,defaults_json,updated_at)
            VALUES (?,?,?,?) ON CONFLICT(business_id,branch_id) DO UPDATE SET
            defaults_json=excluded.defaults_json,updated_at=excluded.updated_at''',
            (business_id,branch_id,json.dumps(values),repo._now()))
        f._audit(business_id,actor_user_id,'FINANCE_INVOICE_SETTINGS_UPDATED',branch_id)
    if personal_profile is not None:
        # Keep Account → Pribadi in sync only after the Finance settings write succeeds.
        account_profiles.save_personal_profile(actor_user_id, personal_profile)


def sync_sender_identity(business_id, name, actor_user_id=None):
    """Update only FUTURE invoice defaults after a business rename; issued invoice snapshots stay frozen."""
    clean_name = f._text(name, 254, True)
    email = _owner_email(business_id)
    f._scope(business_id, actor_user_id)
    rows = db.query_all(
        """SELECT s.branch_id,s.defaults_json
           FROM finance_invoice_settings s
           LEFT JOIN finance_branch_workspaces w
             ON w.business_id=s.business_id AND w.branch_id=s.branch_id
           WHERE s.business_id=? AND COALESCE(w.workspace_type,'BUSINESS')='BUSINESS'""",
        (business_id,))
    # AI-only / non-Finance businesses have nothing to synchronize; renaming the
    # business account must not accidentally require a Finance entitlement.
    if not rows:
        return
    with f._write(business_id, actor_user_id):
        now = repo._now()
        for row in rows:
            values = json.loads(row['defaults_json'])
            sender = values.setdefault('sender', {})
            sender['name'] = clean_name
            sender['email'] = email
            db.execute(
                'UPDATE finance_invoice_settings SET defaults_json=?,updated_at=? '
                'WHERE business_id=? AND branch_id=?',
                (json.dumps(values), now, business_id, row['branch_id']))
        if rows:
            f._audit(business_id, actor_user_id, 'FINANCE_INVOICE_SENDER_IDENTITY_UPDATED', None)


def snapshot(invoice, actor_user_id=None):
    """Legacy fallback is read-only. First correction persists it; never invent past data."""
    if invoice.get('document_snapshot'):
        return json.loads(invoice['document_snapshot'])
    b=db.query_one('SELECT business_name FROM businesses WHERE id=?',(invoice['business_id'],))
    c=f.get_customer(invoice['business_id'],invoice['customer_id'],actor_user_id)
    return clean_document({'sender':{'name':b['business_name']},
                           'recipient':{k:c.get(k) for k in ('name','phone','email')}})


def initial_snapshot(business_id, invoice_id, data, actor_user_id=None):
    invoice=f._invoice(business_id,invoice_id,actor_user_id)
    if data is None:
        data=defaults(business_id,actor_user_id)
        c=f.get_customer(business_id,invoice['customer_id'],actor_user_id)
        data['recipient']={k:c.get(k) for k in ('name','phone','email')}
    doc=clean_document(data)
    db.execute('UPDATE finance_invoices SET document_snapshot=? WHERE business_id=? AND id=?',
               (json.dumps(doc),business_id,invoice_id))


def _inline_customer(business_id, recipient, actor_user_id, key=None):
    matches=[c for c in f.list_customers(business_id,actor_user_id=actor_user_id)
             if c['name'].strip().casefold()==recipient['name'].casefold()]
    if len(matches)>1 or (matches and any(recipient[k] and (matches[0].get(k) or '').casefold()!=recipient[k].casefold() for k in ('phone','email'))):
        raise f.FinanceError('invoice_select_customer')
    if matches:return matches[0]['id']
    return f.create_customer(business_id,recipient['name'],phone=recipient['phone'],email=recipient['email'],
                             actor_user_id=actor_user_id,idempotency_key=key)


def create(business_id, customer_id, data, *, actor_user_id=None, submission_key, **kwargs):
    """Atomic inline recipient + invoice, retry-safe without modifying existing customers."""
    doc=clean_document(data)
    workspace_type, sender_name, sender_email = _workspace_identity(
        business_id, actor_user_id)
    doc['sender']['email'] = sender_email
    if workspace_type == 'PERSONAL':
        doc['sender']['name'] = sender_name
    with f._write(business_id,actor_user_id):
        if workspace_type != 'PERSONAL' and (not doc['sender']['address'] or not doc['sender']['phone']):
            raise f.FinanceError('invoice_sender_required')
        if not customer_id:
            customer_id=_inline_customer(business_id,doc['recipient'],actor_user_id,submission_key)
        return f.create_finance_invoice(business_id,customer_id,actor_user_id=actor_user_id,
            idempotency_key=submission_key,document_data=doc,**kwargs)


def edit(business_id, invoice_id, changes, *, actor_user_id=None, expected_revision=None):
    allowed={'customer_id','issue_date','due_date','currency','notes','items','document_data'}
    if set(changes)-allowed:
        raise f.FinanceError('invalid_invoice_edit')
    with f._write(business_id,actor_user_id):
        old=f._invoice(business_id,invoice_id,actor_user_id)
        if old['status']=='VOID':
            raise f.FinanceError('invoice_unavailable')
        if expected_revision is not None and old['revision']!=expected_revision:
            raise f.FinanceError('invoice_revision_conflict')
        old_items=[{k:x[k] for k in ('description','quantity','unit_price_minor')}
                   for x in f.list_invoice_items(business_id,invoice_id,actor_user_id)]
        before={k:old[k] for k in ('customer_id','issue_date','due_date','currency','notes')}
        before.update(items=old_items,document_data=snapshot(old,actor_user_id))
        after=dict(before,**changes)
        after['document_data']=clean_document(after['document_data'])
        # Sender email is account identity, not a per-invoice editable field. Existing
        # invoice snapshots keep the email they were created with.
        after['document_data']['sender']['email'] = before['document_data']['sender'].get('email','')
        after['issue_date'],after['due_date']=f._period(after['issue_date'],after['due_date'])
        if after['issue_date']>f.business_today(business_id).isoformat():
            raise f.FinanceError('future_date')
        after['currency']=f._currency(after['currency'])
        after['notes']=f._text(after['notes'],4000)
        if not after['customer_id']:
            if old['status'] in ('PARTIALLY_PAID','PAID') or f.list_invoice_payments(business_id,invoice_id,actor_user_id):
                raise f.FinanceError('invoice_financial_locked')
            after['customer_id']=_inline_customer(business_id,after['document_data']['recipient'],actor_user_id)
        if after['customer_id']!=old['customer_id']:
            customer=f.get_customer(business_id,after['customer_id'],actor_user_id)
            if not customer or not customer['is_active']:
                raise f.FinanceError('customer_unavailable')
        items=after['items']
        if not isinstance(items,list) or not 1<=len(items)<=100:
            raise f.FinanceError('invalid_items')
        clean=[];total=0
        for x in items:
            if not isinstance(x,dict) or set(x)!={'description','quantity','unit_price_minor'}:
                raise f.FinanceError('invalid_items')
            d=f._text(x['description'],500,True);q=f._money(x['quantity'],positive=True);p=f._money(x['unit_price_minor'])
            if p<0:raise f.FinanceError('invalid_money_minor')
            total=f._money(total+q*p)
            clean.append(dict(description=d,quantity=q,unit_price_minor=p))
        after['items']=clean
        locked=old['status'] in ('PARTIALLY_PAID','PAID') or bool(f.list_invoice_payments(business_id,invoice_id,actor_user_id))
        if locked and (any(after[k]!=before[k] for k in ('customer_id','currency','issue_date','due_date')) or
                       [(x['quantity'],x['unit_price_minor']) for x in clean]!=
                       [(x['quantity'],x['unit_price_minor']) for x in old_items]):
            raise f.FinanceError('invoice_financial_locked')
        if old['status']!='DRAFT' and total<=0:raise f.FinanceError('empty_invoice_total')
        changed=[k for k in before if before[k]!=after[k]]
        if not changed:return invoice_id
        if 'document_data' in changed:
            changed.remove('document_data')
            for group,keys in GROUPS.items():
                changed.extend(group+'.'+key for key in keys if before['document_data'][group][key]!=after['document_data'][group][key])
            if before['document_data']['reference']!=after['document_data']['reference']:
                changed.append('reference')
        revision=old['revision']+1;now=repo._now()
        db.execute('''UPDATE finance_invoices SET customer_id=?,issue_date=?,due_date=?,currency=?,notes=?,
            document_snapshot=?,revision=?,updated_at=? WHERE business_id=? AND id=?''',
            (after['customer_id'],after['issue_date'],after['due_date'],after['currency'],after['notes'],
             json.dumps(after['document_data']),revision,now,business_id,invoice_id))
        if clean!=old_items:
            if locked:
                rows=f.list_invoice_items(business_id,invoice_id,actor_user_id)
                for row,item in zip(rows,clean):
                    db.execute('UPDATE finance_invoice_items SET description=? WHERE business_id=? AND invoice_id=? AND id=?',
                               (item['description'],business_id,invoice_id,row['id']))
            else:
                db.execute('DELETE FROM finance_invoice_items WHERE business_id=? AND invoice_id=?',(business_id,invoice_id))
                for item in clean:
                    db.execute('INSERT INTO finance_invoice_items (business_id,invoice_id,description,quantity,unit_price_minor,created_at) VALUES (?,?,?,?,?,?)',
                               (business_id,invoice_id,item['description'],item['quantity'],item['unit_price_minor'],now))
        db.execute('''INSERT INTO finance_invoice_revisions
            (business_id,invoice_id,revision,actor_user_id,created_at,fields_changed,before_json,after_json)
            VALUES (?,?,?,?,?,?,?,?)''',(business_id,invoice_id,revision,actor_user_id,now,
                                        json.dumps(changed),json.dumps(before),json.dumps(after)))
        repo.write_audit(actor_user_id,business_id,'FINANCE_INVOICE_EDITED',
                         json.dumps(dict(invoice_id=invoice_id,revision=revision,fields_changed=changed)))
        return invoice_id
