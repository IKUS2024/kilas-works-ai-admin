"""Exact released-source comparison allowing only the documented app bootstrap."""
import json
import re

MARKER = '<!-- creative-app-context -->'
BOOTSTRAP = re.compile(r'<script id="creative-app-context" type="application/json">([^<]*)</script>')
LANGUAGES = {'id', 'en', 'es', 'zh'}


def verify_released_html(actual, expected, headers, *, app_served, expected_language=None):
    """Return normalized bytes after validating the complete response contract."""
    if not app_served:
        assert actual == expected, 'Standalone HTML differs from maintained source'
        return actual
    source = expected.decode('utf-8')
    html = actual.decode('utf-8')
    assert source.count(MARKER) == 1
    matches = list(BOOTSTRAP.finditer(html))
    assert len(matches) == 1 and MARKER not in html, 'Missing or duplicate app bootstrap'
    context = json.loads(matches[0][1])
    assert isinstance(context, dict) and set(context) == {'language', 'csrfToken'}, 'Unexpected bootstrap fields'
    assert context['language'] in LANGUAGES, 'Invalid app language'
    assert isinstance(context['csrfToken'], str) and re.fullmatch(r'[0-9a-f]{64}', context['csrfToken']), 'Invalid CSRF token'
    if expected_language is not None:
        assert context['language'] == expected_language, 'App language differs from selected preference'
    response_headers = {key.lower(): value for key, value in headers.items()}
    assert {'private', 'no-store'} <= {v.strip().lower() for v in response_headers.get('cache-control', '').split(',')}
    assert 'cookie' in {v.strip().lower() for v in response_headers.get('vary', '').split(',')}
    assert response_headers.get('x-frame-options', '').upper() == 'DENY'
    opening = '<html lang="' + context['language'] + '">'
    assert html.count('<html ') == 1 and html.count(opening) == 1, 'Unexpected document language'
    normalized = html[:matches[0].start()] + MARKER + html[matches[0].end():]
    normalized = normalized.replace(opening, '<html lang="id">', 1)
    assert normalized == source, 'Released HTML differs outside the exact bootstrap and html language'
    return normalized.encode('utf-8')
