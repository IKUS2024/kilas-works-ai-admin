"""Real mobile Chromium, actual routes/storage, synthetic model on disposable loopback."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
BASE = os.environ.get('KILAS_PUBLIC_CHAT_QA_BASE','http://127.0.0.1:8766').rstrip('/')
if urlsplit(BASE).hostname not in ('127.0.0.1','localhost'):
    raise SystemExit('Disposable loopback only')
OUT = Path(os.environ.get('KILAS_PUBLIC_CHAT_QA_OUT','/tmp/kilas-phase5-browser-qa'))
OUT.mkdir(parents=True,exist_ok=True)


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'


def public_link(owner, bid):
    owner.goto(BASE+'/dev/owner/'+str(bid),wait_until='networkidle')
    share = owner.locator('[data-web-share]').first
    expect(share).to_be_visible()
    response = owner.context.request.post(BASE+share.get_attribute('data-url'),
        headers={'X-CSRF-Token':share.get_attribute('data-csrf'),'Content-Type':'application/json'},data={})
    assert response.ok, response.text()
    return BASE+response.json()['path']


def send(page, text):
    expect(page.locator('#web-message')).to_be_enabled()
    page.locator('#web-message').fill(text)
    page.get_by_role('button',name='Kirim',exact=True).click()
    expect(page.locator('[data-status]')).to_have_text('Pesan tersimpan.',timeout=15000)


def inbox(owner, bid):
    owner.goto(BASE+f'/business/{bid}/inbox?channel=web',wait_until='networkidle')
    owner.locator('a.web-conversation').first.click()
    expect(owner.locator('[data-playbook-context]')).to_be_visible()
    fits(owner)


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        errors=[]
        def page():
            context=browser.new_context(viewport={'width':390,'height':844})
            result=context.new_page()
            result.on('pageerror',lambda error:errors.append(str(error)))
            return result
        owner=page();visitor=page();other=page();booking=page();finance=page()
        finance.goto(BASE+'/dev/finance',wait_until='networkidle')
        expect(finance.locator('.finance-entry-shell')).to_be_visible()
        finance_before=finance.screenshot(path=str(OUT/'01_finance_before.png'),full_page=True)
        visitor.goto(public_link(owner,7),wait_until='networkidle')
        send(visitor,'Mau kirim 20 kg baju dari Guangzhou ke Tangerang')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(1,timeout=10000)
        reply=visitor.locator('.web-bubble.assistant').inner_text()
        assert 'volume' in reply and all(word not in reply for word in ('berat','asal','tujuan','jenis barang'))
        fits(visitor);visitor.screenshot(path=str(OUT/'02_logistics_missing.png'),full_page=True)
        inbox(owner,7)
        panel=owner.locator('[data-linked-jobs]')
        expect(panel.locator('a.client-item')).to_have_count(1)
        for fact in ('baju','20 kg','Guangzhou','Tangerang','Masih dibutuhkan'):
            assert fact in panel.inner_text()
        job_url=BASE+panel.locator('a.client-item').get_attribute('href')
        inbox_url=owner.url
        owner.screenshot(path=str(OUT/'03_inbox_known_missing.png'),full_page=True)
        send(visitor,'Volumenya 0.2 m3')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(2,timeout=10000)
        owner.reload(wait_until='networkidle')
        expect(owner.locator('[data-linked-jobs] a.client-item')).to_have_count(1)
        assert BASE+owner.locator('[data-linked-jobs] a.client-item').get_attribute('href') == job_url
        assert '0.2 m³' in owner.locator('[data-playbook-context]').inner_text()
        assert 'Siap ditawarkan' in owner.locator('[data-linked-jobs]').inner_text()
        owner.goto(job_url,wait_until='networkidle')
        customer_path=owner.locator('[data-job-customer]').get_attribute('href')
        version=owner.locator('[name=version]').input_value()
        fits(owner);owner.screenshot(path=str(OUT/'04_same_job_ready.png'),full_page=True)
        owner.goto(inbox_url,wait_until='networkidle')
        owner.get_by_role('button',name='Ambil alih',exact=True).click()
        expect(owner.locator('#web-owner-message')).to_be_enabled(timeout=10000)
        send(visitor,'Koreksi asalnya Shanghai')
        owner.goto(job_url,wait_until='networkidle')
        assert owner.locator('[name=version]').input_value()==version
        expect(owner.locator('#field-origin')).to_have_value('Guangzhou')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(2)
        owner.get_by_label('Judul',exact=True).fill('Pengiriman ditangani tim')
        owner.get_by_role('button',name='Simpan perubahan',exact=True).click()
        expect(owner.get_by_text('Data tersimpan.',exact=True)).to_be_visible()
        owner.screenshot(path=str(OUT/'05_human_manual_edit.png'),full_page=True)

        booking.goto(public_link(other,8),wait_until='networkidle')
        send(booking,'Mau potong rambut besok jam 14.00')
        expect(booking.locator('.web-bubble.assistant')).to_have_count(1,timeout=10000)
        assert 'Boleh informasikan' not in booking.locator('.web-bubble.assistant').inner_text()
        assert 'belum ada pesanan atau booking yang dikonfirmasi' in booking.locator('.web-bubble.assistant').inner_text()
        inbox(other,8)
        assert 'potong rambut' in other.locator('[data-linked-jobs]').inner_text()
        assert 'besok' in other.locator('[data-linked-jobs]').inner_text()
        assert '14.00' in other.locator('[data-linked-jobs]').inner_text()
        other.screenshot(path=str(OUT/'06_booking_known_time.png'),full_page=True)
        for target in (job_url,job_url.replace('/business/7/','/business/8/'),BASE+customer_path,inbox_url):
            assert other.goto(target,wait_until='domcontentloaded').status==404
        response=other.context.request.post(job_url.replace('/business/7/','/business/8/'),
                                             form={'csrf_token':'csrf-test','title':'forged'})
        assert response.status==404
        owner.goto(job_url,wait_until='networkidle')
        expect(owner.get_by_label('Judul',exact=True)).to_have_value('Pengiriman ditangani tim')
        finance.goto(job_url,wait_until='networkidle')
        assert urlsplit(finance.url).path=='/products/finance'
        assert finance.screenshot(path=str(OUT/'07_finance_after.png'),full_page=True)==finance_before
        assert not errors,errors
        browser.close()
    print('PASS Phase 5 mobile 390px: logistics known/missing, same Job followup, booking no re-ask, human fence/manual edit, tenant read/write 404, Finance pixel parity; synthetic model only')


if __name__=='__main__': main()
