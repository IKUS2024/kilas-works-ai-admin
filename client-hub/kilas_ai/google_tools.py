"""Fixed Google API adapters. No user-supplied URL is ever fetched."""
import base64
import io
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

import requests

from . import connectors, google_connection


class ProviderError(connectors.ConnectorError):
    pass


HOSTS = {
    "gmail": "https://gmail.googleapis.com/gmail/v1/users/me",
    "calendar": "https://www.googleapis.com/calendar/v3",
    "drive": "https://www.googleapis.com/drive/v3",
    "people": "https://people.googleapis.com/v1",
}
IDS = re.compile(r"[A-Za-z0-9_-]{1,180}\Z")


def _id(value):
    value = str(value or "")
    if not IDS.fullmatch(value):
        raise ProviderError("invalid_target")
    return value


def _request(user_id, tool, family, method, path, *, params=None, body=None, text=False):
    gate = connectors.authorize(user_id, tool)
    scope = connectors.TOOLS[tool][2]
    if gate["provider"] != "GOOGLE" or family not in HOSTS or not path.startswith("/") or ".." in path:
        raise ProviderError("invalid_tool")
    token = google_connection.access_token(user_id, scope)
    try:
        response = requests.request(method, HOSTS[family] + path,
            headers={"Authorization": "Bearer " + token}, params=params, json=body,
            timeout=(5, 18), allow_redirects=False)
    except requests.RequestException:
        raise ProviderError("provider_unavailable") from None
    if response.status_code == 401:
        raise ProviderError("reauth_required")
    if response.status_code == 403:
        raise ProviderError("permission_missing")
    if response.status_code == 404:
        raise ProviderError("invalid_target")
    if response.status_code == 429:
        raise ProviderError("rate_limited")
    if response.status_code < 200 or response.status_code >= 300:
        raise ProviderError("provider_unavailable" if response.status_code >= 500 else "provider_rejected")
    if len(response.content) > 10 * 1024 * 1024:
        raise ProviderError("content_too_large")
    if text:
        return response.content
    try:
        return response.json() if response.content else {}
    except ValueError:
        raise ProviderError("provider_invalid_response") from None


def gmail_search(user_id, query):
    query = str(query or "").strip()[:300]
    if not query:
        raise ProviderError("query_required")
    result = _request(user_id, "gmail.search", "gmail", "GET", "/messages",
                      params={"q": query, "maxResults": 10})
    messages = []
    for item in (result.get("messages") or [])[:10]:
        message = _request(user_id, "gmail.search", "gmail", "GET", "/messages/" + _id(item.get("id")),
                           params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
        headers = {h.get("name", "").lower(): h.get("value", "")[:300]
                   for h in (message.get("payload") or {}).get("headers") or []}
        messages.append({"id": message.get("id"), "thread_id": message.get("threadId"),
                         "from": headers.get("from", ""), "subject": headers.get("subject", ""),
                         "date": headers.get("date", ""), "snippet": str(message.get("snippet") or "")[:400]})
    return messages


def gmail_thread(user_id, thread_id):
    result = _request(user_id, "gmail.thread", "gmail", "GET", "/threads/" + _id(thread_id),
                      params={"format": "full"})
    output = []
    for message in (result.get("messages") or [])[-12:]:
        headers = {h.get("name", "").lower(): h.get("value", "")[:300]
                   for h in (message.get("payload") or {}).get("headers") or []}
        output.append({"id": message.get("id"), "from": headers.get("from", ""),
                       "to": headers.get("to", ""), "subject": headers.get("subject", ""),
                       "date": headers.get("date", ""), "message_id": headers.get("message-id", ""),
                       "snippet": str(message.get("snippet") or "")[:600]})
    return output


def _raw_email(to, subject, body, *, reply_to=None, references=None):
    if not isinstance(to, str) or not re.fullmatch(r"[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+", to):
        raise ProviderError("invalid_recipient")
    if any("\r" in str(value) or "\n" in str(value) for value in (to, subject, reply_to or "", references or "")):
        raise ProviderError("invalid_header")
    if not 1 <= len(str(body or "")) <= 12000 or not 1 <= len(str(subject or "")) <= 300:
        raise ProviderError("invalid_message")
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["In-Reply-To"] = reply_to
    if references:
        message["References"] = references
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")


def gmail_create_draft(user_id, to, subject, body, thread_id=None):
    raw = _raw_email(to, subject, body)
    payload = {"message": {"raw": raw}}
    if thread_id:
        payload["message"]["threadId"] = _id(thread_id)
    result = _request(user_id, "gmail.draft", "gmail", "POST", "/drafts", body=payload)
    if not result.get("id"):
        raise ProviderError("provider_invalid_response")
    return {"draft_id": result["id"], "thread_id": (result.get("message") or {}).get("threadId")}


def gmail_send(user_id, to, subject, body, thread_id=None, reply_to=None):
    raw = _raw_email(to, subject, body, reply_to=reply_to)
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = _id(thread_id)
    result = _request(user_id, "gmail.send", "gmail", "POST", "/messages/send", body=payload)
    if not result.get("id"):
        raise ProviderError("provider_invalid_response")
    return {"id": result["id"], "thread_id": result.get("threadId")}


def calendar_events(user_id, start, end):
    return (_request(user_id, "calendar.list", "calendar", "GET", "/calendars/primary/events",
            params={"timeMin": start, "timeMax": end, "singleEvents": "true", "orderBy": "startTime",
                    "maxResults": 30}).get("items") or [])[:30]


def calendar_get(user_id, event_id):
    return _request(user_id, "calendar.get", "calendar", "GET",
                    "/calendars/primary/events/" + _id(event_id))


def calendar_freebusy(user_id, start, end):
    result = _request(user_id, "calendar.freebusy", "calendar", "POST", "/freeBusy",
                      body={"timeMin": start, "timeMax": end, "items": [{"id": "primary"}]})
    return ((result.get("calendars") or {}).get("primary") or {}).get("busy") or []


def _event_payload(payload):
    if not isinstance(payload, dict):
        raise ProviderError("invalid_event")
    title = str(payload.get("summary") or "").strip()
    start, end = payload.get("start"), payload.get("end")
    if not 1 <= len(title) <= 200 or not isinstance(start, dict) or not isinstance(end, dict):
        raise ProviderError("invalid_event")
    try:
        first = datetime.fromisoformat(start["dateTime"])
        last = datetime.fromisoformat(end["dateTime"])
    except (KeyError, ValueError, TypeError):
        raise ProviderError("invalid_event") from None
    if not first.tzinfo or not last.tzinfo or last <= first or last - first > timedelta(days=7):
        raise ProviderError("invalid_event")
    return {"summary": title, "start": {"dateTime": first.isoformat()},
            "end": {"dateTime": last.isoformat()},
            "description": str(payload.get("description") or "")[:2000]}


def calendar_create(user_id, payload):
    result = _request(user_id, "calendar.create", "calendar", "POST", "/calendars/primary/events",
                      body=_event_payload(payload))
    if not result.get("id"):
        raise ProviderError("provider_invalid_response")
    return {"id": result["id"], "html_link": result.get("htmlLink")}


def calendar_update(user_id, event_id, payload):
    result = _request(user_id, "calendar.update", "calendar", "PATCH",
                      "/calendars/primary/events/" + _id(event_id), body=_event_payload(payload))
    if not result.get("id"):
        raise ProviderError("provider_invalid_response")
    return {"id": result["id"]}


def calendar_delete(user_id, event_id):
    _request(user_id, "calendar.delete", "calendar", "DELETE",
             "/calendars/primary/events/" + _id(event_id))
    return {"id": event_id}


def drive_search(user_id, query):
    query = str(query or "").strip()[:100]
    if not query:
        raise ProviderError("query_required")
    escaped = query.replace("\\", "\\\\").replace("'", "\\'")
    result = _request(user_id, "drive.search", "drive", "GET", "/files",
                      params={"q": "name contains '" + escaped + "' and trashed = false",
                              "fields": "files(id,name,mimeType,modifiedTime,description,size),nextPageToken",
                              "pageSize": 20})
    return (result.get("files") or [])[:20]


def drive_read(user_id, file_id):
    file_id = _id(file_id)
    meta = _request(user_id, "drive.read", "drive", "GET", "/files/" + file_id,
                    params={"fields": "id,name,mimeType,size,description"})
    mime = meta.get("mimeType")
    if mime == "application/vnd.google-apps.document":
        content = _request(user_id, "drive.read", "drive", "GET", "/files/" + file_id + "/export",
                           params={"mimeType": "text/plain"}, text=True).decode("utf-8", "replace")[:20000]
    elif mime == "application/vnd.google-apps.spreadsheet":
        content = _request(user_id, "drive.read", "drive", "GET", "/files/" + file_id + "/export",
                           params={"mimeType": "text/csv"}, text=True).decode("utf-8", "replace")[:20000]
    elif mime in ("text/plain", "text/csv"):
        content = _request(user_id, "drive.read", "drive", "GET", "/files/" + file_id,
                           params={"alt": "media"}, text=True).decode("utf-8", "replace")[:20000]
    elif mime == "application/pdf":
        from pypdf import PdfReader
        raw = _request(user_id, "drive.read", "drive", "GET", "/files/" + file_id,
                       params={"alt": "media"}, text=True)
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if len(reader.pages) > 30:
            raise ProviderError("content_too_large")
        content = "\n".join((page.extract_text() or "") for page in reader.pages)[:20000]
    else:
        raise ProviderError("unsupported_file_type")
    return {"file": meta, "content": content}


def contacts_search(user_id, query):
    query = str(query or "").strip()[:100]
    if not query:
        raise ProviderError("query_required")
    params = {"query": query, "readMask": "names,emailAddresses,phoneNumbers,organizations", "pageSize": 20}
    _request(user_id, "contacts.search", "people", "GET", "/people:searchContacts",
             params={**params, "query": ""})  # Google's search cache warmup.
    result = _request(user_id, "contacts.search", "people", "GET", "/people:searchContacts", params=params)
    output = []
    for item in (result.get("results") or [])[:20]:
        person = item.get("person") or {}
        output.append({"name": ((person.get("names") or [{}])[0]).get("displayName", ""),
                       "emails": [v.get("value", "") for v in person.get("emailAddresses") or []],
                       "phones": [v.get("value", "") for v in person.get("phoneNumbers") or []],
                       "organizations": [v.get("name", "") for v in person.get("organizations") or []]})
    return output
