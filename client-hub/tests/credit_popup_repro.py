"""Synthetic localhost-only popup diagnostic; no application, account or provider."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect


CASES = {'tab': (False, ''), 'popup': (False, 'popup,width=520,height=660'),
         'dialog_popup': (True, 'popup,width=520,height=660')}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        name = urlsplit(self.path).path.removeprefix('/')
        if name == 'approval':
            body = """<!doctype html><h1>Synthetic approval</h1><button id="approve">Approve</button>
<script>approve.onclick=()=>window.opener.postMessage({type:'synthetic-approved'},location.origin)</script>"""
        elif name in CASES:
            modal, features = CASES[name]
            button = '<button id="open">Review charge</button>'
            body = '<!doctype html>' + ('<dialog id="consent">'+button+'</dialog>' if modal else button)
            body += '<script>'+('consent.showModal();' if modal else '')
            body += "document.getElementById('open').onclick=()=>window.open('/approval','kilas-credit-consent',"+json.dumps(features)+");"
            body += "window.addEventListener('message',e=>{if(e.origin===location.origin&&e.data.type==='synthetic-approved')window.approved=true;});</script>"
        else:
            self.send_error(404)
            return
        raw = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def resources():
    result = {'cpu_count': os.cpu_count(), 'shm_bytes': shutil.disk_usage('/dev/shm').total}
    for name in ('memory.max', 'memory.current', 'pids.max', 'pids.current'):
        path = Path('/sys/fs/cgroup')/name
        result[name] = path.read_text().strip() if path.exists() else 'unavailable'
    return result


def main():
    label = os.environ.get('KILAS_CREDIT_REPRO_LABEL', 'guarded')
    assert label in ('guarded', 'standalone')
    output = Path('/tmp/credit-wallet-popup-repro')
    output.mkdir(exist_ok=True)
    report = {'playwright': importlib.metadata.version('playwright'), 'label': label,
              'application_loaded': False, 'provider_calls': 0, 'before': resources(), 'cases': []}
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            for name in CASES:
                browser = None
                row = {'case': name, 'crashes': [], 'ok': False}
                started = time.monotonic()
                try:
                    executable = shutil.which('chromium')
                    browser = playwright.chromium.launch(**({'executable_path': executable} if executable else {'channel': 'chromium'}))
                    report['browser'] = browser.version
                    context = browser.new_context(viewport={'width': 393, 'height': 900})
                    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                    page = context.new_page()
                    page.on('crash', lambda *args, row=row: row['crashes'].append('parent'))
                    page.set_default_timeout(10000)
                    page.goto(origin+'/'+name)
                    with page.expect_popup() as event:
                        page.locator('#open').click()
                    popup = event.value
                    popup.on('crash', lambda *args, row=row: row['crashes'].append('popup'))
                    expect(popup.locator('h1')).to_have_text('Synthetic approval')
                    popup.locator('#approve').click()
                    page.wait_for_function('window.approved===true')
                    assert not row['crashes'], row['crashes']
                    popup.close()
                    row['ok'] = True
                except Exception as error:
                    row['error'] = type(error).__name__+': '+str(error)[:1200]
                finally:
                    row['elapsed_ms'] = round((time.monotonic()-started)*1000)
                    report['cases'].append(row)
                    if browser:
                        try:
                            browser.close()
                        except Exception as error:
                            row['cleanup_error'] = type(error).__name__
    finally:
        server.shutdown()
        server.server_close()
        report['after'] = resources()
        (output/(label+'.json')).write_text(json.dumps(report, indent=2))
        print('CREDIT_POPUP_REPRO '+json.dumps(report), flush=True)
    assert all(row['ok'] for row in report['cases']), report['cases']


if __name__ == '__main__':
    main()
