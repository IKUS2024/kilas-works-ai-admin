"""Real Chromium mobile Jobs flow, synthetic loopback harness only. No production data."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
BASE=os.environ.get('KILAS_PUBLIC_CHAT_QA_BASE','http://127.0.0.1:8765').rstrip('/')
if urlsplit(BASE).hostname not in ('127.0.0.1','localhost'):
    raise SystemExit('This owner QA uses disposable loopback only')
OUT=Path(os.environ.get('KILAS_PUBLIC_CHAT_QA_OUT','/tmp/kilas-phase4-browser-qa'))
OUT.mkdir(parents=True,exist_ok=True)


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':390,'height':844})
        owner=context.new_page();errors=[]
        owner.on('pageerror',lambda error:errors.append(str(error)))
        finance_ctx=browser.new_context(viewport={'width':390,'height':844})
        finance=finance_ctx.new_page()
        finance.goto(BASE+'/dev/finance',wait_until='networkidle')
        expect(finance.locator('.finance-entry-shell')).to_be_visible()
        before_text=finance.locator('.finance-entry-shell').inner_text()
        before=finance.screenshot(path=str(OUT/'06_finance_before.png'),full_page=True)

        owner.goto(BASE+'/dev/owner/7',wait_until='networkidle')
        owner.goto(BASE+'/business/7/customers?stage=CUSTOMER',wait_until='networkidle')
        owner.locator('a.client-item').first.click()
        customer_url=owner.url
        expect(owner.locator('[data-create-job]')).to_be_visible()
        owner.locator('[data-create-job]').click()
        expect(owner.get_by_role('heading',name='Buat Pesanan')).to_be_visible()
        owner.get_by_label('Judul',exact=True).fill('Pesanan kantor Jumat')
        owner.get_by_label('Ringkasan',exact=True).fill('Siapkan 20 paket makan siang')
        owner.get_by_text('Rincian tambahan',exact=True).click()
        owner.get_by_label('Jumlah',exact=True).fill('20')
        owner.get_by_label('Satuan',exact=True).fill('paket')
        fits(owner)
        owner.get_by_role('button',name='Buat Pesanan',exact=True).click()
        expect(owner.get_by_text('Data tersimpan.',exact=True)).to_be_visible()
        first_job_url=owner.url.split('?')[0]
        fits(owner)
        owner.screenshot(path=str(OUT/'07_job_created.png'),full_page=True)
        owner.get_by_label('Status',exact=True).select_option('NEEDS_INFORMATION')
        owner.get_by_role('button',name='Simpan perubahan',exact=True).click()
        expect(owner.locator('span.client-status')).to_have_text('Butuh informasi')
        owner.screenshot(path=str(OUT/'08_job_updated.png'),full_page=True)
        owner.locator('[data-job-customer]').click()
        expect(owner.locator('[data-linked-jobs]').get_by_text('Pesanan kantor Jumat',exact=True)).to_be_visible()
        owner.screenshot(path=str(OUT/'09_customer_jobs.png'),full_page=True)
        # Customer-only Jobs remain supported; retired Web Chat is no longer a CRM navigation source.
        expect(owner.locator('[data-linked-jobs]').get_by_text('Pesanan kantor Jumat',exact=True)).to_be_visible()

        owner.goto(BASE+'/business/7/jobs',wait_until='networkidle')
        owner.get_by_label('Cari pesanan',exact=True).fill('kantor')
        owner.get_by_label('Status',exact=True).select_option('NEEDS_INFORMATION')
        owner.get_by_role('button',name='Cari',exact=True).click()
        expect(owner.locator('a.client-item')).to_have_count(1)
        fits(owner);owner.screenshot(path=str(OUT/'11_jobs_filter.png'),full_page=True)

        other_ctx=browser.new_context(viewport={'width':390,'height':844})
        other=other_ctx.new_page();other.goto(BASE+'/dev/owner/8',wait_until='networkidle')
        for url in (first_job_url,first_job_url.replace('/business/7/','/business/8/')):
            assert other.goto(url,wait_until='domcontentloaded').status==404
        # A workspace preference cannot revoke this owner's entitled AI Job access.
        assert finance.goto(first_job_url,wait_until='networkidle').status==200
        expect(finance.locator('[data-job-customer]')).to_be_visible()
        # Explicitly return to Finance and retain its independent, unchanged presentation.
        finance.goto(BASE+'/products/finance',wait_until='networkidle')
        assert urlsplit(finance.url).path=='/products/finance'
        expect(finance.locator('.finance-entry-shell')).to_be_visible()
        assert finance.locator('.finance-entry-shell').inner_text()==before_text
        assert finance.locator('[data-jobs-page], [data-linked-jobs]').count()==0
        after=finance.screenshot(path=str(OUT/'12_finance_after.png'),full_page=True)
        assert before==after, 'Finance entry visual changed'
        assert not errors, errors
        browser.close()
    print('PASS: mobile Jobs create/edit/lifecycle, Customer linkage, filter, tenant 404, no overflow, Finance entry pixel parity and authorized product transitions')


if __name__=='__main__': main()
