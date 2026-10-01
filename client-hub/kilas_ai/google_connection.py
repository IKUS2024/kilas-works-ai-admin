"""Google OAuth web-server flow, encrypted credential storage, and bounded token refresh."""
import hashlib
import json
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken

import db
from . import connectors

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
IDENTITY_URL = "https://openidconnect.googleapis.com/v1/userinfo"
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
IDENTITY_SCOPES = ("openid", EMAIL_SCOPE)


def _normalize_scopes(values):
    """Normalize Google aliases so token-response scope checks match requested access."""
    return {EMAIL_SCOPE if scope == "email" else scope for scope in values}


class GoogleError(connectors.ConnectorError):
    pass


def configuration():
    missing = [name for name in ("KILAS_GOOGLE_CLIENT_ID", "KILAS_GOOGLE_CLIENT_SECRET",
                                "KILAS_GOOGLE_REDIRECT_URI", "KILAS_CONNECTOR_ENCRYPTION_KEY")
               if not os.environ.get(name, "").strip()]
    if missing:
        return {"ready": False, "missing": missing}
    uri = os.environ["KILAS_GOOGLE_REDIRECT_URI"].strip()
    if not uri.startswith("https://") and not (uri.startswith("http://127.0.0.1:") or uri.startswith("http://localhost:")):
        return {"ready": False, "missing": ["KILAS_GOOGLE_REDIRECT_URI (HTTPS required)"]}
    try:
        Fernet(os.environ["KILAS_CONNECTOR_ENCRYPTION_KEY"].encode("ascii"))
    except (ValueError, TypeError):
        return {"ready": False, "missing": ["KILAS_CONNECTOR_ENCRYPTION_KEY (invalid)"]}
    return {"ready": True, "missing": []}


def _key():
    if not configuration()["ready"]:
        raise GoogleError("provider_not_configured")
    return Fernet(os.environ["KILAS_CONNECTOR_ENCRYPTION_KEY"].encode("ascii"))


def _encrypt(value):
    return _key().encrypt(json.dumps(value, separators=(",", ":")).encode()).decode("ascii")


def _decrypt(value):
    try:
        return json.loads(_key().decrypt(value.encode("ascii")))
    except (InvalidToken, ValueError, TypeError):
        raise GoogleError("reauth_required") from None


def begin(user_id, service, session):
    if service != "gmail":
        raise GoogleError("unknown_google_service")
    if not configuration()["ready"]:
        raise GoogleError("provider_not_configured")
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    scopes = sorted(set(IDENTITY_SCOPES + connectors.GOOGLE_SCOPES[service]))
    t = connectors.now()
    db.execute("INSERT INTO kilas_ai_oauth_states(state_hash,user_id,provider,scopes_json,expires_at,created_at) "
               "VALUES (?,?,'GOOGLE',?,?,?)",
               (digest, user_id, json.dumps(scopes), connectors.stamp(t + timedelta(minutes=10)), connectors.stamp(t)))
    session["kilas_google_oauth_state"] = digest
    params = {"client_id": os.environ["KILAS_GOOGLE_CLIENT_ID"],
              "redirect_uri": os.environ["KILAS_GOOGLE_REDIRECT_URI"],
              "response_type": "code", "scope": " ".join(scopes), "state": raw,
              "access_type": "offline", "prompt": "consent"}
    return AUTHORIZE_URL + "?" + urlencode(params)


def _token_request(data):
    try:
        response = requests.post(TOKEN_URL, data=data, timeout=(5, 15), allow_redirects=False)
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise GoogleError("provider_unavailable") from None
    if not isinstance(payload, dict):
        raise GoogleError("provider_unavailable")
    if response.status_code != 200 or not payload.get("access_token"):
        raise GoogleError("reauth_required" if payload.get("error") == "invalid_grant" else "provider_unavailable")
    return payload


def complete(user_id, session, raw_state, code):
    digest = hashlib.sha256(str(raw_state or "").encode()).hexdigest()
    if not secrets.compare_digest(str(session.get("kilas_google_oauth_state") or ""), digest):
        raise GoogleError("invalid_oauth_state")
    state = db.query_one("SELECT * FROM kilas_ai_oauth_states WHERE state_hash=? AND user_id=?", (digest, user_id))
    if not state or connectors.usage._as_utc(state["expires_at"]) <= connectors.now() or not code:
        raise GoogleError("invalid_oauth_state")
    session.pop("kilas_google_oauth_state", None)
    db.execute("DELETE FROM kilas_ai_oauth_states WHERE state_hash=? AND user_id=?", (digest, user_id))
    if not configuration()["ready"]:
        raise GoogleError("provider_not_configured")
    token = _token_request({"code": code, "client_id": os.environ["KILAS_GOOGLE_CLIENT_ID"],
                            "client_secret": os.environ["KILAS_GOOGLE_CLIENT_SECRET"],
                            "redirect_uri": os.environ["KILAS_GOOGLE_REDIRECT_URI"],
                            "grant_type": "authorization_code"})
    try:
        response = requests.get(IDENTITY_URL, headers={"Authorization": "Bearer " + token["access_token"]},
                                timeout=(5, 10), allow_redirects=False)
        identity = response.json()
    except (requests.RequestException, ValueError):
        raise GoogleError("provider_unavailable") from None
    if (response.status_code != 200 or not isinstance(identity, dict) or
            not identity.get("sub") or not identity.get("email") or not identity.get("email_verified")):
        raise GoogleError("identity_unverified")
    granted = _normalize_scopes(str(token.get("scope") or "").split())
    requested = _normalize_scopes(json.loads(state["scopes_json"]))
    if not granted or not requested.issubset(granted):
        raise GoogleError("permission_missing")
    old = connectors.google_connection(user_id)
    refresh = token.get("refresh_token")
    if old and old["external_account_id"] == identity["sub"] and old["credential_enc"] and not refresh:
        refresh = _decrypt(old["credential_enc"]).get("refresh_token")
    if not refresh:
        raise GoogleError("reauth_required")
    expires = connectors.now() + timedelta(seconds=max(60, int(token.get("expires_in") or 3600)))
    credential = _encrypt({"access_token": token["access_token"], "refresh_token": refresh})
    t = connectors.stamp()
    db.execute("INSERT INTO kilas_ai_connections "
        "(user_id,business_id,provider,external_account_id,display_identity,status,scopes_json,permission_json,credential_enc,token_expires_at,last_success_at,last_error,created_at,updated_at) "
        "VALUES (?,NULL,'GOOGLE',?,?,'CONNECTED',?,'{}',?,?,?,NULL,?,?) "
        "ON CONFLICT(user_id,provider) DO UPDATE SET external_account_id=excluded.external_account_id,"
        "display_identity=excluded.display_identity,status='CONNECTED',scopes_json=excluded.scopes_json,"
        "credential_enc=excluded.credential_enc,token_expires_at=excluded.token_expires_at,"
        "last_success_at=excluded.last_success_at,last_error=NULL,updated_at=excluded.updated_at",
        (user_id, identity["sub"], identity["email"], json.dumps(sorted(granted)), credential,
         connectors.stamp(expires), t, t, t))
    return connectors.google_connection(user_id)


def access_token(user_id, scope):
    row = connectors.google_connection(user_id)
    if not row or row["status"] != "CONNECTED":
        raise GoogleError("not_connected")
    if scope not in json.loads(row["scopes_json"]):
        raise GoogleError("permission_missing")
    credential = _decrypt(row["credential_enc"])
    if connectors.usage._as_utc(row["token_expires_at"]) > connectors.now() + timedelta(minutes=2):
        return credential["access_token"]
    try:
        token = _token_request({"refresh_token": credential["refresh_token"],
            "client_id": os.environ["KILAS_GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["KILAS_GOOGLE_CLIENT_SECRET"], "grant_type": "refresh_token"})
    except GoogleError as error:
        if str(error) == "reauth_required":
            db.execute("UPDATE kilas_ai_connections SET status='REAUTH_REQUIRED',last_error='reauth_required',updated_at=? "
                       "WHERE id=? AND user_id=?", (connectors.stamp(), row["id"], user_id))
        raise
    credential["access_token"] = token["access_token"]
    if token.get("refresh_token"):
        credential["refresh_token"] = token["refresh_token"]
    expiry = connectors.now() + timedelta(seconds=max(60, int(token.get("expires_in") or 3600)))
    db.execute("UPDATE kilas_ai_connections SET credential_enc=?,token_expires_at=?,last_success_at=?,updated_at=? "
               "WHERE id=? AND user_id=? AND status='CONNECTED'",
               (_encrypt(credential), connectors.stamp(expiry), connectors.stamp(), connectors.stamp(), row["id"], user_id))
    return token["access_token"]


def disconnect(user_id):
    row = connectors.google_connection(user_id)
    if not row:
        return
    try:
        credential = _decrypt(row["credential_enc"]) if row["credential_enc"] else {}
    except GoogleError:
        credential = {}
    db.execute("UPDATE kilas_ai_connections SET status='DISCONNECTED',credential_enc=NULL,scopes_json='[]',"
               "token_expires_at=NULL,updated_at=? WHERE id=? AND user_id=?",
               (connectors.stamp(), row["id"], user_id))
    token = credential.get("refresh_token") or credential.get("access_token")
    if token:
        try:
            requests.post(REVOKE_URL, data={"token": token}, timeout=(5, 10), allow_redirects=False)
        except requests.RequestException:
            pass  # Local permission is already revoked, even if provider revocation is unavailable.
