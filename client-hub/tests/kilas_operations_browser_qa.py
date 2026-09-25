"""Phase 6 mobile A–E on synthetic loopback. No production data or model IO."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
BASE=os.environ.get('KILAS_PUBLIC_CHAT_QA_BASE','http://127.0.0.1:8767').rstrip('/')
if urlsplit(BASE).hostname not in ('127.0.0.1','localhost'):
    raise SystemExit('Disposable loopback only')
OUT=Path(os.environ.get('KILAS_PUBLIC_CHAT_QA_OUT','/tmp/kilas-phase6-browser-qa'))
OUT.mkdir(parents=True,exist_ok=True)
FOLLOWUP='Apakah masih ada yang ingin dilengkapi untuk kebutuhan Anda? Kami siap membantu di percakapan ini.'
REVIEW='Terima kasih telah menggunakan layanan kami. Jika berkenan, boleh bagikan ulasan pengalaman Anda di sini?'


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'


def send(page,text):
    expect(page.locator('#web-message')).to_be_enabled()
    page.locator('#web-message').fill(text)
    page.get_by_role('button',name='Kirim',exact=True).click()
    expect(page.locator('[data-status]')).to_have_text('Pesan tersimpan.',timeout=15000)


def run(owner):
    owner.goto(BASE+'/business/7/automations',wait_until='networkidle')
    owner.get_by_role('button',name='Periksa sekarang',exact=True).click()
    expect(owner.locator('[data-automations-page]')).to_be_visible()


def advance(owner):
    response=owner.context.request.post(BASE+'/dev/operations/advance',form={'csrf_token':'csrf-test'})
    assert response.ok,response.text()


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);errors=[]
        def page():
            result=browser.new_context(viewport={'width':390,'height':844}).new_page()
            result.on('pageerror',lambda e:errors.append(str(e)))
            return result
        owner=page();visitor=page();other=page();finance=page()
        finance.goto(BASE+'/dev/finance',wait_until='networkidle')
        expect(finance.locator('.finance-entry-shell')).to_be_visible()
        before=finance.screenshot(path=str(OUT/'01_finance_before.png'),full_page=True)
        owner.goto(BASE+'/dev/owner/7',wait_until='networkidle')
        share=owner.locator('[data-web-share]').first
        response=owner.context.request.post(BASE+share.get_attribute('data-url'),
            headers={'X-CSRF-Token':share.get_attribute('data-csrf'),'Content-Type':'application/json'},data={})
        assert response.ok,response.text()
        visitor.goto(BASE+response.json()['path'],wait_until='networkidle')
        send(visitor,'Saya mau bicara dengan manusia')
        owner.goto(BASE+'/products/assist',wait_until='networkidle')
        home=owner.locator('[data-attention-home]')
        expect(home.get_by_text('1 hal perlu perhatian',exact=True)).to_be_visible()
        fits(owner);owner.screenshot(path=str(OUT/'02_home_human_attention.png'),full_page=True)
        home.locator('[data-attention-inbox]').click()
        inbox_url=owner.url
        expect(owner.locator('#web-owner-message')).to_be_enabled(timeout=10000)
        owner.locator('#web-owner-message').fill('Tim siap membantu pengiriman Anda.')
        owner.get_by_role('button',name='Kirim balasan',exact=True).click()
        expect(visitor.locator('.web-bubble.human').filter(has_text='Tim siap membantu pengiriman Anda.')).to_be_visible(timeout=15000)
        fits(visitor);visitor.screenshot(path=str(OUT/'03_human_reply.png'),full_page=True)
        owner.get_by_role('button',name='Kembalikan ke AI',exact=True).click()
        expect(owner.locator('[data-mode]')).to_have_text('AI aktif',timeout=10000)
        send(visitor,'Mau kirim 20 kg baju dari Guangzhou ke Tangerang')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(1,timeout=10000)
        send(visitor,'Volumenya 0.2 m3')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(2,timeout=10000)
        owner.goto(BASE+'/products/assist',wait_until='networkidle')
        expect(home.get_by_text('1 hal perlu perhatian',exact=True)).to_be_visible()
        expect(home.locator('[data-attention-item]')).to_have_count(1)
        home.locator('[data-attention-job]').click()
        job_url=owner.url.split('?')[0]
        expect(owner.locator('span.client-status')).to_have_text('Siap ditawarkan')
        fits(owner);owner.screenshot(path=str(OUT/'04_ready_job.png'),full_page=True)
        owner.goto(BASE+'/business/7/automations',wait_until='networkidle')
        owner.locator('#followup-enabled').select_option('true')
        owner.locator('#review-enabled').select_option('true')
        owner.locator('#delay-hours').fill('1');owner.locator('#max-attempts').fill('2')
        owner.get_by_role('button',name='Simpan pengaturan',exact=True).click()
        expect(owner.get_by_text('Pengaturan tersimpan.',exact=True)).to_be_visible()
        fits(owner);owner.screenshot(path=str(OUT/'05_bounded_settings.png'),full_page=True)
        advance(owner);run(owner)
        expect(visitor.locator('.web-bubble.assistant').filter(has_text=FOLLOWUP)).to_have_count(1,timeout=15000)
        run(owner)
        expect(visitor.locator('.web-bubble.assistant').filter(has_text=FOLLOWUP)).to_have_count(1)
        owner.goto(inbox_url,wait_until='networkidle')
        owner.get_by_role('button',name='Ambil alih',exact=True).click()
        expect(owner.locator('#web-owner-message')).to_be_enabled(timeout=10000)
        advance(owner);run(owner)
        expect(visitor.locator('.web-bubble.assistant').filter(has_text=FOLLOWUP)).to_have_count(1)
        owner.goto(inbox_url,wait_until='networkidle')
        owner.get_by_role('button',name='Kembalikan ke AI',exact=True).click()
        expect(owner.locator('[data-mode]')).to_have_text('AI aktif',timeout=10000)
        owner.goto(job_url,wait_until='networkidle')
        for status in ('QUOTED','APPROVED','IN_PROGRESS','COMPLETED'):
            owner.get_by_label('Status',exact=True).select_option(status)
            owner.get_by_role('button',name='Simpan perubahan',exact=True).click()
            expect(owner.get_by_text('Data tersimpan.',exact=True)).to_be_visible()
        run(owner)
        expect(visitor.locator('.web-bubble.assistant').filter(has_text=REVIEW)).to_have_count(1,timeout=15000)
        run(owner)
        expect(visitor.locator('.web-bubble.assistant').filter(has_text=REVIEW)).to_have_count(1)
        fits(visitor);visitor.screenshot(path=str(OUT/'06_followup_and_review.png'),full_page=True)
        owner.goto(BASE+'/business/7/attention',wait_until='networkidle')
        expect(owner.locator('[data-attention-item]')).to_have_count(0)
        fits(owner);owner.screenshot(path=str(OUT/'07_resolved_attention.png'),full_page=True)
        other.goto(BASE+'/dev/owner/8',wait_until='networkidle')
        for path in ('/business/7/attention','/business/7/automations'):
            assert other.goto(BASE+path,wait_until='domcontentloaded').status==404
        assert other.context.request.post(BASE+'/business/7/automations/run',form={'csrf_token':'csrf-test'}).status==404
        other.goto(BASE+'/business/8/attention',wait_until='networkidle')
        expect(other.locator('[data-attention-item]')).to_have_count(0)
        assert finance.goto(BASE+'/business/7/attention',wait_until='networkidle').status==200
        finance.goto(BASE+'/products/finance',wait_until='networkidle')
        assert urlsplit(finance.url).path=='/products/finance'
        assert finance.screenshot(path=str(OUT/'08_finance_after.png'),full_page=True)==before
        assert not errors,errors
        browser.close()
    print('PASS Phase 6 mobile 390px A–E: human Home/Inbox/manual reply/return, ready attention, clock followup once/human suppression, completed review once, tenant read/write 404, Finance pixel parity')


if __name__=='__main__': main()
