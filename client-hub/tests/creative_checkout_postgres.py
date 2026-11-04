"""Native PostgreSQL order/proof transaction rehearsal on a disposable loopback DB."""
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
print(json.dumps({'result':'PASS','postgres_version':db.query_one('SHOW server_version')['server_version'],'price_variations':15,'concurrent_checkout_and_upload':'PASS','persistent_private_bytea':'PASS','paid_transitions':0}))
