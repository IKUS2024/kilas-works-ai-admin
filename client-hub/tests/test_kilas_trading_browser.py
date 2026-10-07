"""Actual local app browser acceptance and responsive desktop/mobile evidence."""
import os
import shutil
import threading
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
import test_kilas_trading as f


def main():
    f.TradingTests.setUpClass()
    f.app.app.config.update(TESTING=False)
    server = make_server('127.0.0.1', 0, f.app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    origin = 'http://127.0.0.1:' + str(server.server_port)
    output = Path(os.environ.get('TRADING_QA_OUTPUT', '/tmp/kilas-trading-browser'));output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            executable = os.environ.get('TRADING_CHROMIUM') or shutil.which('chromium')
            browser = p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1100})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/login')
            page.locator('input[name=email]').fill('irvankarnavi@gmail.com');page.locator('input[name=password]').fill('paper-test-only')
            page.get_by_role('button',name='Login',exact=True).click()
            page.wait_for_url('**/products/start')
            assert page.locator('.premium-home-secondary h2').filter(has_text='Kilas Trading').count()==1
            assert page.locator('.premium-home-secondary a[href="/products/services/trading"]').inner_text()=='Buka Kilas Trading'
            page.locator('.premium-home-secondary a[href="/products/services/trading"]').click()
            page.wait_for_url('**/products/services/trading')
            assert 'Kilas Services' not in page.locator('.trading').text_content()
            assert page.locator('.trading-heading a').inner_text()=='Muat ulang dashboard'
            assert page.get_by_role('button',name='Analisis market demo',exact=True,include_hidden=True).is_disabled()
            assert 'UNAVAILABLE' in page.locator('#ai-analysis-title').locator('..').text_content()
            assert 'UNAVAILABLE' in page.locator('#observation-title').locator('..').text_content()
            assert 'XAUUSD' in page.locator('.trading').text_content()
            assert 'Jumlah troy oz sintetis' in page.locator('.trading').text_content()
            for name in ('Hubungkan','Putuskan koneksi','Mulai AI','Jeda AI'):
                assert page.get_by_role('button',name=name,exact=True).is_disabled()
            assert 'DEMO / REAL belum terverifikasi' in page.locator('.trading-connection').inner_text()
            assert 'Data broker:' in page.locator('#paper-account-title').locator('..').inner_text()
            assert 'belum tersedia' in page.locator('#paper-account-title').locator('..').inner_text()
            assert not page.locator('#paper-tools').evaluate('e=>e.open')
            assert not page.locator('#market-details').evaluate('e=>e.open')
            assert not page.locator('#history-details').evaluate('e=>e.open')
            assert not page.locator('#observation-details').evaluate('e=>e.open')
            assert not page.locator('#order-advanced').evaluate('e=>e.open')
            assert not page.locator('form[data-order] input[name=trailing_distance]').is_visible()
            assert page.get_by_role('button',name='Hentikan trading',exact=True).is_visible()
            assert not page.get_by_role('button',name='Langkah simulasi berikutnya',exact=True,include_hidden=True).is_visible()
            for width in (1440,768,390,320):
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
                assert page.locator('#paper-risk-form').is_visible()
                page.screenshot(path=str(output/f'simple-dashboard-{width}.png'),full_page=True)
            # Native keyboard expansion, then preserve existing advanced functional scenarios.
            chart_summary=page.locator('#market-details > summary')
            chart_summary.focus();page.keyboard.press('Enter')
            assert page.locator('.trading-chart').is_visible()
            chart_summary.focus();page.keyboard.press('Enter')
            assert not page.locator('.trading-chart').is_visible()
            before=f.store.snapshot(f.TradingTests.user)
            page.locator('#paper-risk-form input[name=risk_percent]').fill('0.5')
            page.locator('#paper-risk-form input[name=daily_loss]').fill('100')
            with page.expect_navigation():page.get_by_role('button',name='Simpan risiko',exact=True).click()
            after=f.store.snapshot(f.TradingTests.user)
            assert after['risk']['risk_bps']==50 and after['risk']['daily_loss_cents']==10000
            assert after['strategy']==before['strategy']
            assert {k:v for k,v in after['risk'].items() if k not in ('risk_bps','daily_loss_cents')}=={k:v for k,v in before['risk'].items() if k not in ('risk_bps','daily_loss_cents')}
            def reveal():
                page.evaluate("document.querySelectorAll('.trading details').forEach(e=>e.open=true)")
            reveal()
            page.on('domcontentloaded',lambda:reveal())
            assert 'troy ounce' in page.locator('.trading').text_content()
            assert 'belum diverifikasi' in page.locator('.trading').text_content()
            page.get_by_text('Asumsi kontrak XAUUSD simulasi dan candle terakhir',exact=True).click()
            for width in (1440,768,390,320):
                page.set_viewport_size({'width':width,'height':1100})
                page.locator('#trading-title').wait_for()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
                assert page.locator('.trading-chart').is_visible()
                assert page.locator('#trading-stop').evaluate("el=>getComputedStyle(el).backgroundColor")=='rgb(255, 255, 255)'
                page.screenshot(path=str(output/f'dashboard-{width}.png'),full_page=True)
            with page.expect_navigation():page.get_by_role('button',name='Buka posisi simulasi',exact=True).click()
            assert page.locator('.trading-position').count()==1
            with page.expect_navigation():page.get_by_role('button',name='Simpan SL/TP',exact=True).click()
            with page.expect_navigation():page.get_by_role('button',name='Jeda posisi baru',exact=True).click()
            assert page.locator('#trading-status').inner_text()=='DIJEDA'
            assert page.get_by_role('button',name='Buka posisi simulasi',exact=True).is_disabled()
            with page.expect_navigation():page.get_by_role('button',name='Lanjutkan',exact=True).click()
            with page.expect_navigation():page.get_by_role('button',name='Evaluasi candle ini sekali',exact=True).click()
            assert 'NO_SIGNAL' in page.locator('#history-details .trading-event').first.inner_text()
            with page.expect_navigation():page.get_by_role('button',name='Langkah simulasi berikutnya',exact=True).click()
            with page.expect_navigation():page.locator('.trading-position-actions form:last-child button').click()
            assert page.locator('.trading-position').count()==0
            page.locator('form[data-order] input[name=quantity]').fill('1')
            page.get_by_role('button',name='Buka posisi simulasi',exact=True).click()
            page.wait_for_function("document.querySelector('#trading-status').textContent==='Aksi gagal'")
            assert page.locator('#trading-error').is_visible()
            assert page.get_by_role('button',name='Analisis market demo',exact=True,include_hidden=True).is_disabled()
            for name in ('Hubungkan','Putuskan koneksi','Mulai AI','Jeda AI'):
                assert page.get_by_role('button',name=name,exact=True).is_disabled()
            page.screenshot(path=str(output/'error-mobile.png'),full_page=True)
            page.reload();assert 'REJECTED' in page.locator('#history-details .trading-event').first.inner_text()
            page.locator('input[name=steps]').fill('20')
            with page.expect_navigation():page.get_by_role('button',name='Jalankan paper agent',exact=True).click()
            assert 'Run paper selesai: 20 candle' in page.locator('#history-details .trading-event').first.inner_text()
            assert page.locator('#history-details .trading-event').count()>=20
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(output/'journal-mobile.png'),full_page=True)
            from test_kilas_trading_observation import observation_fixture
            f.app.app.config.update(TESTING=True, KILAS_TRADING_OBSERVATION_FIXTURE=observation_fixture())
            page.reload()
            panel = page.locator('#observation-title').locator('..')
            assert 'OBSERVATION_ONLY' in panel.inner_text() and 'usia data belum diketahui' in panel.inner_text()
            assert 'GOLD' in panel.inner_text() and 'unknown' in panel.inner_text()
            panel.get_by_text('Bukti waktu fixture', exact=True).locator('..').evaluate('e=>e.open=true')
            assert 'null · belum diketahui' in panel.inner_text()
            for width in (1440, 320):
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert page.get_by_role('button',name='Analisis market demo',exact=True,include_hidden=True).is_disabled()
                page.screenshot(path=str(output/f'observation-fixture-{width}.png'),full_page=True)
            f.app.app.config.pop('KILAS_TRADING_OBSERVATION_FIXTURE')
            f.app.app.config['TESTING'] = False
            from test_kilas_trading_observation import demo_upload
            import json
            page.reload()
            page.locator('input[name=observation]').set_input_files({'name':'synthetic-local-acceptance.json','mimeType':'application/json','buffer':json.dumps(demo_upload()).encode()})
            with page.expect_navigation(): page.get_by_role('button',name='Unggah observasi DEMO',exact=True).click()
            panel = page.locator('#observation-title').locator('..')
            assert 'sumber dinyatakan DEMO oleh pengunggah' in panel.inner_text()
            assert 'usia data belum diketahui' in panel.inner_text()
            panel.get_by_text('Bukti waktu observasi',exact=True).locator('..').evaluate('e=>e.open=true')
            panel.get_by_text('3 candle mentah · M1 · waktu/closed belum diverifikasi',exact=True).locator('..').evaluate('e=>e.open=true')
            for width in (1440,320):
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert page.get_by_role('button',name='Analisis market demo',exact=True,include_hidden=True).is_disabled()
                page.screenshot(path=str(output/f'observation-upload-{width}.png'),full_page=True)
            # UI submission lock blocks rapid repeated submissions; failed responses restore only eligible controls.
            calls=[]
            def rejected(route):
                calls.append(route.request.url)
                route.fulfill(status=409,content_type='application/json',body='{"message":"Aksi uji ditolak"}')
            page.route('**/trading/configure',rejected)
            page.locator('#paper-risk-form').evaluate("form=>{form.requestSubmit();form.requestSubmit()}")
            page.wait_for_function("document.querySelector('#trading-status').textContent==='Aksi gagal'")
            assert len(calls)==1
            for name in ('Hubungkan','Putuskan koneksi','Mulai AI','Jeda AI'):
                assert page.get_by_role('button',name=name,exact=True).is_disabled()
            page.unroute('**/trading/configure')
            # Network failure must display an uncertain result, never claim success.
            page.route('**/trading/configure',lambda route:route.abort())
            page.locator('#paper-risk-form').evaluate('form=>form.requestSubmit()')
            page.wait_for_function("document.querySelector('#trading-error').textContent.includes('Hasil belum pasti')")
            assert page.locator('#trading-error').is_visible()
            page.unroute('**/trading/configure')
            page.reload()
            page.locator('#trading-freshness').evaluate("e=>e.dataset.generated='2000-01-01T00:00:00Z'")
            page.wait_for_function("document.querySelector('#trading-freshness').textContent.includes('Harga perlu diperbarui')")
            assert page.locator('[data-new-position]').evaluate_all('items=>items.every(e=>e.disabled)')
            page.screenshot(path=str(output/'stale-mobile.png'),full_page=True)
            page.reload()
            previous=len(f.store.snapshot(f.TradingTests.user)['positions'])
            page.on('dialog',lambda dialog:dialog.accept())
            with page.expect_navigation():page.get_by_role('button',name='Hentikan trading',exact=True).click()
            assert f.store.snapshot(f.TradingTests.user)['account']['killed']
            assert len(f.store.snapshot(f.TradingTests.user)['positions'])==previous
            assert page.get_by_role('button',name='Hentikan trading',exact=True).is_disabled()
            page.screenshot(path=str(output/'stopped-mobile.png'),full_page=True)
            # Missing storage uses the existing unavailable route and a reload affordance.
            from unittest.mock import patch
            with patch.object(f.store,'snapshot',return_value=None):
                page.reload()
                assert page.get_by_role('heading',name='Simulasi belum tersedia').is_visible()
                assert page.get_by_role('link',name='Muat ulang',exact=True).is_visible()
                assert page.locator('.trading [data-new-position]').count()==0
                for width in (1440,320):
                    page.set_viewport_size({'width':width,'height':1100})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    page.screenshot(path=str(output/f'unavailable-{width}.png'),full_page=True)
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
    print('Browser PASS: login → Service → Trading; 1440/768/390/320; order/SL-TP/pause/resume/decision/replay/close/error journal; no page errors.')


if __name__=='__main__':main()
