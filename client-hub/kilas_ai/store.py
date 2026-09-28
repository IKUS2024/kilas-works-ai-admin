"""Small, explicitly user-scoped Kilas AI persistence boundary."""
import json
import db

MODES = frozenset(("FAST", "SMART", "EXPERT"))


def thread(user_id, thread_id):
    return db.query_one("SELECT * FROM kilas_ai_threads WHERE id=? AND user_id=?", (thread_id, user_id))


def list_threads(user_id, limit=50):
    limit = max(1, min(int(limit), 100))
    return db.query_all(
        "SELECT id,title,selected_mode,created_at,updated_at FROM kilas_ai_threads "
        "WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT ?",
        (user_id, limit),
    )


def create_thread(user_id, mode="SMART"):
    if mode not in MODES:
        raise ValueError("invalid_mode")
    return db.insert_returning_id("INSERT INTO kilas_ai_threads(user_id,selected_mode) VALUES (?,?)", (user_id, mode))


def rename_thread(user_id, thread_id, title):
    title = " ".join((title or "").split())[:100]
    if not title:
        raise ValueError("empty_title")
    if not thread(user_id, thread_id):
        return False
    db.execute("UPDATE kilas_ai_threads SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
               (title, thread_id, user_id))
    return True


def delete_thread(user_id, thread_id):
    if not thread(user_id, thread_id):
        return False
    db.execute("DELETE FROM kilas_ai_threads WHERE id=? AND user_id=?", (thread_id, user_id))
    return True


def messages(user_id, thread_id, limit=100):
    if not thread(user_id, thread_id):
        return None
    limit = max(1, min(int(limit), 200))
    rows = db.query_all(
        "SELECT id,role,content,mode,provider,model,operation_key,metadata_json,created_at "
        "FROM kilas_ai_messages WHERE thread_id=? ORDER BY id DESC LIMIT ?", (thread_id, limit))
    return list(reversed(rows))


def context(user_id, thread_id):
    rows = messages(user_id, thread_id, 24)
    if rows is None:
        return None
    bounded = []
    remaining = 20000
    for row in reversed(rows):
        content = row["content"] or ""
        if not content or len(content) > remaining:
            break
        bounded.append({"role": row["role"], "content": content})
        remaining -= len(content)
    return list(reversed(bounded))


def operation(user_id, thread_id, key):
    if not thread(user_id, thread_id):
        return None
    return db.query_one(
        "SELECT * FROM kilas_ai_messages WHERE thread_id=? AND operation_key=?",
        (thread_id, key),
    )


def append_user_once(user_id, thread_id, content, mode, key):
    if not thread(user_id, thread_id):
        return None, False
    existing = operation(user_id, thread_id, key)
    if existing:
        return existing["id"], False
    try:
        message_id = db.insert_returning_id(
            "INSERT INTO kilas_ai_messages(thread_id,role,content,mode,operation_key) VALUES (?,'user',?,?,?)",
            (thread_id, content, mode, key),
        )
    except Exception:
        existing = operation(user_id, thread_id, key)
        if existing:
            return existing["id"], False
        raise
    current = thread(user_id, thread_id)
    if current and current["title"] == "Chat baru":
        title = " ".join(content.split())[:68] or "Chat baru"
        db.execute("UPDATE kilas_ai_threads SET title=?,selected_mode=?,updated_at=CURRENT_TIMESTAMP "
                   "WHERE id=? AND user_id=?", (title, mode, thread_id, user_id))
    else:
        db.execute("UPDATE kilas_ai_threads SET selected_mode=?,updated_at=CURRENT_TIMESTAMP "
                   "WHERE id=? AND user_id=?", (mode, thread_id, user_id))
    return message_id, True


def append_assistant(user_id, thread_id, content, mode, provider, model, key, metadata):
    if not thread(user_id, thread_id):
        return None
    return db.insert_returning_id(
        "INSERT INTO kilas_ai_messages(thread_id,role,content,mode,provider,model,operation_key,metadata_json) "
        "VALUES (?,'assistant',?,?,?,?,?,?)",
        (thread_id, content, mode, provider, model, key + ":assistant", json.dumps(metadata)),
    )
