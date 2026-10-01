"""Owner-only connector setup and explicit action confirmation routes."""
from flask import abort, redirect, request, session, url_for

from . import connector_actions, connectors, google_connection
from .routes import ai_bp, automation_enabled


def _enabled():
    if not automation_enabled():
        abort(404)
    return session["user_id"]  # Existing Kilas AI blueprint gate checks CLIENT_OWNER.


@ai_bp.post("/agent/connections/google/<service>", endpoint="connector_google_begin")
def google_begin(service):
    owner = _enabled()
    try:
        target = google_connection.begin(owner, service, session)
    except connectors.ConnectorError as error:
        return redirect(url_for("kilas_ai.agent_home", view="connections", error=str(error)), code=303)
    return redirect(target, code=303)


@ai_bp.get("/agent/connections/google/callback", endpoint="connector_google_callback")
def google_callback():
    owner = _enabled()
    if request.args.get("error"):
        return redirect(url_for("kilas_ai.agent_home", view="connections", error="oauth_cancelled"), code=303)
    try:
        google_connection.complete(owner, session, request.args.get("state"), request.args.get("code"))
    except connectors.ConnectorError as error:
        return redirect(url_for("kilas_ai.agent_home", view="connections", error=str(error)), code=303)
    pending = session.pop("connector_pending_intent", "")
    return redirect(url_for("kilas_ai.agent_home", view="chat", message=pending[:1200]), code=303)


@ai_bp.post("/agent/connections/google/disconnect", endpoint="connector_google_disconnect")
def google_disconnect():
    owner = _enabled()
    google_connection.disconnect(owner)
    return redirect(url_for("kilas_ai.agent_home", view="connections"), code=303)


@ai_bp.post("/agent/approval/<int:approval_id>/confirm", endpoint="connector_approve")
def approve(approval_id):
    owner = _enabled()
    try:
        connector_actions.execute(owner, approval_id)
    except connectors.ConnectorError as error:
        return redirect(url_for("kilas_ai.agent_home", view="chat", error=str(error)), code=303)
    from . import agent_store
    agent_store.append(owner, "assistant", "Tindakan berhasil dikonfirmasi oleh layanan terkait.")
    return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)


@ai_bp.post("/agent/approval/<int:approval_id>/cancel", endpoint="connector_cancel")
def cancel(approval_id):
    owner = _enabled()
    connectors.cancel_action(owner, approval_id)
    return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)


@ai_bp.post("/agent/approval/<int:approval_id>/edit", endpoint="connector_edit")
def edit(approval_id):
    owner = _enabled()
    row = connectors.approval(owner, approval_id)
    if not row or row["status"] != "PENDING":
        abort(404)
    connectors.cancel_action(owner, approval_id)
    import json
    payload = json.loads(row["payload_json"])
    tool = row["tool"]
    if tool == "gmail.send":
        message = (f"Siapkan email ke {payload.get('to', '')} dengan subjek "
                   f"{payload.get('subject', '')}. Isi: {payload.get('body', '')}")
    elif tool == "whatsapp.send":
        message = f"Siapkan balasan WhatsApp untuk percakapan {row['target']}: {payload.get('text', '')}"
    elif tool.startswith("calendar."):
        message = (f"Siapkan perubahan Calendar {tool.split('.')[-1]} untuk acara "
                   f"{row['target']}: {json.dumps(payload, ensure_ascii=False)}")
    else:
        message = ("Siapkan ulang transaksi Kilas Finance dengan rincian: " +
                   json.dumps(payload, ensure_ascii=False))
    return redirect(url_for("kilas_ai.agent_home", view="chat", message=message[:1200]), code=303)
