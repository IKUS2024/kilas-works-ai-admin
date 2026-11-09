"""Current quotation gate + historical order/proof rehearsal on disposable PostgreSQL."""
import io,json,os,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image
from flask import Flask
from werkzeug.datastructures import FileStorage
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
url=urlsplit(os.environ.get('DATABASE_URL',''))
if url.hostname not in ('127.0.0.1','localhost') or url.path!='/creative_checkout_qa':
    raise RuntimeError('disposable_creative_checkout_database_required')
import db,repo,creative_orders as orders,payment_service,projects_repo
app=Flask('creative-checkout-native');app.secret_key='synthetic-native-test-only'
db.init_schema()
owner=repo.create_user('checkout-native-'+__import__('uuid').uuid4().hex+'@example.test','synthetic-password-hash')
# First exercise unresolved public prices: they must not become automatic invoices.
# Counts include every financial/project table this path can create, not just invoices.
def counts():
    return {table: db.query_one(f'SELECT COUNT(*) n FROM {table}')['n']
            for table in ('projects', 'invoices', 'payments', 'project_files')}
before_quote = counts()
quote_packages = sum(orders.offer(key)['quotation_required'] for key in orders.CATALOG['packages'])
with app.app_context():
    for key, spec in orders.CATALOG['packages'].items():
        if not orders.offer(key)['quotation_required']:
            continue
        try:
            orders.create_order(owner, key, {'order_token': orders.checkout_token(owner, key)})
        except ValueError as exc:
            assert 'quotation tertulis' in str(exc), str(exc)
        else:
            raise AssertionError('current quote-only offer created an invoice: ' + key)
assert counts() == before_quote
current_fixed_packages = 0
with app.app_context():
    for key, spec in orders.CATALOG['packages'].items():
        if orders.offer(key)['quotation_required']:
            continue
        form = {'order_token': orders.checkout_token(owner, key), 'name': 'Synthetic Current QA',
                'whatsapp': '081234567890', 'event_date': '2099-12-01', 'location': 'Synthetic venue',
                'brand': 'Synthetic brand', 'social_account': '@synthetic'}
        invoice_id = orders.create_order(owner, key, form)
        assert payment_service.get_invoice(invoice_id)['amount'] == spec['amount']
        assert orders.create_order(owner, key, form) == invoice_id
        current_fixed_packages += 1
# The remaining concurrency/security scenarios deliberately rehearse saved historical
# purchases, independent of today's fixed/quotation rates and new public package cards.
orders.CATALOG = json.loads(Path(__file__).with_name('creative_historical_catalog.json').read_text())
with app.app_context():
    for key,spec in orders.CATALOG['packages'].items():
        for addon in (orders.CATALOG['addons'] if spec['service']=='social' else ['none']):
            form={'order_token':orders.checkout_token(owner,key),'name':'Synthetic Native QA','whatsapp':'081234567890','event_date':'2099-12-01','location':'Synthetic venue','brand':'Synthetic brand','social_account':'@synthetic','addon':addon}
            invoice=orders.create_order(owner,key,form)
            assert payment_service.get_invoice(invoice)['amount']==orders.offer(key,addon)['total']
    token=orders.checkout_token(owner,'creative_event_basic')
form=dict(form,order_token=token,addon='none')
def create():
    try:
        with app.app_context():return orders.create_order(owner,'creative_event_basic',form)
    finally:
        db.get_connection().close();db._local.conn=None
with ThreadPoolExecutor(2) as pool:ids=list(pool.map(lambda _:create(),range(2)))
assert ids[0]==ids[1]
image=io.BytesIO();Image.new('RGB',(32,32),'white').save(image,'PNG')
def upload():
    try:
        with app.app_context():orders.submit_proof(ids[0],owner,FileStorage(stream=io.BytesIO(image.getvalue()),filename='synthetic.png',content_type='image/png'))
    finally:
        db.get_connection().close();db._local.conn=None
with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:upload(),range(2)))
payment=payment_service.get_payment_for_invoice(ids[0]);invoice=payment_service.get_invoice(ids[0])
assert payment['status']=='UNDER_REVIEW' and invoice['status']=='ISSUED'
assert projects_repo.get_project(invoice['project_id'])['status']=='PAYMENT_PENDING'
assert db.query_one('SELECT COUNT(*) n FROM project_files WHERE project_id=?',(invoice['project_id'],))['n']==1
assert bytes(db.query_one('SELECT content FROM project_files WHERE id=?',(payment['proof_file_id'],))['content']).startswith(b'\xff\xd8')
db.get_connection().close();db._local.conn=None
assert payment_service.get_payment_for_invoice(ids[0])['status']=='UNDER_REVIEW'
# Cancellation holds the same owner/row locks while concurrent upload and admin
# verification attempt to run. Neither may revive the committed closed order.
from threading import Event
with app.app_context():
    form['order_token']=orders.checkout_token(owner,'creative_event_basic')
    closed_invoice=orders.create_order(owner,'creative_event_basic',form)
closed_project=payment_service.get_invoice(closed_invoice)['project_id']
closed_payment=payment_service.get_payment_for_invoice(closed_invoice)['id']
admin=repo.create_user('checkout-admin-'+__import__('uuid').uuid4().hex+'@example.test','synthetic-password-hash',role='KILAS_ADMIN')
locked=Event();release=Event();started_upload=Event();started_verify=Event()
def cancel():
    try:
        with db.app_purchase_transaction(None,owner):
            orders.lock_payment(closed_invoice)
            assert projects_repo.customer_can_cancel(projects_repo.get_project(closed_project))
            db.execute("UPDATE projects SET status='CANCELLED' WHERE id=?",(closed_project,))
            locked.set()
            assert release.wait(10)
    finally:
        db.get_connection().close();db._local.conn=None
def closed_attempt(kind):
    try:
        with app.app_context():
            if kind=='upload':
                started_upload.set()
                orders.submit_proof(closed_invoice,owner,FileStorage(stream=io.BytesIO(image.getvalue()),filename='synthetic.png',content_type='image/png'))
            else:
                started_verify.set()
                payment_service.verify_payment(closed_payment,None,admin)
        raise AssertionError('closed order accepted mutation')
    except ValueError:
        return 'blocked'
    finally:
        db.get_connection().close();db._local.conn=None
with ThreadPoolExecutor(3) as pool:
    cancellation=pool.submit(cancel)
    assert locked.wait(10)
    attempt_upload=pool.submit(closed_attempt,'upload');attempt_verify=pool.submit(closed_attempt,'verify')
    assert started_upload.wait(10) and started_verify.wait(10)
    release.set();cancellation.result()
    assert attempt_upload.result() == attempt_verify.result() == 'blocked'
assert projects_repo.get_project(closed_project)['status']=='CANCELLED'
assert payment_service.get_invoice(closed_invoice)['status']=='ISSUED'
assert payment_service.get_payment(closed_payment)['status']=='PAYMENT_PENDING'
assert db.query_one('SELECT COUNT(*) n FROM project_files WHERE project_id=?',(closed_project,))['n']==0
print(json.dumps({'result':'PASS','postgres_version':db.query_one('SHOW server_version')['server_version'],'quotation_gate_packages':quote_packages,'current_fixed_packages':current_fixed_packages,'price_variations':15,'purchase_scope':'historical fixed-price checkout','concurrent_checkout_and_upload':'PASS','persistent_private_bytea':'PASS','cancel_upload_verify_race':'PASS','paid_transitions':0}))
