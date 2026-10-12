"""Turn-local ElevenLabs connection reuse; no cached credit or paid retries."""
from contextlib import contextmanager
from contextvars import ContextVar
import requests

_turn_client = ContextVar('kilas_live_http_client', default=None)


@contextmanager
def turn_connection():
    # A client belongs to one turn, never another owner, thread or later session.
    client = requests.Session()
    token = _turn_client.set(client)
    try:
        yield
    finally:
        _turn_client.reset(token)
        client.close()


def _client(url):
    client = _turn_client.get()
    # Pool only this existing provider origin. Other integrations retain transport.
    return client if client is not None and url.startswith('https://api.elevenlabs.io/') else requests


def get(url, **kwargs):
    return _client(url).get(url, **kwargs)


def post(url, **kwargs):
    return _client(url).post(url, **kwargs)


def request(method, url, **kwargs):
    return _client(url).request(method, url, **kwargs)
