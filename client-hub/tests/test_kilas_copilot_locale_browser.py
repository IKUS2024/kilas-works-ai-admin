"""EN/ID App Language end-to-end; synthetic mic/provider, no paid calls."""
import json
import logging
import os
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_copilot as fixture
from test_kilas_copilot_browser import FAKE_MIC
from kilas_ai import copilot, audio_provider, translator_languages

TEXT={
 'en':{'badge':'Automatic conversation language','toggle':'Show translation','listen':'Listen','off':'Microphone off','style':'Casual','professional':'Professional','new':'New session','history':'Session history','library':'My Library','products':'Products','creative':'Creative Services','credits':'Credits & Usage','profile':'Profile','language':'App Language','listening':'Listening…','processing':'Recognizing speech…','ready':'Reply ready','reply':'AI-suggested reply','copy':'Copy reply','copied':'Copied','heard':'Speech heard','cancel':'Cancelled.','permission':'Microphone permission was denied.','generate':'Generate Voice Over','voicehistory':'History','start':'Start'},
 'id':{'badge':'Bahasa percakapan otomatis','toggle':'Tampilkan terjemahan','listen':'Dengarkan','off':'Mikrofon mati','style':'Santai','professional':'Profesional','new':'Sesi baru','history':'Riwayat sesi','library':'Pustaka saya','products':'Produk','creative':'Jasa Kreatif','credits':'Kredit & Penggunaan','profile':'Profil','language':'Bahasa aplikasi','listening':'Mendengarkan…','processing':'Mengenali ucapan…','ready':'Jawaban siap','reply':'Saran jawaban AI','copy':'Salin jawaban','copied':'Tersalin','heard':'Ucapan yang didengar','cancel':'Proses dibatalkan.','permission':'Izin mikrofon ditolak.','generate':'Buat Voice Over','voicehistory':'Riwayat','start':'Mulai'}
}
SOURCE='Anda sekolah di mana? Dengarkan.'
REPLY='Saya bersekolah di … (isi sendiri). Dengarkan.'
TRANSLATED='I studied at … (fill in yourself). Show translation.'


def shot(page,**kwargs):
    # Full-page screenshots after auto-scroll can otherwise include offscreen
    # fixed skip links. Capture the normal top-of-page, non-focus presentation.
    page.evaluate('document.activeElement?.blur();window.scrollTo(0,0)')
    page.screenshot(**kwargs)


def apply(page,locale):
    menu=page.locator('body>.premium-mobile-header .kilas-profile-menu')
    if menu.get_attribute('open') is None:menu.locator(':scope>summary').click()
    options=menu.locator('.kilas-profile-language')
    if options.get_attribute('open') is None:options.locator(':scope>summary').click()
    options.locator('select[name=language]').select_option(locale)
    with page.expect_navigation(wait_until='networkidle'):
        options.locator('button[type=submit]').click()
    expect(page.locator('html')).to_have_attribute('lang',locale)


def main():
    case=fixture.CopilotTests();case.setUp()
    server=make_server('127.0.0.1',0,case.app,threaded=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path('/tmp/kilas-copilot-browser');output.mkdir(exist_ok=True)
    gate=threading.Event();gate.set();entered=threading.Event();calls=[]
    def stt(raw):
        calls.append(('stt',None));entered.set();gate.wait(15);return SOURCE
    def answer(system,content,**options):
        calls.append(('translation' if options.get('json_mode') else 'reply',(system,content)))
        if options.get('json_mode'):yield from fixture.answer(json.dumps({'source_translation':'Where did you go to school? Listen.','reply_translation':TRANSLATED}))
        else:yield from fixture.answer(REPLY)
    reports=[]
    try:
        with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',side_effect=stt),patch.object(copilot,'text_stream',side_effect=answer),patch.object(audio_provider,'request',side_effect=AssertionError('Paid provider forbidden')),patch.object(translator_languages,'classic_names',return_value=translator_languages.names(translator_languages.CLASSIC)),sync_playwright() as p:
            executable=os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)
            browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),headless=True,args=['--no-sandbox'])
            for locale in ('en','id'):
                text=TEXT[locale]
                for width,height in ((360,800),(393,850),(1440,1000)):
                    owner=fixture.CopilotTests();owner.setUp();owner.premium();cookie=owner.client.get_cookie('session')
                    context=browser.new_context(viewport={'width':width,'height':height})
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'id' if locale=='en' else 'en','url':origin}])
                    context.add_init_script(FAKE_MIC)
                    context.add_init_script('''
                        window.copiedText=null;window.copyFails=false;
                        Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{if(window.copyFails)throw Error('copy');window.copiedText=text;}}});
                        const original=navigator.mediaDevices.getUserMedia;
                        navigator.mediaDevices.getUserMedia=async options=>{const stream=await original(options);for(const track of stream.getTracks()){const stop=track.stop.bind(track);track.stop=()=>{localStorage.setItem('testStoppedTracks',String(Number(localStorage.getItem('testStoppedTracks')||0)+1));stop();};}return stream;};
                    ''')
                    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                    page.goto(origin+'/kilas-ai',wait_until='networkidle');apply(page,locale)
                    assert next(c for c in context.cookies() if c['name']=='kilas_language')['httpOnly']
                    page.reload(wait_until='networkidle')
                    expect(page.locator('.copilot-language-badge')).to_have_text(text['badge'])
                    expect(page.locator('.copilot-translation span')).to_have_text(text['toggle'])
                    expect(page.locator('#copilot-trigger')).to_have_text(text['listen'])
                    expect(page.locator('#copilot-state')).to_have_text(text['off'])
                    expect(page.locator('[data-copilot-style=santai]')).to_have_text(text['style'])
                    expect(page.locator('[data-copilot-style=profesional]')).to_have_text(text['professional'])
                    assert page.evaluate('micRequests')==0
                    assert page.locator('#copilot-target').input_value()=='id'
                    assert page.locator('body').evaluate('e=>document.documentElement.scrollWidth<=innerWidth')
                    shot(page,path=str(output/f'locale-{locale}-idle-{width}.png'),full_page=True)
                    page.locator('[data-premium-menu]').click()
                    expect(page.locator('#premium-sidebar .ai-new')).to_have_text(text['new'])
                    expect(page.locator('#premium-sidebar .chat-history-toggle')).to_contain_text(text['history'])
                    expect(page.locator('#premium-sidebar .chat-library-entry').first).to_contain_text(text['library'])
                    expect(page.locator('#premium-sidebar .chat-products>summary')).to_contain_text(text['products'])
                    expect(page.locator('#premium-sidebar .chat-products')).to_contain_text(text['creative'])
                    page.locator('#premium-sidebar .kilas-profile-menu>summary').click()
                    expect(page.locator('#premium-sidebar .kilas-profile-menu')).to_contain_text(text['credits'])
                    expect(page.locator('#premium-sidebar .kilas-profile-language>summary')).to_contain_text(text['language'])
                    shot(page,path=str(output/f'locale-{locale}-sidebar-{width}.png'),full_page=False,animations='disabled')
                    page.keyboard.press('Escape')
                    for name,path in (('Translator','/kilas-translator/live?classic=1'),('Native-Translator','/kilas-translator/interpreter'),('Voice-Over','/kilas-translator?mode=voiceover')):
                        page.goto(origin+path,wait_until='networkidle');expect(page.locator('html')).to_have_attribute('lang',locale)
                        assert page.locator('#premium-sidebar,[data-premium-menu]').count()==0
                        assert page.evaluate('micRequests')==0
                        expect(page.locator('body>.premium-mobile-header .kilas-profile-menu>summary')).to_contain_text(text['profile'])
                        if name=='Translator':expect(page.locator('#live-setup-form button[type=submit]')).to_have_text(text['start'])
                        elif name=='Native-Translator':expect(page.locator('#interpreter-start')).to_have_text(text['start'])
                        else:
                            expect(page.locator('#voice-generate')).to_have_text(text['generate'])
                            expect(page.locator('.reference-history-toggle')).to_have_text(text['voicehistory'])
                            expect(page.locator('#dictation-start')).to_contain_text('Record Script' if locale=='en' else 'Rekam Naskah')
                            page.locator('#audio-script').fill('Dengarkan · Show translation · user script')
                            assert page.locator('#audio-script').input_value()=='Dengarkan · Show translation · user script'
                            # Clear the unsaved synthetic draft before navigation.
                            page.locator('#audio-script').fill('')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        shot(page,path=str(output/f'locale-{locale}-{name}-{width}.png'),full_page=True)
                    page.goto(origin+'/kilas-ai',wait_until='networkidle');page.go_back(wait_until='networkidle')
                    expect(page.locator('html')).to_have_attribute('lang',locale);assert page.locator('#premium-sidebar').count()==0
                    page.go_forward(wait_until='networkidle');expect(page.locator('#copilot-state')).to_have_text(text['off'])
                    page.evaluate("micPermission='denied'");page.locator('#copilot-mic').click()
                    expect(page.locator('#copilot-error')).to_contain_text(text['permission'])
                    shot(page,path=str(output/f'locale-{locale}-error-{width}.png'),full_page=True)
                    page.evaluate("micPermission='granted'");before=len(calls)
                    page.locator('#copilot-trigger').click();expect(page.locator('#copilot-state')).to_have_text(text['listening'])
                    page.locator('#copilot-cancel').click();expect(page.locator('#copilot-error')).to_contain_text(text['cancel']);assert len(calls)==before
                    first_frame=page.evaluate('processFrames')
                    page.locator('#copilot-trigger').click();expect(page.locator('#copilot-state')).to_have_text(text['listening'])
                    page.wait_for_function('(before)=>processFrames>before+4',arg=first_frame);assert len(calls)==before
                    shot(page,path=str(output/f'locale-{locale}-listening-{width}.png'),full_page=True)
                    gate.clear();entered.clear();page.locator('#copilot-mic').click()
                    # Pump routed browser requests through Playwright before
                    # waiting on the Python provider-entry synchronization.
                    expect(page.locator('#copilot-state')).to_have_text(text['processing'])
                    assert entered.wait(3)
                    shot(page,path=str(output/f'locale-{locale}-processing-{width}.png'),full_page=True);gate.set()
                    expect(page.locator('#copilot')).to_have_attribute('data-state','idle')
                    expect(page.locator('#copilot-state')).to_have_text(text['ready'])
                    expect(page.locator('.copilot-reply').first).to_have_text(REPLY)
                    expect(page.locator('.copilot-answer-card h3').first).to_have_text(text['reply'])
                    assert page.locator('.copilot-source').count()==0
                    shot(page,path=str(output/f'locale-{locale}-results-off-{width}.png'),full_page=True)
                    page.locator('#copilot-translate').check();page.locator('#copilot-target').select_option('en')
                    frame_before=page.evaluate('processFrames')
                    page.locator('#copilot-trigger').click();page.wait_for_function('(before)=>processFrames>before+4',arg=frame_before);page.locator('#copilot-trigger').click()
                    expect(page.locator('#copilot')).to_have_attribute('data-state','idle')
                    expect(page.locator('.copilot-reply-translation').first).to_have_text(TRANSLATED)
                    expect(page.locator('.copilot-source').first).to_have_text(SOURCE)
                    expect(page.locator('.copilot-source-card h3').first).to_have_text(text['heard'])
                    page.locator('.copilot-copy').first.click();expect(page.locator('.copilot-copy').first).to_have_text(text['copied'])
                    assert page.evaluate('copiedText')==REPLY
                    shot(page,path=str(output/f'locale-{locale}-results-on-{width}.png'),full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.evaluate('copyFails=true');page.locator('.copilot-copy').first.click()
                    expect(page.locator('#copilot-error')).to_contain_text('Unable to copy.' if locale=='en' else 'Belum dapat menyalin.')
                    expect(page.locator('.copilot-reply').first).to_have_text(REPLY)
                    session_url=page.url;page.reload(wait_until='networkidle')
                    expect(page.locator('.copilot-reply')).to_have_count(2)
                    expect(page.locator('.copilot-reply').first).to_have_text(REPLY)
                    assert page.evaluate('micRequests')==0
                    opposite='id' if locale=='en' else 'en';apply(page,opposite)
                    expect(page.locator('#copilot-state')).to_have_text(TEXT[opposite]['off'])
                    expect(page.locator('.copilot-reply').first).to_have_text(REPLY)
                    assert page.url==session_url
                    page.goto(origin+'/kilas-ai',wait_until='networkidle');expect(page.locator('#copilot-trigger')).to_have_text(TEXT[opposite]['listen'])
                    # Applying a UI locale while listening stops the previous mic;
                    # it does not process audio or arm capture on the new page.
                    prior_stops=page.evaluate("Number(localStorage.getItem('testStoppedTracks')||0)")
                    before_apply=len(calls);page.locator('#copilot-trigger').click();expect(page.locator('#copilot')).to_have_attribute('data-state','listening')
                    apply(page,locale);assert page.evaluate('micRequests')==0
                    assert page.evaluate("Number(localStorage.getItem('testStoppedTracks')||0)")>prior_stops
                    assert len(calls)==before_apply
                    assert not errors,errors
                    reports.append({'locale':locale,'width':width,'apply_reload_navigation_sidebar_results_errors_content_and_mic_cleanup':'PASS'})
                    context.close()
            browser.close()
        report={'paid_provider_calls':0,'physical_microphone_calls':0,'cases':reports}
        (output/'locale-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:gate.set();server.shutdown()

if __name__=='__main__':main()
