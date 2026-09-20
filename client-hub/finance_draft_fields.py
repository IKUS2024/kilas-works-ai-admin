"""Finance domain field contracts shared by Assistant and manual route validation."""
CUSTOMER = ('name', 'phone', 'email', 'notes')
TRANSACTION = ('direction', 'account_id', 'amount', 'occurred_on', 'category_id',
               'description', 'project_id', 'customer_id', 'counterparty_name')
RECURRING = ('name', 'account_id', 'amount', 'category_id', 'cadence', 'next_due_on',
             'end_on', 'project_id', 'counterparty_name', 'description')
INVOICE = ('customer_id', 'issue_date', 'due_date', 'currency', 'items', 'notes')
LABELS = {'name':'Nama customer', 'phone':'Nomor telepon', 'email':'Email', 'notes':'Catatan'}

CUSTOMER_LIMITS = {'name':160,'phone':64,'email':254,'notes':4000}

def customer_values(values):
    import finance_service as f
    return tuple(f._text(values.get(k),CUSTOMER_LIMITS[k],k=='name') for k in CUSTOMER)
