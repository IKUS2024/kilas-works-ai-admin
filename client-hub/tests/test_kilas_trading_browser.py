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
    output = Path('/tmp/kilas-trading-browser');output.mkdir(exist_ok=True)
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
            assert 'Kilas Services' not in page.locator('.trading').inner_text()
            assert page.locator('.trading-heading a').inner_text()=='Kilas Trading'
            assert page.get_by_role('button',name='Analisis market demo',exact=True).is_disabled()
            assert 'UNAVAILABLE' in page.locator('#ai-analysis-title').locator('..').inner_text()
            assert 'UNAVAILABLE' in page.locator('#observation-title').locator('..').inner_text()
            assert 'XAUUSD' in page.locator('.trading').inner_text()
            assert 'Jumlah troy oz sintetis' in page.locator('.trading').inner_text()
            page.get_by_text('Asumsi kontrak XAUUSD simulasi dan candle terakhir',exact=True).click()
            assert 'troy ounce' in page.locator('.trading').inner_text()
            assert 'belum diverifikasi' in page.locator('.trading').inner_text()
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
            assert page.locator('#trading-status').inner_text()=='PAUSED'
            assert page.get_by_role('button',name='Buka posisi simulasi',exact=True).is_disabled()
            with page.expect_navigation():page.get_by_role('button',name='Lanjutkan',exact=True).click()
            with page.expect_navigation():page.get_by_role('button',name='Evaluasi candle ini sekali',exact=True).click()
            assert 'NO_SIGNAL' in page.locator('.trading-event').first.inner_text()
            with page.expect_navigation():page.get_by_role('button',name='Maju 1 candle',exact=True).click()
            with page.expect_navigation():page.locator('.trading-position-actions form:last-child button').click()
            assert page.locator('.trading-position').count()==0
            page.locator('form[data-order] input[name=quantity]').fill('1')
            page.get_by_role('button',name='Buka posisi simulasi',exact=True).click()
            page.wait_for_function("document.querySelector('#trading-status').textContent==='ERROR'")
            assert page.locator('#trading-error').is_visible()
            assert page.get_by_role('button',name='Analisis market demo',exact=True).is_disabled()
            page.reload();assert 'REJECTED' in page.locator('.trading-event').first.inner_text()
            page.locator('input[name=steps]').fill('20')
            with page.expect_navigation():page.get_by_role('button',name='Jalankan paper agent',exact=True).click()
            assert 'Run paper selesai: 20 candle' in page.locator('.trading-event').first.inner_text()
            assert page.locator('.trading-event').count()>=20
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(output/'journal-mobile.png'),full_page=True)
            from test_kilas_trading_observation import observation_fixture
            f.app.app.config.update(TESTING=True, KILAS_TRADING_OBSERVATION_FIXTURE=observation_fixture())
            page.reload()
            panel = page.locator('#observation-title').locator('..')
            assert 'OBSERVATION_ONLY' in panel.inner_text() and 'freshness unknown' in panel.inner_text()
            assert 'GOLD' in panel.inner_text() and 'unknown' in panel.inner_text()
            panel.get_by_text('Bukti waktu fixture', exact=True).click()
            assert 'null · belum diketahui' in panel.inner_text()
            for width in (1440, 320):
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert page.get_by_role('button',name='Analisis market demo',exact=True).is_disabled()
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
            assert 'freshness unknown' in panel.inner_text()
            panel.get_by_text('Bukti waktu observasi',exact=True).click()
            panel.get_by_text('3 candle mentah · M1 · waktu/closed belum diverifikasi',exact=True).click()
            for width in (1440,320):
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert page.get_by_role('button',name='Analisis market demo',exact=True).is_disabled()
                page.screenshot(path=str(output/f'observation-upload-{width}.png'),full_page=True)
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
    print('Browser PASS: login → Service → Trading; 1440/768/390/320; order/SL-TP/pause/resume/decision/replay/close/error journal; no page errors.')


if __name__=='__main__':main()
