"""CI mobile certification against the guarded disposable Phase 7 harness only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
BASE='http://127.0.0.1:8768'
OUT=Path('/tmp/kilas-phase7-browser-qa');OUT.mkdir(parents=True,exist_ok=True)

LAYOUT_ISSUES=[]

def fits(page):
    details=page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
        elements:[...document.querySelectorAll('body *')].filter(e => {
            const r=e.getBoundingClientRect();return r.width>0 && (r.right>innerWidth || r.left<0);
        }).slice(0,30).map(e=>({tag:e.tagName,cls:e.className,id:e.id,
            left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,
            width:e.getBoundingClientRect().width,overflow:getComputedStyle(e).overflowX}))})""")
    if details['scroll']>details['width']:
        LAYOUT_ISSUES.append(dict(url=page.url,**details))
        (OUT/'layout-issues.json').write_text(json.dumps(LAYOUT_ISSUES,indent=2))

def shot(page,name):
    fits(page);page.screenshot(path=str(OUT/name),full_page=True)

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':390,'height':844})
        owner=context.new_page();errors=[]
        owner.on('pageerror',lambda error:errors.append(str(error)))
        data=context.request.get(BASE+'/dev/health').json()
        bid,target,branch=data['source'],data['target'],data['branch']
        base=f'{BASE}/business/{bid}/finance-bridge'
        owner.goto(BASE+'/dev/standalone',wait_until='networkidle')
        assert owner.url.endswith(f"/business/{data['standalone']}/finance")
        shot(owner,'01_standalone_zero_bridge.png')
        for tail in ('accounts','transactions','invoices','operations','reports','settings','assistant'):
            response=owner.goto(f"{BASE}/business/{data['standalone']}/finance/{tail}",wait_until='networkidle')
            assert response.status==200,(tail,response.status)
            fits(owner)
        owner.goto(BASE+'/dev/owner',wait_until='networkidle')
        expect(owner.locator('[data-finance-bridge]')).to_be_visible()
        owner.get_by_role('link',name='Pengaturan koneksi Finance',exact=True).click()
        owner.get_by_label('Bisnis dan cabang Finance').select_option(f'{target}:{branch}')
        owner.get_by_role('checkbox').check()
        owner.get_by_role('button',name='Simpan koneksi',exact=True).click()
        expect(owner.get_by_text(f'Finance #{target} · Cabang #{branch} · Aktif',exact=True)).to_be_visible()
        shot(owner,'02_explicit_mapping.png')
        owner.goto(base+'/customers/'+data['cid'],wait_until='networkidle')
        owner.get_by_label('Pilih Customer Finance').select_option('new')
        owner.get_by_label('Nama customer baru').fill('Customer reviewed in mobile')
        owner.get_by_role('checkbox').check()
        owner.get_by_role('button',name='Hubungkan customer',exact=True).click()
        expect(owner.get_by_text('Terhubung:',exact=False)).to_be_visible()
        shot(owner,'03_explicit_customer.png')
        job=base+'/jobs/'+data['jid']
        owner.goto(job,wait_until='networkidle')
        owner.get_by_label('Mata uang',exact=True).fill('IDR')
        owner.get_by_label('Tanggal invoice',exact=True).fill('2026-09-01')
        owner.get_by_label('Jatuh tempo',exact=True).fill('2026-09-30')
        owner.get_by_label('Deskripsi 1',exact=True).fill('Owner supplied service')
        owner.get_by_label('Jumlah 1',exact=True).fill('2')
        owner.get_by_label('Harga satuan 1',exact=True).fill('500')
        owner.get_by_role('checkbox').check()
        shot(owner,'04_owner_review.png')
        owner.get_by_role('button',name='Buat draft di Finance',exact=True).click()
        expect(owner.get_by_text('Status: DRAFT',exact=True)).to_be_visible()
        shot(owner,'05_finance_draft_readback.png')
        owner.get_by_role('link',name='Buka invoice di Finance',exact=True).click()
        assert f'/business/{target}/finance/invoices/' in owner.url
        shot(owner,'06_authoritative_finance_invoice.png')
        # Synthetic test fixture posts exclusively through authoritative Finance
        # issue/payment APIs; there is no Bridge payment endpoint in the product.
        owner.goto(base,wait_until='networkidle')
        csrf=owner.locator('input[name="csrf_token"]').input_value()
        response=context.request.post(BASE+'/dev/payment',form={'csrf_token':csrf})
        assert response.ok,response.text()
        owner.goto(job,wait_until='networkidle')
        expect(owner.get_by_text('Status: PARTIALLY_PAID',exact=True)).to_be_visible()
        shot(owner,'07_authoritative_payment_readback.png')
        foreign=browser.new_context(viewport={'width':390,'height':844})
        other=foreign.new_page();other.goto(BASE+'/dev/foreign')
        assert other.goto(base).status==404
        assert other.goto(job).status==404
        owner.goto(base,wait_until='networkidle')
        csrf=owner.locator('input[name="csrf_token"]').input_value()
        assert context.request.post(BASE+'/dev/expire',form={'csrf_token':csrf}).ok
        owner.goto(job,wait_until='networkidle')
        expect(owner.get_by_text('Status: PARTIALLY_PAID',exact=True)).to_be_visible()
        shot(owner,'08_expired_history_readable.png')
        owner.goto(base,wait_until='networkidle')
        owner.get_by_label('Bisnis dan cabang Finance').select_option(f'{target}:{branch}')
        owner.get_by_role('checkbox').check()
        owner.get_by_role('button',name='Simpan koneksi',exact=True).click()
        expect(owner.get_by_text('Aksi belum selesai',exact=True)).to_be_visible()
        shot(owner,'09_expired_write_blocked.png')
        assert not errors,errors
        assert not LAYOUT_ISSUES,json.dumps(LAYOUT_ISSUES)
        (OUT/'results.json').write_text(json.dumps(dict(passed=True,viewport='390x844',
            checks=['standalone zero bridge','Finance-only pages','explicit mapping','explicit customer',
                    'owner reviewed draft','Finance detail','authoritative partial payment','foreign tenant',
                    'expired read','expired write blocked','no horizontal overflow','no JS errors']),indent=2))
        print('Phase 7 mobile browser QA PASS')
        browser.close()

if __name__=='__main__':main()
