"""Focused real Chromium picker/layout QA; no mic, model or audio request."""
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_live_translator as fixture
from kilas_ai import translator_languages as languages, live_gemini as native, live_gemini_pair as pair


def main():
    case=fixture.LiveTranslatorTests('test_pair_consent_voice_owner_and_concurrent_session_checks')
    case.id=lambda:'translator-picker-browser';case.setUp();case.credit(300)
    app=fixture.audio.f.app.app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path('/tmp/kilas-translator-picker-qa');output.mkdir(exist_ok=True)
    report={'paid_calls':0,'microphone_calls':0,'cases':[]}
    try:
        with patch.object(fixture.live,'ready',return_value=True),patch.object(native,'ready',return_value=True),patch.object(pair,'ready',return_value=True),patch.object(fixture.branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'},{'alias':'kilas-female','name':'Kilas Female'}]),patch.object(fixture.audio_provider,'request',side_effect=AssertionError('Provider IO forbidden')),sync_playwright() as pw:
            options={'headless':True}
            if os.environ.get('KILAS_QA_CHROMIUM'):options.update(executable_path=os.environ['KILAS_QA_CHROMIUM'],args=['--no-sandbox'])
            browser=pw.chromium.launch(**options)
            for width,locale in ((320,'en'),(768,'es'),(1440,'id'),(320,'zh')):
                context=browser.new_context(viewport={'width':width,'height':900})
                cookie=case.client.get_cookie('session')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                context.add_init_script("Intl.DisplayNames=class{of(code){return code}};navigator.mediaDevices.getUserMedia=()=>{throw Error('Unexpected microphone access')}")
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                def route(request):
                    if not request.request.url.startswith(origin):request.abort()
                    elif request.request.method!='GET':raise AssertionError('Unexpected mutation')
                    else:request.continue_()
                page.route('**/*',route)
                for path,count in (('/kilas-translator/live?classic=1',83),('/kilas-translator/live/gemini',76)):
                    page.goto(origin+path,wait_until='networkidle')
                    expect(page.locator('.translator-picker')).to_have_count(2)
                    assert page.locator('select[data-translator-language] option').evaluate_all('rows=>rows.every(row=>row.textContent.trim()!==row.value)')
                    assert page.locator('select[name=language_a] option:not([value=auto])').count()==count
                    # Check before touching either picker: recovery must target Start.
                    for control in page.locator('.translator-picker').all():
                        selected=control.locator('select').evaluate('e=>e.selectedOptions[0].textContent')
                        expect(control.locator(':scope > button')).to_have_text(selected)
                        expect(control.locator(':scope > button')).to_be_enabled()
                    expect(page.locator('#live-setup-form button[type=submit]')).to_have_text('Start')
                    assert not page.locator('input[name=consent]').is_checked()
                    assert not page.locator('#live-setup-form').evaluate('e=>e.checkValidity()')
                    # Native browser validation still prevents submission without consent.
                    if page.locator('#live-setup-form button[type=submit]').is_enabled():
                        page.locator('#live-setup-form button[type=submit]').click()
                    assert not page.locator('input[name=consent]').is_checked()
                    if count==83:
                        first=page.locator('.translator-picker').first
                        first.locator(':scope > button').click()
                        first.locator('input').fill({'id':'Deteksi bahasa','en':'Detect language','es':'Detectar idioma','zh':'检测语言'}[locale])
                        first.locator('[role=option]').click()
                        expect(page.locator('select[name=language_a]')).to_have_value('auto')
                        first.locator(':scope > button').click();first.locator('input').fill('in')
                        # Legacy alias remains searchable; the submitted ID stays canonical.
                        first.locator('[role=option]').filter(has_text={'en':'Indonesian','id':'Indonesia','es':'indonesio','zh':'印度尼西亚语'}[locale]).first.click()
                        expect(page.locator('select[name=language_a]')).to_have_value('id')
                        for code in ('oc','or'):
                            first.locator(':scope > button').click();first.locator('input').fill(code)
                            # Code search can match several names; exact catalog option remains readable.
                            assert first.locator('[role=option]').filter(has_text=page.locator('select[name=language_a] option[value='+code+']').text_content()).count()>=1
                            first.locator('input').press('Escape')
                    picker=page.locator('.translator-picker').nth(1)
                    picker.locator(':scope > button').click()
                    search=picker.locator('input[type=search]');expect(search).to_be_visible()
                    search.fill('jv');expect(picker.locator('[role=option]')).to_have_count(1)
                    search.press('Enter');expect(page.locator('select[name=language_b]')).to_have_value('jv')
                    assert page.evaluate("new FormData(document.querySelector('#live-setup-form')).get('language_b')")=='jv'
                    picker.locator(':scope > button').click();search.fill('zzzzzz');expect(picker.locator('[role=status]')).to_be_visible();search.press('Escape')
                    first=page.locator('.translator-picker').first
                    first.locator(':scope > button').click();first.locator('input').fill('jv')
                    expect(first.locator('[role=option]')).to_be_disabled();first.locator('input').press('Escape')
                    assert not page.locator('input[name=consent]').is_checked()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(path,width)
                    picker.locator(':scope > button').click();search.fill('')
                    assert picker.locator('.translator-picker-list').evaluate('e=>e.clientHeight<=230')
                    rect=picker.locator('.translator-picker-popup').bounding_box();assert rect['x']>=0 and rect['x']+rect['width']<=width+1
                    page.screenshot(path=str(output/f'{locale}-{width}-{count}.png'),full_page=True)
                    search.press('Escape')
                    page.reload(wait_until='networkidle')
                    for control in page.locator('.translator-picker').all():
                        selected=control.locator('select').evaluate('e=>e.selectedOptions[0].textContent')
                        expect(control.locator(':scope > button')).to_have_text(selected)
                        expect(control.locator(':scope > button')).to_be_enabled()
                    report['cases'].append({'width':width,'locale':locale,'options':count,'search_code_keyboard_pair_form_consent_layout':'PASS'})
                page.goto(origin+'/kilas-translator?mode=translate',wait_until='networkidle')
                assert page.locator('#translate-panel select[name=language] option').count()==93
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
