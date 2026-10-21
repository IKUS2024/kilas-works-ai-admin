"""Loopback-only design preview. No application import, account data or provider calls.

Run: python scripts/preview_credits_usage.py
Open: http://127.0.0.1:8765/kilas-ai/usage
The production route separately renders the same proposal and preserves legacy billing.
"""
from pathlib import Path
import sys

from flask import Flask, redirect, render_template

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ui_i18n


def create_preview():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.config['TESTING'] = True
    ui_i18n.install(app)
    app.jinja_env.globals.update(csrf_token=lambda: 'local-design-only',
                                ui_language_return_path=lambda: '/kilas-ai/usage')

    def page():
        return render_template('kilas_ai/credits_usage_preview.html',
                               home_ai={'history_items': []}, view='settings',
                               kilas_profile_email='Preview account', credits_design_preview=True,
                               ui_messages={})

    app.add_url_rule('/kilas-ai/usage', 'kilas_ai.usage_page', page)

    def preview_link(**kwargs):
        return redirect('/kilas-ai/usage')

    for index, endpoint in enumerate(('products.product_start', 'kilas_ai.home', 'kilas_ai.library',
                                     'client.creative_services', 'kilas_ai.sidebar_history',
                                     'auth.logout_page', 'auth.account_page', 'kilas_ai.agent_new_chat')):
        app.add_url_rule('/preview-link/' + str(index), endpoint, preview_link, methods=['GET', 'POST'])

    return app


if __name__ == '__main__':
    create_preview().run(host='127.0.0.1', port=8765, debug=False)
