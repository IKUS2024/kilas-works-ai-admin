"""Read-only Creative Services on the existing app origin.

The bundled site is generated from ../creative-services-site by
scripts/package_creative_services.py. Render's client-hub root cannot read its parent.
Only the existing CSRF session token is initialized; no entitlement, payment or model state is written.
"""
from pathlib import Path
import json
from flask import make_response, send_from_directory
from security import get_csrf_token
from ui_i18n import language

SITE_ROOT = Path(__file__).resolve().parent / 'creative-services-site'


def creative_services():
    # HttpOnly preferences must be read by the server, never document.cookie.
    context = json.dumps({'language': language(), 'csrfToken': get_csrf_token()}).replace('<', r'\u003c')
    html = (SITE_ROOT / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<!-- creative-app-context -->',
                        '<script id="creative-app-context" type="application/json">' + context + '</script>')
    html = html.replace('<html lang="id">', '<html lang="' + language() + '">', 1)
    response = make_response(html)
    response.headers['Cache-Control'] = 'private, no-store'
    response.vary.add('Cookie')
    return response


def creative_services_asset(filename):
    return send_from_directory(SITE_ROOT / 'assets', filename, max_age=0, conditional=True)
