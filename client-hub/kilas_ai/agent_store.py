"""Owner-scoped Agent conversation and read-only activity over existing runs."""
import db


def messages(user_id, limit=60):
    limit = max(1, min(int(limit), 100))
    rows = db.query_all(
        "SELECT id,role,content,created_at FROM kilas_ai_agent_messages "
        "WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    return list(reversed(rows))


def append(user_id, role, content):
    if role not in ("user", "assistant"):
        raise ValueError("invalid_agent_role")
    content = str(content or "").strip()
    if not content or len(content) > 2400:
        raise ValueError("invalid_agent_message")
    db.execute("INSERT INTO kilas_ai_agent_messages(user_id,role,content) VALUES (?,?,?)",
               (user_id, role, content))


def activity(user_id, limit=12):
    limit = max(1, min(int(limit), 30))
    return db.query_all(
        "SELECT r.id,r.automation_id,r.status,r.completed_at,r.scheduled_for,r.result_text,"
        "r.error_code,r.unread,a.title,a.automation_type "
        "FROM kilas_automation_runs r JOIN kilas_automations a "
        "ON a.id=r.automation_id AND a.user_id=r.user_id "
        "WHERE r.user_id=? AND a.deleted_at IS NULL AND r.status NOT IN ('QUEUED','RUNNING') "
        "ORDER BY r.id DESC LIMIT ?", (user_id, limit))
