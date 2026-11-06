"""Localized non-image Work consent/resume and paused issued invoices; synthetic IO."""
import json
import logging
from pathlib import Path
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from credit_browser_tools import launch
from werkzeug.serving import make_server
import test_kilas_credit_work_steps as fixture
from kilas_ai import credit_wallet as wallet
from kilas_ai.agent_workers import content_worker


def main():
    fixture.WorkStepsTests.setUpClass();logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,fixture.WorkStepsTests.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}';dest=Path('/tmp/kilas-credit-work-steps-browser');dest.mkdir(exist_ok=True);reports=[]
    try:
        with sync_playwright() as p:
            browser=launch(p)
            for lang in ('en','id','es','zh'):
                for width in (393,1440):
                    case=fixture.WorkStepsTests('test_multistep_text_consent_completed_steps_and_no_internal_chat_quota');case.id=lambda:f'synthetic-work-step-browser-{lang}-{width}';case.setUp();context=None
                    try:
                        case.add_step()
                        with patch.object(content_worker.requests,'post',return_value=case.response()) as provider:
                            case.tick();provider.assert_not_called()
                            client=case.client_for(case.user);context=browser.new_context(viewport={'width':width,'height':900})
                            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}])
                            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(origin+'/kilas-ai/agent/jobs/'+str(case.job),wait_until='networkidle');page.locator('[data-credit-work-consent] a').click();page.wait_for_load_state('networkidle')
                            expect(page.locator('section h2')).to_have_text('Work');assert page.locator('html').get_attribute('lang')==lang
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(dest/f'work-consent-{lang}-{width}.png'),full_page=True)
                            page.locator('button[value=approve]').click();expect(page.locator('#credit-consent-result')).to_have_attribute('data-state','APPROVED');provider.assert_not_called()
                            case.tick();provider.assert_called_once();assert wallet.balance(case.user)['balance_milli']==1999000
                            invoice=wallet.create_purchase(case.user,'synthetic-paused-invoice')
                            with patch.dict('os.environ',{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
                                page.goto(origin+'/kilas-ai/credits/orders/'+invoice,wait_until='networkidle')
                                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                                expect(page.locator('input[type=file]')).to_be_visible()
                                assert not page.locator('.subscription-bank').count()
                                page.screenshot(path=str(dest/f'issued-paused-{lang}-{width}.png'),full_page=True)
                            assert not errors,errors
                            reports.append({'language':lang,'width':width,'overflow':False,'no_dispatch_before_consent':True,'resume_once':True,'issued_invoice_access_after_rollback':True,'bank_instructions_hidden_while_paused':True,'errors':errors})
                    finally:
                        if context:context.close()
                        case.doCleanups()
            browser.close()
    finally:server.shutdown()
    (dest/'report.json').write_text(json.dumps(reports,indent=2));print('PASS 8 non-image Work/paused invoice language and viewport journeys; synthetic provider only')


if __name__=='__main__':main()
