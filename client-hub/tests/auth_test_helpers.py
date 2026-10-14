"""Create real revocable sessions for disposable actors; never bypass auth middleware."""
import security
from flask import session


def authenticate(client,user,**values):
    with client.application.test_request_context():
        security.login_user(user)
        authenticated=dict(session)
    with client.session_transaction() as state:
        state.clear();state.update(authenticated);state.update(values)
