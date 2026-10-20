"""Real Chromium source-link rendering, isolated from network and app accounts."""
import os
from pathlib import Path
import shutil
import unittest
from playwright.sync_api import sync_playwright


SCRIPT = Path(os.environ.get('KILAS_MARKDOWN_SCRIPT', Path(__file__).parents[1] / 'static/kilas_ai_markdown.js'))


class SourceLinkBrowserTests(unittest.TestCase):
    def test_exact_provider_destinations_stream_safely(self):
        urls = ['https://example.test/wiki/Ekonomi_(Indonesia)',
                'https://example.test/archive/;edition=2?q=a%20b&empty=&q=c#table-2',
                'https://example.test/signed/?sig=a%2Fb%2Bc&empty=&utm_source=signature-input',
                'https://example.test/nested_(one_(two))']
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox', '--disable-background-networking'])
            context = browser.new_context()
            def route(request):
                if request.request.url == 'https://local.test/':
                    request.fulfill(body='<div id="answer"></div><script src="/markdown.js"></script>', content_type='text/html')
                elif request.request.url == 'https://local.test/markdown.js':
                    request.fulfill(body=SCRIPT.read_text(), content_type='text/javascript')
                else:
                    request.abort()
            context.route('**/*', route)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto('https://local.test/')
            for url in urls:
                with self.subTest(url=url):
                    text = '[Sumber](' + url + '). [Berikut](https://example.test/next)'
                    page.evaluate('''text=>{const node=document.querySelector('#answer'); KilasMarkdown.render(node,'');
                        for(let i=0;i<text.length;i+=7)KilasMarkdown.stream(node,text.slice(i,i+7));
                        KilasMarkdown.finish(node);}''', text)
                    links = page.locator('#answer a')
                    self.assertEqual(links.count(), 2)
                    self.assertEqual(links.nth(0).get_attribute('href'), url)
                    self.assertEqual(links.nth(0).get_attribute('rel'), 'noopener noreferrer nofollow')
                    self.assertEqual(links.nth(1).get_attribute('href'), 'https://example.test/next')
            page.evaluate('''()=>KilasMarkdown.render(document.querySelector('#answer'),
                '[X](javascript:alert(1)) <script>window.injected=1</script> [Y](https://user:password@example.test)')''')
            self.assertEqual(page.locator('#answer a').count(), 0)
            self.assertIsNone(page.evaluate('window.injected'))
            self.assertFalse(errors)
            browser.close()


if __name__ == '__main__':
    unittest.main()
