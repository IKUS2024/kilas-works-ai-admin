"""Read-only Creative Services on the existing app origin.

The bundled site is generated from ../creative-services-site by
scripts/package_creative_services.py. Render's client-hub root cannot read its parent.
No session, entitlement, payment or model state is written by these handlers.
"""
from pathlib import Path
from flask import send_from_directory

SITE_ROOT = Path(__file__).resolve().parent / 'creative-services-site'


def creative_services():
    return send_from_directory(SITE_ROOT, 'index.html', max_age=0, conditional=True)


def creative_services_asset(filename):
    return send_from_directory(SITE_ROOT / 'assets', filename, max_age=0, conditional=True)
