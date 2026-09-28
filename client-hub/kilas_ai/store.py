"""Small, explicitly user-scoped Kilas AI persistence boundary."""
import json
import hashlib
import secrets
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
        "FROM kilas_ai_messages WHERE thread_id=? AND content<>'' ORDER BY id DESC LIMIT ?", (thread_id, limit))
    return list(reversed(rows))


def context(user_id, thread_id):
    rows = messages(user_id, thread_id, 24)
    if rows is None:
        return None
    bounded = []
    remaining = 20000
    latest_user_id = next((row["id"] for row in reversed(rows) if row["role"] == "user"), None)
    for row in reversed(rows):
        content = row["content"] or ""
        if not content:
            break
        attachments = (attachment_context(user_id, thread_id, row["id"], include_content=row["id"] == latest_user_id)
                       if row["role"] == "user" else [])
        from .attachments import prompt_content
        prompt = prompt_content(content, attachments if row["id"] == latest_user_id else
                                [item for item in attachments if item["extracted_text"]])
        text_size = len(prompt) if isinstance(prompt, str) else len(prompt[0]["text"])
        if text_size > remaining:
            break
        bounded.append({"role": row["role"], "content": prompt})
        remaining -= text_size
    return list(reversed(bounded))


def save_attachments(user_id, thread_id, message_id, prepared):
    if not thread(user_id, thread_id):
        return None
    ids = []
    for item in prepared:
        ids.append(db.insert_returning_id(
            "INSERT INTO kilas_ai_attachments(user_id,thread_id,message_id,filename,mime_type,byte_size,content,extracted_text) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, thread_id, message_id, item["filename"], item["mime_type"],
             item["byte_size"], item["content"], item["extracted_text"])))
    return ids


def attachment(user_id, thread_id, attachment_id):
    return db.query_one("SELECT * FROM kilas_ai_attachments WHERE id=? AND user_id=? AND thread_id=?",
                        (attachment_id, user_id, thread_id))


def attachment_context(user_id, thread_id, message_id, include_content=False):
    content_column = "content" if include_content else "NULL AS content"
    return db.query_all("SELECT filename,mime_type," + content_column + ",extracted_text FROM kilas_ai_attachments "
                        "WHERE user_id=? AND thread_id=? AND message_id=? ORDER BY id LIMIT 5",
                        (user_id, thread_id, message_id))


def attachment_list(user_id, thread_id):
    return db.query_all("SELECT id,message_id,filename,mime_type,byte_size FROM kilas_ai_attachments "
                        "WHERE user_id=? AND thread_id=? ORDER BY id", (user_id, thread_id))


def latest_generated_document(user_id, thread_id):
    row = db.query_one("SELECT a.filename,a.extracted_text FROM kilas_ai_attachments a "
        "JOIN kilas_ai_messages m ON m.id=a.message_id AND m.thread_id=a.thread_id "
        "WHERE a.user_id=? AND a.thread_id=? AND a.mime_type='application/pdf' AND m.role='assistant' "
        "ORDER BY a.id DESC LIMIT 1", (user_id, thread_id))
    return row if row and row["extracted_text"] else None


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


def share_thread(user_id, thread_id):
    if not thread(user_id, thread_id):
        return None
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    db.execute("UPDATE kilas_ai_threads SET share_token_hash=? WHERE id=? AND user_id=?",
               (digest, thread_id, user_id))
    return token


def revoke_share(user_id, thread_id):
    if not thread(user_id, thread_id):
        return False
    db.execute("UPDATE kilas_ai_threads SET share_token_hash=NULL WHERE id=? AND user_id=?",
               (thread_id, user_id))
    return True


def shared_messages(token):
    if not isinstance(token, str) or len(token) > 128:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    selected = db.query_one("SELECT id,title FROM kilas_ai_threads WHERE share_token_hash=?", (digest,))
    if not selected:
        return None
    rows = db.query_all("SELECT role,content FROM kilas_ai_messages WHERE thread_id=? AND content<>'' ORDER BY id LIMIT 200",
                        (selected["id"],))
    return {"title": selected["title"], "messages": rows}


def last_user_message(user_id, thread_id):
    if not thread(user_id, thread_id):
        return None
    return db.query_one("SELECT id,content,mode FROM kilas_ai_messages WHERE thread_id=? AND role='user' "
                        "ORDER BY id DESC LIMIT 1", (thread_id,))


def reserve_regeneration(user_id, thread_id, mode, key):
    if not thread(user_id, thread_id):
        return None, False
    existing = operation(user_id, thread_id, key + ":assistant")
    if existing:
        return existing["id"], False
    try:
        message_id = db.insert_returning_id(
            "INSERT INTO kilas_ai_messages(thread_id,role,content,mode,operation_key,metadata_json) "
            "VALUES (?,'assistant','',?,?,?)",
            (thread_id, mode, key + ":assistant", json.dumps({"status": "pending"})),
        )
        return message_id, True
    except Exception:
        existing = operation(user_id, thread_id, key + ":assistant")
        if existing:
            return existing["id"], False
        raise


def finish_regeneration(user_id, thread_id, message_id, content, provider, model, metadata):
    if not thread(user_id, thread_id):
        return False
    db.execute("UPDATE kilas_ai_messages SET content=?,provider=?,model=?,metadata_json=? "
               "WHERE id=? AND thread_id=?", (content, provider, model, json.dumps(metadata), message_id, thread_id))
    return True
