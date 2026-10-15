"""Explicit UI localization. Customer text and generated content are never translated."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort, redirect, request, url_for

LANGUAGES = {'id': 'Bahasa Indonesia', 'en': 'English', 'es': 'Español', 'zh': '中文'}
DEFAULT_LANGUAGE = 'en'
CATALOG = json.loads((Path(__file__).parent / 'locales' / 'ui.json').read_text(encoding='utf-8'))
EN_MESSAGES = json.loads((Path(__file__).parent / 'locales' / 'ui_en.json').read_text(encoding='utf-8'))
CLIENT_MESSAGES = json.loads((Path(__file__).parent / 'locales' / 'client.json').read_text(encoding='utf-8'))
# Validation messages with numeric limits. Match only these UI-owned formats;
# never run a general translator over arbitrary request or response values.
_NUMERIC_MESSAGES = (
    'Durasi audio maksimal {value0} detik.',
    'File maksimal {value0} MB.',
    'Saldo tidak cukup. Dibutuhkan {value0}s; saldo tersedia {value1}s.',
    'Saldo tidak cukup. Estimasi {value0}s; perlu mencadangkan hingga {value1}s. Saldo tersedia {value2}s. Sisa reservasi dikembalikan setelah durasi aktual dihitung.',
)
_NUMERIC_PATTERNS = [
    (key, re.compile('^' + re.sub(r'\\\{(value\d+)\\\}',
        lambda match: '(?P<' + match[1] + r'>[0-9]+(?:\.[0-9]+)?)', re.escape(key)) + '$'))
    for key in _NUMERIC_MESSAGES
]


def language():
    value = request.cookies.get('kilas_language', DEFAULT_LANGUAGE)
    return value if value in LANGUAGES else DEFAULT_LANGUAGE


def translate(message, **values):
    message = str(message)
    selected = language()
    result = (EN_MESSAGES.get(message, CATALOG.get(message, {}).get('en', message))
              if selected == 'en' else CATALOG.get(message, {}).get(selected, message))
    for key, value in values.items():
        result = result.replace('{' + key + '}', str(value))
    return result


def translate_ui_message(message):
    result = translate(message)
    if result == message:
        for key, pattern in _NUMERIC_PATTERNS:
            match = pattern.fullmatch(message)
            if match:
                return translate(key, **match.groupdict())
    return result


def install(app):
    # Startup evidence contains configuration counts only, never cookie/user data.
    print('KILAS_UI_LANGUAGE ' + json.dumps({
        'default': DEFAULT_LANGUAGE, 'explicit_cookie': True,
        'supported': list(LANGUAGES), 'english_messages': len(EN_MESSAGES),
        'client_messages': len(CLIENT_MESSAGES),
    }, sort_keys=True))
    app.jinja_env.globals.update(ui_t=translate, ui_language=language, ui_languages=LANGUAGES)
    app.jinja_env.filters['ui_text'] = translate
    def language_return_path():
        from legacy_order_retirement import retired_endpoint
        # Retired pages must not reflect historical request identifiers in a form.
        return (url_for('products.product_start') if retired_endpoint(request.endpoint)
                else request.full_path.rstrip('?'))
    app.jinja_env.globals['ui_language_return_path'] = language_return_path
    # Only designated UI period labels use this filter; no transaction/customer text.
    app.jinja_env.filters['ui_period'] = lambda value: re.sub(
        r'\b(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\b',
        lambda match: translate(match.group()), translate(value))

    @app.context_processor
    def localized_ui():
        # Keep the client catalog limited to explicit UI copy used by scripts;
        # include new audio/status keys without shipping unrelated page copy.
        keys = CLIENT_MESSAGES
        messages = {key: translate(key) for key in keys}
        return {'ui_messages': {key: value for key, value in messages.items() if value != key}}

    @app.after_request
    def localized_ui_response(response):
        # These are application-owned UI fields, never text/script/transcript,
        # source/target language, voice, model output or nested user content.
        if (request.blueprint not in {'kilas_ai', 'kilas_audio'} or response.is_streamed
                or response.headers.get('Content-Disposition')):
            return response
        if response.is_json:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict):
                changed = False
                keys = []
                if response.status_code >= 400 or (payload.get('status') == 'FAILED'
                                                   and isinstance(payload.get('code'), str)):
                    keys.append('error')
                if request.endpoint == 'kilas_audio.status':
                    keys.append('status_label')
                for key in keys:
                    value = payload.get(key)
                    if isinstance(value, str):
                        localized = translate_ui_message(value)
                        if localized != value:
                            payload[key] = localized
                            changed = True
                if changed:
                    response.set_data(app.json.dumps(payload))
                response.vary.add('Cookie')
        elif (response.status_code >= 400 and response.mimetype in {'text/plain', 'text/html'}
              and (response.content_length or 0) <= 2048):
            # A few legacy error handlers return a plain UI sentence. Do not
            # parse or translate HTML fragments, streams or successful content.
            message = response.get_data(as_text=True)
            localized = translate_ui_message(message)
            if localized != message:
                response.set_data(localized)
                response.vary.add('Cookie')
        return response

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
