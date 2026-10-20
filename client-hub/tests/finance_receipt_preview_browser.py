"""Actual shared receipt tile, local synthetic photos only; no OCR/provider calls."""
import hashlib,io,os,threading
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_finance_expense_entries as fixture
import db,finance_service as f,finance_branches as branches,finance_expense_entries as expense

def picture(kind,color,size):
 raw=io.BytesIO();Image.new('RGB',size,color).save(raw,kind);return raw.getvalue()
RED=picture('JPEG','red',(37,29));BLUE=picture('PNG','blue',(73,41));WEBP=picture('WEBP','green',(51,31))

def main():
 case=fixture.ExpenseEntryTests();case.setUp();saved={}
 for scope,branch,account,key in (('BUSINESS',case.branch,case.a,'a'),('PERSONAL',case.personal,case.pa,'b')):
  with branches.scope(case.b,branch,case.uid):
   category=next(c['id'] for c in f.list_categories(case.b,'EXPENSE',include_children=True,actor_user_id=case.uid) if not f.list_category_children(case.b,c['id'],actor_user_id=case.uid));receipt=case.photo();tx=expense.save(case.b,case.uid,amount_minor=12345,account_id=account,category_id=category,occurred_on='2025-01-01',currency='IDR',receipt=receipt,submission_key=key*32);saved[scope]=(tx,receipt['digest'])
 originals=[dict(r) for r in db.query_all('SELECT * FROM finance_expense_receipts ORDER BY transaction_id')]
 server=make_server('127.0.0.1',0,fixture.fixture.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';cookie=case.client.get_cookie('session');out=Path('/tmp/kilas-finance-receipt-preview');out.mkdir(exist_ok=True)
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM'),args=['--no-sandbox'])
   widths_requested=tuple(map(int,os.environ.get('KILAS_QA_WIDTHS','320,390,768,1440').split(',')))
   for mode,widths in (('ADD',widths_requested),('EDIT',tuple(w for w in (390,1440) if w in widths_requested))):
    for width in widths:
     for scope,branch,account in (('BUSINESS',case.branch,case.a),('PERSONAL',case.personal,case.pa)):
      ctx=browser.new_context(viewport={'width':width,'height':950},is_mobile=width<500,has_touch=width<500);ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);page=ctx.new_page();page.set_default_timeout(5000);errors=[];choosers=[];posts=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('filechooser',lambda e:choosers.append(e));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None);page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
      page.add_init_script("""const create=URL.createObjectURL,revoke=URL.revokeObjectURL;window.__photoURLs={created:[],revoked:[]};URL.createObjectURL=function(v){const u=create.call(this,v);__photoURLs.created.push(u);return u};URL.revokeObjectURL=function(u){__photoURLs.revoked.push(u);return revoke.call(this,u)};""")
      base=origin+case.url+f'?branch_id={branch}&view=transactions&direction=EXPENSE'
      if mode=='ADD':page.goto(base);page.locator('[data-transaction-direction=EXPENSE]').click();container=page.locator('#add-expense-dialog')
      else:page.goto(origin+case.url+f'/transactions/{saved[scope][0]}/edit?branch_id={branch}');container=page.locator('.expense-edit')
      form=container.locator('[data-expense-form]');upload=form.locator('[data-expense-photo]');clear=form.locator('[data-expense-photo-clear]');preview=form.locator('[data-expense-photo-preview]');name=form.locator('[data-expense-photo-name]');error=form.locator('[data-expense-photo-error]')
      form.locator('[name=notes]').fill('Keep these other fields');form.locator('[name=counterparty_name]').fill('Synthetic optional payee');form.locator('[name=amount]').fill('123.45');form.locator('[name=occurred_on]').fill('2025-01-01');form.locator('[name=account_id]').select_option(str(account))
      state=lambda:form.evaluate("(f)=>Array.from(f.elements).filter(e=>e.name&&e.type!=='file').map(e=>[e.name,e.value,e.checked])")
      fields=state()
      def choose(raw,filename,mime,dimensions):
       upload.set_input_files({'name':filename,'mimeType':mime,'buffer':raw});expect(preview).to_be_visible();page.wait_for_function("(v)=>{const e=document.querySelector('[data-expense-photo-preview]');return e?.naturalWidth===v[0]&&e.naturalHeight===v[1]}",arg=dimensions);assert name.text_content()==filename;assert preview.get_attribute('src').startswith('blob:');assert clear.is_visible();assert error.is_hidden()
      choose(RED,'receipt <script>.jpg','image/jpeg',[37,29]);assert name.locator('script').count()==0;first=preview.get_attribute('src')
      choose(BLUE,'replacement.png','image/png',[73,41]);assert page.evaluate('(u)=>__photoURLs.revoked.includes(u)',first)
      page.screenshot(path=str(out/f'{mode.lower()}-{scope.lower()}-{width}.png'))
      cross=clear.bounding_box();assert abs(cross['width']-cross['height'])<1;box=preview.bounding_box();tile=form.locator('.expense-camera').bounding_box();assert box['x']>=tile['x'] and box['x']+box['width']<=tile['x']+tile['width']+1
      upload.evaluate("e=>e.setCustomValidity('Synthetic stale validity')")
      if width<500:clear.tap()
      else:clear.press('Enter')
      assert upload.evaluate('(e)=>e.files.length')==0;assert upload.evaluate('(e)=>e.validity.valid');assert preview.is_hidden();assert preview.get_attribute('src') is None;assert clear.is_hidden();assert not name.text_content();assert state()==fields;assert not choosers;assert not posts
      choose(BLUE,'replacement.png','image/png',[73,41]);clear.press('Space');assert upload.evaluate('(e)=>e.files.length')==0;choose(WEBP,'receipt.webp','image/webp',[51,31]);clear.click();assert state()==fields
      upload.set_input_files({'name':'invalid.jpg','mimeType':'image/jpeg','buffer':b'<svg/>'});expect(error).to_be_visible();assert upload.evaluate('(e)=>e.files.length')==0;assert preview.is_hidden();assert 'JPG' in error.text_content()
      choose(RED,'receipt <script>.jpg','image/jpeg',[37,29])
      if mode=='ADD':
       container.locator('[data-finance-close=add-expense-dialog]').click();expect(container).not_to_be_visible();page.locator('[data-transaction-direction=EXPENSE]').click();expect(container).to_be_visible();assert upload.evaluate('(e)=>e.files.length')==0;assert preview.is_hidden();assert state()==fields
      else:
       assert container.get_by_role('link',name='View receipt',exact=True).count()==1
       original_url=container.get_by_role('link',name='View receipt',exact=True).get_attribute('href');assert page.request.get(origin+original_url).status==200
       clear.click();assert container.get_by_role('link',name='View receipt',exact=True).get_attribute('href')==original_url
      if mode=='ADD' and scope=='BUSINESS' and width==320:
       # Delay real12-byte reads, remove/replace, then deliver stale completion.
       page.evaluate("""()=>{window.__nativeArrayBuffer=Blob.prototype.arrayBuffer;window.__headers=[];Blob.prototype.arrayBuffer=function(){const result=__nativeArrayBuffer.call(this);return this.size===12?result.then(v=>new Promise(resolve=>__headers.push(()=>resolve(v)))):result}}""")
       upload.set_input_files({'name':'late.jpg','mimeType':'image/jpeg','buffer':RED});page.wait_for_function('__headers.length===1');clear.click();page.evaluate('__headers.shift()()');page.wait_for_timeout(30);assert preview.is_hidden();assert upload.evaluate('(e)=>e.files.length')==0
       upload.set_input_files({'name':'old.jpg','mimeType':'image/jpeg','buffer':RED});page.wait_for_function('__headers.length===1');upload.set_input_files({'name':'new.png','mimeType':'image/png','buffer':BLUE});page.wait_for_function('__headers.length===2');page.evaluate('__headers.shift()()');page.wait_for_timeout(30);assert preview.is_hidden();page.evaluate('__headers.shift()()');expect(preview).to_be_visible();assert preview.evaluate('(e)=>e.naturalWidth')==73;page.evaluate('()=>{Blob.prototype.arrayBuffer=__nativeArrayBuffer;}');clear.click()
       # Hold the actual image callback, clear, then deliver its stale handler.
       page.evaluate("""()=>{window.__NativeImage=Image;window.__loads=[];window.Image=function(){const image=new __NativeImage;let handler=null;Object.defineProperty(image,'onload',{configurable:true,get(){return handler},set(fn){handler=fn;if(fn)__loads.push({image,fn})}});return image}}""")
       upload.set_input_files({'name':'late-image.jpg','mimeType':'image/jpeg','buffer':RED});page.wait_for_function('__loads.length===1&&__loads[0].image.naturalWidth===37');clear.click();page.evaluate('__loads[0].fn()');assert preview.is_hidden();assert upload.evaluate('(e)=>e.files.length')==0;page.evaluate('()=>{window.Image=__NativeImage;}')
       choose(RED,'reset.jpg','image/jpeg',[37,29]);form.evaluate('(e)=>e.reset()');assert upload.evaluate('(e)=>e.files.length')==0;assert preview.is_hidden()
       form.locator('[name=notes]').fill('Save without removed receipt');form.locator('[name=amount]').fill('123.45');form.locator('[name=occurred_on]').fill('2025-01-01');form.locator('[name=account_id]').select_option(str(account))
       with branches.scope(case.b,branch,case.uid):
        roots=f.list_categories(case.b,'EXPENSE',actor_user_id=case.uid);root=next(v for v in roots if f.list_category_children(case.b,v['id'],actor_user_id=case.uid));leaf=f.list_category_children(case.b,root['id'],actor_user_id=case.uid)[0]
       single=form.locator('[data-expense-single]');single.locator('[data-expense-cascade]').click();panel=single.locator('[data-expense-cascade-panel]');root_text=single.locator('[data-expense-parent] option[value="'+str(root['id'])+'"]').text_content();group=panel.locator('[data-expense-group="'+str(root['id'])+'"]');group.locator('summary').click() if not group.evaluate('(e)=>e.open') else None;leaf_text=single.locator('[data-expense-child] option[value="'+str(leaf['id'])+'"]').text_content();group.locator('[data-expense-choice="'+str(leaf['id'])+'"]').click()
       choose(RED,'removed-before-save.jpg','image/jpeg',[37,29]);clear.click()
       with page.expect_navigation():container.get_by_role('button',name='Save',exact=True).click()
       tx=db.query_one('SELECT * FROM finance_transactions ORDER BY id DESC LIMIT 1');assert tx['notes']=='Save without removed receipt';assert db.query_one('SELECT transaction_id FROM finance_expense_receipts WHERE transaction_id=?',(tx['id'],)) is None
       print('PASS delayed header/image fencing, reset, actual Save after removal has no receipt',flush=True)
      else:
       choose(RED,'pagehide.jpg','image/jpeg',[37,29]);page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide'))");assert upload.evaluate('(e)=>e.files.length')==0;assert preview.is_hidden()
      assert not errors,errors;assert not choosers;assert not any('/receipts/analyze' in u for u in posts);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');assert page.evaluate('__photoURLs.created.every(u=>__photoURLs.revoked.includes(u))')
      print(f'PASS {mode} {scope} {width}: native image preview/replace/remove/reselect, other fields, touch/keyboard, cleanup/no OCR',flush=True);ctx.close()
   browser.close()
  assert [dict(r) for r in db.query_all('SELECT * FROM finance_expense_receipts ORDER BY transaction_id')]==originals
  print('PASS existing saved receipts remain byte-identical in both scopes',flush=True)
 finally:server.shutdown();case.doCleanups()
if __name__=='__main__':main()
