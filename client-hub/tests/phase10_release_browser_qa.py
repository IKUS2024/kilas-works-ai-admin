"""Release journeys against the synthetic loopback harness, without session injection."""
import json
import re
import csv
import io
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:8771'
OUT = Path('/tmp/kilas-phase10-browser-qa'); OUT.mkdir(exist_ok=True)
PASSWORD = 'Phase10-disposable-only!'
checks = []


def shot(page, name):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url
    page.screenshot(path=str(OUT / (name + '.png')), full_page=True)
    checks.append(name)


def login(page, email):
    page.goto(BASE + '/login')
    page.locator('[name=email]').fill(email)
    page.locator('[name=password]').fill(PASSWORD)
    page.locator('button.auth-submit').click()
    expect(page.locator('button.auth-submit')).to_have_count(0)


def signup(page, name):
    page.goto(BASE + '/register')
    page.locator('[name=full_name]').fill('Release ' + name)
    page.locator('[name=email]').fill('release-' + name + '@example.test')
    page.locator('[name=password]').fill(PASSWORD)
    page.locator('button.auth-submit').click()
    expect(page.get_by_role('button', name='Pilih Layani Customer', exact=False)).to_be_visible()


def send(page, message):
    expect(page.locator('#web-message')).to_be_enabled()
    page.locator('#web-message').fill(message)
    page.get_by_role('button', name='Kirim', exact=True).click()
    expect(page.locator('[data-status]')).to_have_text('Pesan tersimpan.', timeout=15000)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        errors = []
        def new_page():
            page = browser.new_context(viewport={'width':390,'height':844}).new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            return page
        owner = new_page(); data = owner.context.request.get(BASE + '/dev/health').json()
        bid, target, branch = data['source'], data['target'], data['branch']
        # Registration, intent, business creation and minimal profile use real forms.
        for persona, label in [('ai','Layani Customer'), ('both','Keduanya')]:
            page = new_page(); signup(page, persona)
            page.get_by_role('button', name='Pilih ' + label, exact=False).click()
            page.get_by_label('Nama bisnis', exact=True).fill('Release ' + persona)
            page.get_by_role('button', name='Buat Bisnis & Setup Kilas Assist', exact=False).click()
            page.locator('[name=category]').fill('Logistics')
            page.locator('[name=owner_name]').fill('Release Owner')
            page.locator('[name=short_description]').fill('Pengiriman barang untuk QA disposable')
            page.get_by_role('button', name='Simpan & Lanjut', exact=True).click()
            assert '/wizard/services' in page.url
            page.goto(BASE + '/workspace'); shot(page, persona + '-signup-minimal-setup')
            page.goto(BASE + '/logout'); login(page, 'release-' + persona + '@example.test')
            expect(page.get_by_role('heading', name='Release ' + persona, exact=True)).to_be_visible()
            shot(page, persona + '-login-persistence')
            if persona == 'both':
                page.goto(BASE + '/workspace/go/finance_setup')
                page.get_by_role('button', name='Mulai Sekarang', exact=False).click()
                expect(page.get_by_role('heading', name='Release both', exact=True)).to_be_visible()
                page.goto(BASE + '/workspace')
                expect(page.locator('.finance-app-sidebar')).to_be_visible()
                page.locator('.product-switcher summary').click()
                page.get_by_role('navigation',name='Pilih produk').get_by_role('link',name='Kilas Assist',exact=True).click()
                assert [s.strip() for s in page.locator('.kw-primary a>span:last-child').all_text_contents()] == ['Home','Inbox','Customers','Jobs','More']
                shot(page, 'both-real-finance-activation')
        finance_only = new_page(); signup(finance_only, 'finance')
        finance_only.get_by_role('button', name='Pilih Kelola Keuangan', exact=False).click()
        finance_only.get_by_role('button', name='Mulai Sekarang', exact=False).click()
        expect(finance_only.get_by_role('heading', name='Release finance', exact=True)).to_be_visible()
        finance_bid = re.search(r'/business/(\d+)/finance', finance_only.url).group(1)
        finance_base = BASE + f'/business/{finance_bid}/finance'
        finance_only.goto(finance_base + '?view=accounts')
        finance_only.locator('[data-finance-open="account-dialog"]').first.click()
        account_form = finance_only.locator('#account-dialog form[data-account-type-manager]')
        account_form.locator('[name=name]').fill('Release Cash')
        account_form.locator('[name=currency]').select_option('IDR')
        account_form.locator('[name=opening_balance]').fill('1000')
        account_form.get_by_role('button', name='Tambah Akun', exact=True).click()
        finance_only.get_by_role('region', name='Daftar Akun').locator('details').filter(
            has=finance_only.get_by_text('Release Cash', exact=True)).locator('summary').first.click()
        expect(finance_only.get_by_text('Release Cash', exact=True).first).to_be_visible()
        shot(finance_only, 'finance-only-account-opening')
        for direction, amount in [('INCOME','200'),('EXPENSE','50')]:
            finance_only.goto(finance_base + '?view=transactions&direction=' + direction)
            finance_only.locator('[data-finance-open="add-transaction-dialog"]').first.click()
            form = finance_only.locator('#add-transaction')
            form.locator('[name=account_id]').select_option(label='Release Cash · IDR')
            form.locator('[name=amount]').fill(amount)
            category = form.locator(f'[name=category_id] option[data-direction="{direction}"][data-other="false"]').first.get_attribute('value')
            form.locator('[name=category_id]').select_option(category)
            form.get_by_role('button', name='Simpan Transaksi', exact=True).click()
            expect(finance_only.locator('#add-transaction-dialog')).not_to_be_visible()
            shot(finance_only, 'finance-only-' + direction.lower())
        def ledger():
            response = finance_only.context.request.get(finance_base + '/reports/export/transactions.csv')
            assert response.ok
            return list(csv.DictReader(io.StringIO(response.text().lstrip('\ufeff'))))
        before_drafts = ledger()
        assert len(before_drafts) == 2, before_drafts
        finance_only.goto(finance_base + '/operations')
        finance_only.get_by_role('button', name='Tambah tagihan', exact=True).click()
        bill = finance_only.locator('#bill-add-dialog form')
        bill.locator('[name=name]').fill('Release Internet')
        bill.locator('[name=amount]').fill('25')
        bill.locator('[data-bill-category-summary]').click()
        bill.locator('[data-bill-category-option]').first.click()
        bill.locator('[name=cadence]').select_option('MONTHLY')
        bill.get_by_role('button', name='Simpan Tagihan', exact=True).click()
        expect(finance_only.get_by_text('Release Internet', exact=True).first).to_be_visible()
        shot(finance_only, 'finance-only-recurring-created')
        finance_only.goto(finance_base + '/budget')
        finance_only.locator('.finance-budget-category-row').first.click()
        budget = finance_only.locator('dialog[open] form.finance-budget-sheet-form')
        budget.locator('[name=amount]').fill('300')
        budget.locator('[name=currency]').select_option('IDR')
        budget.get_by_role('button', name='Simpan Anggaran', exact=True).click()
        shot(finance_only, 'finance-only-budget-created')
        finance_only.goto(finance_base + '/assistant')
        finance_only.locator('#assistant-text').fill('catat pengeluaran')
        finance_only.locator('#assistant-send').click()
        expect(finance_only.locator('#assistant-draft-status')).to_contain_text('Draft', timeout=15000)
        finance_only.locator('#assistant-text').fill('batal')
        finance_only.locator('#assistant-send').click()
        expect(finance_only.locator('#assistant-draft-status')).to_have_text('')
        assert ledger() == before_drafts, 'Budget, recurring rule or unconfirmed AI draft posted cash'
        shot(finance_only, 'finance-ai-draft-cancel-no-write')
        finance_only.goto(finance_base + '/invoices/new')
        finance_only.locator('#new-recipient').click()
        finance_only.locator('[name=recipient_name]').fill('Standalone release customer')
        finance_only.locator('[name=sender_address]').fill('Synthetic QA address')
        finance_only.locator('[name=sender_phone]').fill('080000000001')
        finance_only.locator('[name=item_description]').first.fill('Synthetic service')
        finance_only.locator('[name=quantity]').first.fill('1')
        finance_only.locator('[name=unit_price]').first.fill('1000')
        finance_only.get_by_role('button', name='Simpan Draft & Preview', exact=True).click()
        finance_only.get_by_role('button', name='Terbitkan Invoice', exact=True).click()
        finance_only.locator('[name=amount]').fill('400')
        finance_only.locator('[name=account_id]').select_option(label='Release Cash · IDR')
        finance_only.locator('[name=category_id]').select_option(index=1)
        finance_only.get_by_role('button', name='Simpan Pembayaran', exact=True).click()
        expect(finance_only.locator('.fin-invoice-amounts')).to_contain_text('600')
        assert len(ledger()) == 3
        shot(finance_only, 'finance-only-invoice-partial-payment')
        for tail in ('operations','budget','reports','assistant'):
            assert finance_only.goto(finance_base + '/' + tail).status == 200
            shot(finance_only, 'finance-only-' + tail)
        export = finance_only.context.request.get(finance_base + '/reports/export/all.zip')
        assert export.ok and 'zip' in export.headers.get('content-type',''), export.status
        finance_only.goto(BASE + '/workspace')
        expect(finance_only.locator('.finance-app-sidebar')).to_be_visible()
        assert finance_only.locator('.kw-primary').count() == 0
        assert finance_only.locator('.product-switcher').count() == 0
        finance_only.goto(BASE + '/logout'); login(finance_only, 'release-finance@example.test')
        shot(finance_only, 'finance-only-signup-activation-persistence')
        # Existing eligible full-package fixture: only entitlement/model are synthetic.
        login(owner, data['email'])
        owner.goto(BASE + f'/business/{bid}/automations')
        csrf = owner.locator('input[name="csrf_token"]').first.input_value()
        owner.goto(BASE + f'/business/{bid}/inbox?channel=web')
        public_link_path = f'/business/{bid}/web-chat/link'
        assert owner.context.request.post(BASE + public_link_path, data={}).status == 400
        response = owner.context.request.post(BASE + public_link_path, data={},
            headers={'X-CSRF-Token':csrf})
        assert response.ok, response.text()
        visitor = new_page(); visitor.goto(BASE + response.json()['path'])
        send(visitor, 'Mau kirim 20 kg baju dari Guangzhou ke Tangerang')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(1, timeout=15000)
        assert 'volume' in visitor.locator('.web-bubble.assistant').inner_text()
        # CRM policy: a new contact is a Lead and must not expose Jobs until confirmed Customer.
        owner.goto(BASE + f'/business/{bid}/customers?stage=LEAD')
        owner.locator('a.client-item').first.click()
        expect(owner.locator('[data-linked-jobs]')).to_have_count(0)
        owner.locator('select[name=stage]').select_option('CUSTOMER')
        owner.get_by_role('button', name='Simpan', exact=True).click()
        expect(owner.locator('[data-linked-jobs] a.client-item')).to_have_count(0)
        send(visitor, 'Mau kirim 20 kg baju dari Guangzhou ke Tangerang')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(2, timeout=15000)
        owner.reload()
        expect(owner.locator('[data-linked-jobs] a.client-item')).to_have_count(1)
        owner.goto(BASE + f'/business/{bid}/inbox?channel=web')
        owner.locator('a.web-conversation').first.click()
        expect(owner.locator('[data-linked-jobs] a.client-item')).to_have_count(1)
        job_url = BASE + owner.locator('[data-linked-jobs] a.client-item').get_attribute('href')
        inbox_url = owner.url
        send(visitor, 'Volumenya 0.2 m3')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(3, timeout=15000)
        owner.reload()
        assert BASE + owner.locator('[data-linked-jobs] a.client-item').get_attribute('href') == job_url
        shot(owner, 'web-inbox-same-job-followup')
        owner.goto(job_url)
        customer_url = BASE + owner.locator('[data-job-customer]').get_attribute('href')
        owner.goto(inbox_url)
        owner.get_by_role('button', name='Ambil alih', exact=True).click()
        expect(owner.locator('#web-owner-message')).to_be_enabled(timeout=10000)
        send(visitor, 'Koreksi asalnya Shanghai')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(3)
        owner.locator('#web-owner-message').fill('Tim sedang memeriksa pengiriman Anda.')
        owner.get_by_role('button', name='Kirim balasan', exact=True).click()
        expect(owner.locator('[data-send-status]')).to_have_text('Balasan terkirim.')
        expect(visitor.locator('.web-bubble.human')).to_have_count(1, timeout=10000)
        owner.get_by_role('button', name='Kembalikan ke AI', exact=True).click()
        expect(owner.locator('[data-mode]')).to_have_text('AI aktif', timeout=10000)
        send(visitor, 'Koreksi asalnya Shanghai')
        expect(visitor.locator('.web-bubble.assistant')).to_have_count(4, timeout=15000)
        owner.goto(job_url); expect(owner.locator('#field-origin')).to_have_value('Shanghai')
        shot(owner, 'human-reply-explicit-resume-persisted')

        # Customer has explicitly dealt: move the owner-visible Job to Dikerjakan.
        owner.goto(job_url)
        owner.get_by_label('Status', exact=True).select_option('IN_PROGRESS')
        owner.get_by_role('button', name='Simpan perubahan', exact=True).click()
        expect(owner.locator('span.client-status').first).to_have_text('Dikerjakan')

        base = BASE + f'/business/{bid}/finance-bridge'
        owner.goto(base)
        owner.get_by_label('Bisnis dan cabang Finance').select_option(f'{target}:{branch}')
        owner.get_by_role('checkbox').check()
        owner.get_by_role('button', name='Simpan koneksi', exact=True).click()
        cid = customer_url.rsplit('/',1)[-1]; jid = job_url.rsplit('/',1)[-1]
        bridge_job = base + '/jobs/' + jid

        # Dikerjakan exposes the human invoice task. It must reuse the full Finance editor.
        owner.goto(job_url)
        expect(owner.get_by_text('Tugas manusia · Invoice', exact=True)).to_be_visible()
        owner.get_by_role('button', name='Buat Invoice', exact=True).click()
        assert f'/business/{target}/finance/invoices/new' in owner.url
        expect(owner.get_by_text('Buat Invoice', exact=True)).to_be_visible()
        owner.locator('[name=sender_address]').fill('Synthetic QA address')
        owner.locator('[name=sender_phone]').fill('080000000002')
        owner.locator('[name=item_description]').first.fill('Synthetic reviewed shipping')
        owner.locator('[name=quantity]').first.fill('2')
        owner.locator('[name=unit_price]').first.fill('500')
        shot(owner, 'job-finance-full-editor')
        owner.get_by_role('button', name='Simpan Draft & Preview', exact=True).click()

        # Saving the authoritative Finance draft returns to the Job for the human publish action.
        assert owner.url.startswith(job_url)
        expect(owner.get_by_role('button', name='Terbitkan', exact=True)).to_be_visible()
        shot(owner, 'job-invoice-draft-ready-to-publish')
        owner.get_by_role('button', name='Terbitkan', exact=True).click()
        expect(owner.get_by_text('Customer sudah bayar?', exact=True)).to_be_visible()
        shot(owner, 'job-invoice-issued-payment-task')

        # Human confirms the full outstanding payment. Finance must own the resulting ledger write.
        payment = owner.locator('form').filter(has=owner.get_by_role('button', name='Invoice sudah dibayar', exact=True))
        payment.locator('[name=account_id]').select_option(index=1)
        payment.locator('[name=category_id]').select_option(index=1)
        payment.get_by_role('button', name='Invoice sudah dibayar', exact=True).click()
        expect(owner.get_by_text('Lunas · pembayaran sudah masuk sebagai pemasukan di Kilas Finance.', exact=True)).to_be_visible()
        shot(owner, 'job-invoice-paid-finance-income')
        invoice_link = owner.get_by_role('link', name='Buka Invoice di Finance', exact=True)
        invoice_url = BASE + invoice_link.get_attribute('href')

        owner.goto(BASE + '/logout')
        assert '/login' in owner.goto(job_url).url
        login(owner, data['email']); owner.goto(job_url)
        expect(owner.get_by_text('Lunas · pembayaran sudah masuk sebagai pemasukan di Kilas Finance.', exact=True)).to_be_visible()
        shot(owner, 'full-logout-login-persistence')
        other = new_page(); login(other, data['foreign_email'])
        for path in (job_url, customer_url, bridge_job, invoice_url, inbox_url):
            assert other.goto(path).status == 404, path
        checks.append('foreign-tenant-direct-objects-denied')
        operator = new_page(); login(operator, 'phase10-operator@example.test')
        for path in ('/admin','/admin/search','/admin/projects','/admin/payments','/admin/talent','/admin/ai-usage'):
            assert operator.goto(BASE + path).status == 200, path
            shot(operator, 'operator-' + path.rsplit('/',1)[-1])
        assert not errors, errors
        (OUT/'results.json').write_text(json.dumps({'passed':True,'checks':checks},indent=2))
        print('Phase 10 authenticated release browser QA PASS:', len(checks), 'checks')
        browser.close()


if __name__ == '__main__':
    main()
