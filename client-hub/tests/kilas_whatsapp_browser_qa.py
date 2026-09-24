"""CI regression for real owner UI in 390x844 Chromium; synthetic loopback fixture only."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
BASE='http://127.0.0.1:8769'
OUT=Path('/tmp/kilas-phase8-browser-qa');OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_context(viewport={'width':390,'height':844}).new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(BASE+'/dev/owner/7',wait_until='networkidle')
    expect(page.locator('[data-owner-chat]')).to_be_visible()
    expect(page.locator('.web-panel h2').filter(has_text='WhatsApp')).to_be_visible()
    expect(page.locator('[data-playbook-context]').filter(has_text='Guangzhou')).to_be_visible()
    expect(page.locator('.web-bubble.assistant')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT/'01_whatsapp_core_inbox.png'),full_page=True)
    page.get_by_role('button',name='Ambil alih',exact=True).click()
    expect(page.locator('#web-owner-message')).to_be_enabled(timeout=10000)
    page.locator('#web-owner-message').fill('Tim membantu pengiriman Anda.')
    page.get_by_role('button',name='Kirim balasan',exact=True).click()
    expect(page.locator('[data-send-status]')).to_have_text('Diterima Meta; menunggu status pengiriman.')
    expect(page.locator('.web-bubble.human')).to_have_count(1,timeout=10000)
    evidence=page.context.request.get(BASE+'/dev/evidence').json()
    assert evidence['attempts']==2,evidence
    page.get_by_role('button',name='Kirim template yang disetujui',exact=True).click()
    expect(page.locator('[data-send-status]')).to_have_text('Template diterima Meta; menunggu status pengiriman.')
    expect(page.locator('.web-bubble.human')).to_have_count(2,timeout=10000)
    assert page.context.request.get(BASE+'/dev/evidence').json()['attempts']==3
    page.screenshot(path=str(OUT/'02_human_official_reply.png'),full_page=True)
    page.get_by_role('button',name='Kembalikan ke AI',exact=True).click()
    expect(page.locator('[data-mode]')).to_have_text('AI aktif',timeout=10000)
    response=page.context.request.post(BASE+'/dev/inbound',headers={'X-CSRF-Token':'csrf-test'},data={})
    assert response.ok,response.text()
    expect(page.locator('.web-bubble.assistant')).to_have_count(2,timeout=10000)
    page.reload(wait_until='networkidle')
    expect(page.locator('[data-playbook-context]').filter(has_text='Rincian lengkap')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT/'03_resumed_job_updated.png'),full_page=True)
    foreign=page.context.request.get(BASE+'/business/8/web-inbox/'+evidence['conversation']+'/messages')
    assert foreign.status==404
    assert not errors,errors
    browser.close()
print('Phase 8 mobile owner Inbox PASS: channel, known/missing, takeover, official manual reply, resume, Job update, tenant denial, no overflow/JS errors')
