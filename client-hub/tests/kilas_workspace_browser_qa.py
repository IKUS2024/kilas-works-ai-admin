"""Real route UI regression at five viewports, against isolated fixtures only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
BASE='http://127.0.0.1:8770'
OUT=Path('/tmp/kilas-phase9-browser-qa'); OUT.mkdir(exist_ok=True)
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for width,height in [(360,800),(390,844),(430,932),(820,1180),(1440,1000)]:
        context=browser.new_context(viewport={'width':width,'height':height})
        page=context.new_page(); errors=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        data=context.request.get(BASE+'/dev/health').json()
        def visit(path,name):
            response=page.goto(BASE+path,wait_until='networkidle')
            assert response.status==200,(path,response.status)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,path)
            page.screenshot(path=str(OUT/f'{width}-{name}.png'),full_page=True)
            results.append(dict(width=width,page=name,status=response.status))
        for persona,expected in [('new',['Home','More']),('ai',['Home','Inbox','Customers','Jobs','More']),
                                 ('finance',['Home','Finance','More']),('full',['Home','Inbox','Customers','Jobs','Finance','More'])]:
            visit('/dev/persona/'+persona,persona+'-home')
            assert page.locator('.kw-primary a').all_text_contents() and [s.strip() for s in page.locator('.kw-primary a>span:last-child').all_text_contents()]==expected
            expect(page.locator('.kw-primary [aria-current]')).to_have_count(1)
        source,target=data['source'],data['target']
        for path,name in [('/workspace/more','more'),('/workspace/go/setup','onboarding'),
            (f'/workspace/go/customers?business_id={source}','customers'),
            (f'/business/{source}/customers/{data["customer"]}','customer'),
            (f'/workspace/go/jobs?business_id={source}','jobs'),
            (f'/business/{source}/jobs/{data["job"]}','job'),
            (f'/workspace/go/inbox?business_id={source}','inbox'),
            (f'/business/{target}/finance','finance'),
            (f'/business/{target}/finance?view=accounts','accounts'),
            (f'/business/{target}/finance?view=transactions','transactions'),
            (f'/business/{target}/finance/receivables?section=invoices','invoices'),
            (f'/business/{target}/finance/operations','bills'),
            (f'/business/{target}/finance/budget','budget'),
            (f'/business/{target}/finance/reports','reports'),
            (f'/business/{target}/finance/bank-imports','bank'),
            (f'/business/{target}/finance/assistant','finance-ai'),
            ('/workspace/go/services','services'),('/workspace/go/projects','projects'),
            ('/workspace/go/talent','talent'),('/workspace/go/account','account')]:
            visit(path,name)
        # Switch product from Finance without a routing dead end.
        visit(f'/workspace/go/finance?business_id={target}','finance-selector')
        page.get_by_role('navigation',name='Navigasi utama').get_by_text('Home',exact=True).click()
        expect(page.get_by_role('heading',name='Selamat datang,',exact=False)).to_be_visible()
        # Skip link is reachable by keyboard and has visible focus.
        page.keyboard.press('Control+Home'); page.reload();page.keyboard.press('Tab')
        expect(page.locator('.kw-skip')).to_be_focused()
        for path,name in [('/dev/persona/admin','admin'),('/admin/search','admin-search'),
                          ('/admin/projects','admin-projects'),('/admin/payments','admin-payments'),
                          ('/admin/talent','admin-talent'),('/admin/ai-usage','admin-ai')]:
            visit(path,name)
        assert not errors,errors
        context.close()
    browser.close()
(OUT/'results.json').write_text(json.dumps(results,indent=2))
print(f'Phase 9 browser PASS: {len(results)} responsive page visits; package navigation, focus, no overflow or JS errors')
