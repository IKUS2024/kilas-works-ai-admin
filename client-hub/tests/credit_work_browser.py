"""Synthetic Work consent and Interpreter layout, four languages and two widths."""
import json
import logging
import shutil
from pathlib import Path
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_credit_work_routes as fixture
from kilas_ai.agent_workers import image_worker
from kilas_ai import autonomous_store as store


def main():
    fixture.WorkRouteCreditTests.setUpClass()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app=fixture.WorkRouteCreditTests.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    dest=Path('/tmp/kilas-credit-work-browser');dest.mkdir(exist_ok=True)
    reports=[]
    try:
        with sync_playwright() as p:
            executable=shutil.which('chromium')
            browser=p.chromium.launch(**({'executable_path':executable} if executable else {}))
            for lang in ('en','id','es','zh'):
                for width in (393,1440):
                    case=fixture.WorkRouteCreditTests('test_real_runner_pauses_renders_localized_consent_and_resumes_provider_once')
                    case.id=lambda:f'synthetic-work-browser-{lang}-{width}'
                    case.setUp()
                    context=None
                    try:
                        with patch.object(image_worker.chat_offering,'for_job',return_value=None),patch.object(image_worker.tools,'image') as provider:
                            case.tick();provider.assert_not_called()
                            client=case.client_for(case.user)
                            context=browser.new_context(viewport={'width':width,'height':900})
                            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}])
                            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                            page.goto(origin+'/kilas-ai/agent/jobs/'+str(case.job),wait_until='networkidle')
                            link=page.locator('[data-credit-work-consent] a');expect(link).to_be_visible()
                            assert page.locator('html').get_attribute('lang')==lang
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(dest/f'work-{lang}-{width}.png'),full_page=True)
                            link.click();page.wait_for_load_state('networkidle')
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(dest/f'consent-{lang}-{width}.png'),full_page=True)
                            page.locator('button[value=approve]').click();expect(page.locator('#credit-consent-result')).to_have_attribute('data-state','APPROVED')
                            provider.assert_not_called()
                            page.get_by_text({'en':'Return to Work','id':'Kembali ke Work','es':'Volver a Work','zh':'返回 Work'}[lang],exact=True).click()
                            page.wait_for_load_state('networkidle');expect(page.locator('[data-credit-work-consent]')).to_have_count(0)
                            page.goto(origin+'/kilas-translator/interpreter',wait_until='networkidle')
                            expect(page.locator('#interpreter')).to_be_visible()
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(dest/f'interpreter-{lang}-{width}.png'),full_page=True)
                            assert not errors,errors
                            reports.append({'language':lang,'width':width,'overflow':False,'consent_no_direct_dispatch':True,'return_to_original_job':True,'interpreter_layout':True,'errors':errors})
                    finally:
                        if context:context.close()
                        current=store.get(case.user,case.job)
                        if current and current['status'] not in store.TERMINAL:store.control(case.user,case.job,'stop')
                        case.doCleanups()
            browser.close()
    finally:server.shutdown()
    (dest/'report.json').write_text(json.dumps(reports,indent=2))
    print('PASS 8 Work/consent/Interpreter language and viewport journeys; no supplier calls')


if __name__=='__main__':main()
