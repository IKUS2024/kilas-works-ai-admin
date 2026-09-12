"""Production wins if either supported application environment selects it."""
import os

def is_production():
    return any(os.environ.get(key, '').strip().lower() == 'production'
               for key in ('APP_ENV', 'CLIENT_HUB_ENV')) or bool(os.environ.get('RENDER'))
