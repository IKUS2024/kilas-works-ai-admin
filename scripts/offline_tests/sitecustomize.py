"""Test-only network isolation inherited by all regression subprocesses."""
import socket
import os

def denied(*args, **kwargs):
    raise OSError('KILAS_OFFLINE_TEST: network disabled; mock external APIs')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
if os.environ.get('KILAS_OFFLINE_ENV_CLEAN') != 'true':
    os.environ['KILAS_OFFLINE_ENV_CLEAN'] = 'true'
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('RENDER', None)
    os.environ.pop('WHATSAPP_APP_SECRET', None)
    os.environ.pop('ENABLE_MULTI_TENANT', None)
    os.environ.pop('ANTHROPIC_API_KEY', None)
    os.environ.pop('WHATSAPP_ACCESS_TOKEN', None)
