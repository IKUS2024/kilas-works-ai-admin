"""Offline result-card layout and actual streaming/project renderer contracts.

Uses synthetic metadata, existing source templates/assets and system Chromium.
No app DB, login, provider, generation or production mutation is involved.
"""
import json
import os
from pathlib import Path
import unittest
from urllib.parse import urlencode
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get('KILAS_CARD_QA_OUTPUT', '/tmp/kilas-artifact-card-qa'))
FORMATS = ('pdf', 'docx', 'xlsx', 'pptx', 'zip', 'py')
NAME = 'laporan-penjualan-dan-rangkuman-kilas-works-2026-versi-final.'


def url_for(endpoint, **values):
    job, artifact = values.pop('job_id', 9), values.pop('artifact_id', 7)
    suffix = '?' + urlencode(values) if values else ''
    return f'/kilas-ai/agent/jobs/{job}/artifacts/{artifact}' + suffix


class ArtifactCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUTPUT.mkdir(exist_ok=True)
        cls.playwright = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE')
        if not executable and Path('/usr/bin/chromium').exists():
            executable = '/usr/bin/chromium'
        cls.browser = cls.playwright.chromium.launch(executable_path=executable, headless=True)
        cls.translations = json.loads((ROOT / 'locales/ui.json').read_text())
        cls.environment = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape())
        cls.css = '\n'.join((ROOT / 'static' / name).read_text() for name in
            ('kilas_ai.css', 'kilas_ai_agent.css', 'kilas_premium.css', 'kilas_home.css', 'kilas_chat.css', 'kilas_artifacts.css'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def page(self, width=390, language='id'):
        page = self.browser.new_page(viewport={'width': width, 'height': 980})
        self.addCleanup(page.close)
        page.route('**/*', lambda route: route.abort())
        self.translate = lambda key: self.translations.get(key, {}).get(language, key)
        self.environment.globals.update(ui_t=self.translate, url_for=url_for, chat_model_name=lambda value: value)
        page.set_content('<!doctype html><html lang="' + language + '"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="synthetic">'
            '<style>' + self.css + '\nhtml,body{margin:0;background:white;color:#202329}'
            'main.fixture{box-sizing:border-box;max-width:800px;margin:auto;padding:24px 20px}'
            '.fixture .kilas-home-workspace{height:auto}.fixture .ai-message{width:100%}</style>'
            '<body class="kilas-light"><main class="fixture"></main></body></html>')
        page.evaluate('(labels)=>{window.KilasUI={t:key=>labels[key]||key}}',
                      {key: self.translate(key) for key in ('Buka', 'Download', 'KB', 'File hasil', 'Tidak tersedia')})
        page.add_script_tag(content=(ROOT / 'static/kilas_artifacts.js').read_text())
        return page

    def server_card(self, filename, size=43827, url='/saved.pdf'):
        macro = self.environment.get_template('kilas_ai/_artifact_card.html').module.artifact_card
        return str(macro(filename, size, url, '/saved.pdf?inline=1' if filename and filename.endswith('.pdf') else None))

    def test_mobile_tablet_desktop_localization_long_names_and_missing_metadata(self):
        for width in (360, 390, 820, 1440):
            for language in ('id', 'en', 'es', 'zh'):
                with self.subTest(width=width, language=language):
                    page = self.page(width, language)
                    saved = self.server_card('payung-untuk-hari-cerah.pdf')
                    page.locator('main').evaluate('(main,html)=>main.innerHTML=html',
                        '<section class="kilas-home-workspace ai-shell"><article class="ai-message ai-assistant">'
                        '<div class="ai-message-text">PDF siap: Payung untuk Hari Cerah</div>' + saved + '</article></section>')
                    page.evaluate('(formats)=>{for(const ext of formats){document.querySelector("article").append(KilasArtifacts.card({filename:'
                                  + json.dumps(NAME) + '+ext,byte_size:43827,url:"/existing/"+ext}));}'
                                  'document.querySelector("article").append(KilasArtifacts.card({}));}', FORMATS)
                    self.assertEqual(page.locator('.ai-file-kind').all_text_contents(), ['PDF', 'PDF', 'DOCX', 'XLSX', 'PPTX', 'ZIP', 'PY', 'FILE'])
                    self.assertEqual(page.locator('.ai-file-card:last-child a').count(), 0)
                    self.assertEqual(page.locator('.ai-file-unavailable').inner_text(), self.translate('Tidak tersedia'))
                    self.assertNotRegex(page.locator('main').inner_text(), r'NaN|undefined|None')
                    issues = page.evaluate('''()=>{const issues=[];if(document.documentElement.scrollWidth>innerWidth)issues.push('page overflow');
                      for(const card of document.querySelectorAll('.ai-file-card')){
                        const r=card.getBoundingClientRect();for(const child of card.children){const c=child.getBoundingClientRect();if(c.left<r.left||c.right>r.right+1)issues.push('child overflow');}
                        const badge=card.querySelector('.ai-file-kind');if(badge.offsetWidth!==52||badge.offsetHeight!==52||badge.scrollWidth>badge.clientWidth)issues.push('badge');
                        const links=[...card.querySelectorAll('a')];for(const a of links){if(a.getBoundingClientRect().height<44||!a.getAttribute('aria-label'))issues.push('action');}
                        if(links.length===2&&links[0].getBoundingClientRect().right>links[1].getBoundingClientRect().left)issues.push('action overlap');
                      }return issues;}''')
                    self.assertEqual(issues, [])
                    self.assertEqual(page.locator('.ai-file-card').first.locator('a').first.get_attribute('href'), '/saved.pdf?inline=1')
                    self.assertEqual(page.locator('.ai-file-card').first.locator('a').last.get_attribute('href'), '/saved.pdf')
                    page.locator('.ai-file-actions a').first.focus()
                    self.assertEqual(page.locator('.ai-file-actions a').first.evaluate("a=>getComputedStyle(a).outlineStyle"), 'solid')
                    if language == 'id':
                        page.screenshot(path=str(OUTPUT / f'after-{width}.png'), full_page=True)

    def test_work_cards_keep_preview_download_and_verification_metadata(self):
        page = self.page(360)
        artifact = {'name': NAME + 'pdf', 'id': 7, 'job_id': 9, 'media_type': 'application/pdf',
                    'byte_size': None, 'model_provenance': None, 'validation': {'execution': 'not_verified'}}
        markup = self.environment.get_template('kilas_ai/_work_artifact.html').render(artifact=artifact, job={'id': 9})
        page.locator('main').evaluate('(main,html)=>main.innerHTML=html', markup)
        self.assertIn(self.translate('Hasil eksekusi belum terverifikasi.'), page.locator('.work-file-info').inner_text())
        self.assertEqual(page.locator('.work-file-actions a').first.get_attribute('href'), '/kilas-ai/agent/jobs/9/artifacts/7')
        self.assertEqual(page.locator('.work-file-actions a').last.get_attribute('href'), '/kilas-ai/agent/jobs/9/artifacts/7?download=1')
        self.assertEqual(page.locator('.work-file-info>span').inner_text(), 'PDF')
        self.assertTrue(page.locator('details').count())
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 360)

    def test_project_results_use_shared_cards_and_do_not_duplicate_files(self):
        page = self.page()
        page.locator('main').evaluate('main=>main.innerHTML=`<section class="ai-shell"><article class="ai-message"><div class="ai-message-text"></div></article></section>`')
        page.evaluate('''()=>{window.KilasMarkdown={render:(node,text)=>node.textContent=text,finish:()=>{}};
          window.fetch=async()=>new Response(JSON.stringify({state:'COMPLETED',text:'File siap',events:[],files:[{id:7,filename:'landing-page.zip',byte_size:2048,url:'/owned/zip'}]}));}''')
        page.add_script_tag(content=(ROOT / 'static/kilas_thread_projects.js').read_text())
        page.evaluate("async()=>{const body=document.querySelector('.ai-message-text');await KilasThreadProjects.watch({url:'/job'},body);await KilasThreadProjects.watch({url:'/job'},body)}")
        self.assertEqual(page.locator('[data-artifact-id="7"]').count(), 1)
        self.assertEqual(page.locator('.ai-file-kind').inner_text(), 'ZIP')
        self.assertEqual(page.locator('.ai-file-actions a').get_attribute('href'), '/owned/zip')

    def test_streamed_pptx_has_correct_type_and_separate_actions(self):
        page = self.page()
        page.locator('main').evaluate('''main=>main.innerHTML=`<section class="ai-shell" data-thread-id="9"><main class="ai-main"><div class="ai-empty" hidden></div>
          <div id="ai-messages"></div><div id="ai-notice"></div><form id="ai-composer"><textarea id="ai-input">Uji</textarea>
          <button id="ai-send">Kirim</button><button id="ai-stop" hidden>Stop</button><input id="ai-files" type="file"><div id="ai-pending"></div></form>
          <template id="ai-copy-icon"><svg><path></path></svg></template></main></section>`''')
        page.evaluate('''()=>{window.KilasMarkdown={render:(node,text)=>node.textContent=text,stream:(node,text)=>node.textContent+=text,finish:()=>{}};
          const frames='event: delta\\ndata: {"text":"File siap"}\\n\\nevent: file\\ndata: {"filename":"presentasi.pptx","byte_size":1000,"url":"/owned/file?existing=1"}\\n\\nevent: done\\ndata: {}\\n\\n';
          window.fetch=async()=>new Response(frames,{headers:{'Content-Type':'text/event-stream'}});}''')
        page.add_script_tag(content=(ROOT / 'static/kilas_ai.js').read_text())
        page.locator('#ai-composer').evaluate('form=>form.requestSubmit()')
        page.locator('.ai-file-card').wait_for()
        self.assertEqual(page.locator('.ai-file-kind').inner_text(), 'PPTX')
        self.assertEqual(page.locator('.ai-file-actions a').first.get_attribute('href'), '/owned/file?existing=1&inline=1')
        self.assertEqual(page.locator('.ai-file-actions a').last.get_attribute('href'), '/owned/file?existing=1')


if __name__ == '__main__':
    unittest.main()
