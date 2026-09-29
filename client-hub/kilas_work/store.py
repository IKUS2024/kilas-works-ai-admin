"""Private Work conversations, attachments and durable job records."""
import json

import db
from . import sql


def threads(user_id):
    return db.query_all("SELECT id,title,updated_at FROM kilas_work_threads WHERE user_id=? "
                        "ORDER BY updated_at DESC,id DESC LIMIT 50", (user_id,))


def thread(user_id, thread_id):
    return db.query_one("SELECT id,title,created_at,updated_at FROM kilas_work_threads "
                        "WHERE id=? AND user_id=?", (thread_id, user_id))


def messages(user_id, thread_id):
    if not thread(user_id, thread_id):
        return None
    return db.query_all("SELECT m.id,m.role,m.content,m.model,m.metadata_json,m.created_at "
                        "FROM kilas_work_messages m JOIN kilas_work_threads t ON t.id=m.thread_id "
                        "WHERE t.user_id=? AND t.id=? ORDER BY m.id LIMIT 200", (user_id, thread_id))


def create_thread(user_id, title):
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        thread_id = sql.insert_id(conn, "INSERT INTO kilas_work_threads(user_id,title) VALUES (?,?)",
                                  (user_id, (title or "Pekerjaan baru").strip()[:90]))
        conn.commit()
        return thread_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_message(user_id, thread_id, role, content, *, model=None, metadata=None):
    if role not in ("user", "assistant", "activity"):
        raise ValueError("invalid_role")
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        if not sql.one(conn, "SELECT id FROM kilas_work_threads WHERE id=? AND user_id=?",
                       (thread_id, user_id)):
            raise ValueError("thread_not_found")
        message_id = sql.insert_id(conn, "INSERT INTO kilas_work_messages"
                                   "(thread_id,role,content,model,metadata_json) VALUES (?,?,?,?,?)",
                                   (thread_id, role, str(content)[:30000], model,
                                    json.dumps(metadata or {}, ensure_ascii=False)))
        sql.run(conn, "UPDATE kilas_work_threads SET updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                (thread_id, user_id))
        conn.commit()
        return message_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_file(user_id, thread_id, message_id, prepared):
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        if not sql.one(conn, "SELECT id FROM kilas_work_threads WHERE id=? AND user_id=?",
                       (thread_id, user_id)):
            raise ValueError("thread_not_found")
        file_id = sql.insert_id(conn, "INSERT INTO kilas_work_files"
                                "(user_id,thread_id,message_id,filename,mime_type,content,extracted_text) "
                                "VALUES (?,?,?,?,?,?,?)",
                                (user_id, thread_id, message_id, prepared["filename"],
                                 prepared["mime_type"], prepared["content"], prepared.get("extracted_text")))
        conn.commit()
        return file_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def files(user_id, thread_id):
    return db.query_all("SELECT id,message_id,filename,mime_type,created_at FROM kilas_work_files "
                        "WHERE user_id=? AND thread_id=? ORDER BY id", (user_id, thread_id))


def file(user_id, thread_id, file_id):
    return db.query_one("SELECT filename,mime_type,content FROM kilas_work_files "
                        "WHERE user_id=? AND thread_id=? AND id=?", (user_id, thread_id, file_id))


def create_job(user_id, thread_id, goal):
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        if not sql.one(conn, "SELECT id FROM kilas_work_threads WHERE id=? AND user_id=?",
                       (thread_id, user_id)):
            raise ValueError("thread_not_found")
        job_id = sql.insert_id(conn, "INSERT INTO kilas_work_jobs(user_id,thread_id,status,goal) "
                               "VALUES (?,?,'QUEUED',?)", (user_id, thread_id, goal[:12000]))
        conn.commit()
        return job_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def job(user_id, job_id):
    return db.query_one("SELECT id,thread_id,status,goal,checkpoint_json,last_response_id,"
                        "current_url,error_code,created_at,updated_at FROM kilas_work_jobs "
                        "WHERE id=? AND user_id=?", (job_id, user_id))


def jobs(user_id, thread_id):
    return db.query_all("SELECT id,status,goal,current_url,error_code,updated_at FROM kilas_work_jobs "
                        "WHERE user_id=? AND thread_id=? ORDER BY id DESC LIMIT 20", (user_id, thread_id))


def update_job(user_id, job_id, expected_status, new_status, *, checkpoint=None,
               response_id=None, current_url=None, error_code=None):
    allowed = {"QUEUED", "RUNNING", "PAUSED_USER", "PAUSED_QUOTA", "PAUSED_CONFIRM",
               "COMPLETED", "FAILED", "CANCELLED"}
    if expected_status not in allowed or new_status not in allowed:
        raise ValueError("invalid_status")
    conn = sql.connect()
    try:
        sql.lock_user(conn, user_id)
        changed = sql.run(conn, "UPDATE kilas_work_jobs SET status=?,checkpoint_json=?,"
                          "last_response_id=?,current_url=?,error_code=?,updated_at=CURRENT_TIMESTAMP "
                          "WHERE id=? AND user_id=? AND status=?",
                          (new_status, json.dumps(checkpoint or {}, ensure_ascii=False),
                           response_id, current_url, error_code, job_id, user_id, expected_status))
        conn.commit()
        return bool(changed)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
