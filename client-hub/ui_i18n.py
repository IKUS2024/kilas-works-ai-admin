"""Explicit UI localization. Customer text and generated content are never translated."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort, redirect, request, url_for

LANGUAGES = {'id': 'Bahasa Indonesia', 'en': 'English', 'es': 'Español', 'zh': '中文'}
CATALOG = json.loads((Path(__file__).parent / 'locales' / 'ui.json').read_text(encoding='utf-8'))
CLIENT_MESSAGES = json.loads((Path(__file__).parent / 'locales' / 'client.json').read_text(encoding='utf-8'))


def language():
    value = request.cookies.get('kilas_language', 'id')
    return value if value in LANGUAGES else 'id'


def translate(message, **values):
    message = str(message)
    result = CATALOG.get(message, {}).get(language(), message)
    for key, value in values.items():
        result = result.replace('{' + key + '}', str(value))
    return result


def install(app):
    app.jinja_env.globals.update(ui_t=translate, ui_language=language, ui_languages=LANGUAGES)
    app.jinja_env.filters['ui_text'] = translate
    # Only designated UI period labels use this filter; no transaction/customer text.
    app.jinja_env.filters['ui_period'] = lambda value: re.sub(
        r'\b(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\b',
        lambda match: translate(match.group()), translate(value))

    @app.context_processor
    def localized_ui():
        selected = language()
        return {'ui_messages': ({key: CATALOG.get(key, {}).get(selected, key)
                                for key in CLIENT_MESSAGES} if selected != 'id' else {})}

    @app.post('/language')
    def set_ui_language():
        # The existing application CSRF hook protects this preference form too.
        selected = request.form.get('language', '')
        if selected not in LANGUAGES:
            abort(400)
        destination = request.form.get('next', '')
        try:
            parsed = urlsplit(destination)
        except ValueError:
            destination = url_for('products.product_start')
            parsed = urlsplit(destination)
        if (not destination.startswith('/') or destination.startswith('//') or
                parsed.scheme or parsed.netloc or '\\' in destination or
                any(ord(char) < 32 for char in destination)):
            destination = url_for('products.product_start')
        response = redirect(destination, code=303)
        response.set_cookie('kilas_language', selected, max_age=31536000,
                            secure=app.config['SESSION_COOKIE_SECURE'], httponly=True,
                            samesite='Lax')
        return response
