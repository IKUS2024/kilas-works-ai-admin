"""Small, explicitly user-scoped Kilas AI persistence boundary."""
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
