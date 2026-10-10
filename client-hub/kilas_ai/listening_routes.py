"""Default-off synthetic listening demo. No capture, storage or provider backend."""
import os
from flask import abort, render_template
from .routes import ai_bp


def enabled():
    return os.environ.get('KILAS_LISTENING_DEMO_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


@ai_bp.get('/listening-demo', endpoint='listening_demo')
def home():
    if not enabled():
        abort(404)
    return render_template('kilas_content/listening.html')
