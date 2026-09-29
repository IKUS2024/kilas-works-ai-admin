"""Account-owned Automation persistence and transactional due-run claims."""
import json
from datetime import datetime, timedelta, timezone

import db
from . import automation_schedule as schedules, usage

ACTIVE_LIMITS = {"FREE": 1, "PLUS": 5, "PRO": 15, "MAX": 50}
RUN_LIMITS = {"FREE": 10, "PLUS": 60, "PRO": 200, "MAX": 500}
MAX_PAGE = 20
MAX_BATCH = 20


class AutomationError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else value


def _lock_user(conn, user_id):
    if db.BACKEND == "postgres":
        usage._query(conn, "SELECT id FROM users WHERE id=? FOR UPDATE", (user_id,), one=True)


def setting(user_id):
    row = db.query_one("SELECT timezone FROM kilas_automation_settings WHERE user_id=?", (user_id,))
    return row["timezone"] if row else "Asia/Jakarta"


def has_setting(user_id):
    return bool(db.query_one("SELECT 1 FROM kilas_automation_settings WHERE user_id=?", (user_id,)))


def unread_count(user_id):
    row = db.query_one("SELECT COUNT(*) AS n FROM kilas_automation_runs r "
                       "JOIN kilas_automations a ON a.id=r.automation_id "
                       "WHERE r.user_id=? AND a.user_id=r.user_id AND a.deleted_at IS NULL AND r.unread=?",
                       (user_id, True if db.BACKEND == "postgres" else 1))
    return row["n"]


def set_timezone(user_id, name):
    name = schedules.validate_timezone(name)
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        usage._query(conn, "INSERT INTO kilas_automation_settings(user_id,timezone) VALUES (?,?) "
                     "ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone,updated_at=CURRENT_TIMESTAMP",
                     (user_id, name))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return name


def _plan_period(conn, user_id, at):
    plan, start, end = usage._plan(conn, user_id, at)
    if plan == "FREE":
        return plan, at - timedelta(days=30), at + timedelta(microseconds=1)
    period_start, period_end = usage._period(plan, start, end, "CHAT", at)
    return plan, period_start, period_end


def usage_summary(user_id):
    at = _now()
    conn = usage._connect()
    try:
        plan, start, end = _plan_period(conn, user_id, at)
        active = usage._query(conn, "SELECT COUNT(*) FROM kilas_automations WHERE user_id=? "
                              "AND status='ACTIVE' AND next_run_at IS NOT NULL AND deleted_at IS NULL", (user_id,), one=True)[0]
        runs = usage._query(conn, "SELECT COUNT(*) FROM kilas_automation_runs r "
                            "JOIN kilas_automations a ON a.id=r.automation_id "
                            "WHERE r.user_id=? AND a.automation_type!='REMINDER' "
                            "AND r.attempt_count>0 AND r.status NOT IN ('SKIPPED_QUOTA','SKIPPED_DUPLICATE') "
                            "AND r.started_at>=? AND r.started_at<?",
                            (user_id, _iso(start), _iso(end)), one=True)[0]
        unread = usage._query(conn, "SELECT COUNT(*) FROM kilas_automation_runs r "
                              "JOIN kilas_automations a ON a.id=r.automation_id "
                              "WHERE r.user_id=? AND a.user_id=r.user_id AND a.deleted_at IS NULL AND r.unread=?",
                              (user_id, True if db.BACKEND == "postgres" else 1), one=True)[0]
        conn.commit()
        return {"plan": plan, "active": active, "active_limit": ACTIVE_LIMITS[plan],
                "runs": runs, "run_limit": RUN_LIMITS[plan], "unread": unread,
                "reset_at": end}
    finally:
        conn.close()


def get(user_id, automation_id):
    return db.query_one("SELECT * FROM kilas_automations WHERE id=? AND user_id=? AND deleted_at IS NULL",
                        (automation_id, user_id))


def list_for_owner(user_id, status="ACTIVE", page=1):
    page = max(1, min(int(page), 10000))
    status_clause = ("AND a.status IN ('PAUSED','PAUSED_QUOTA')" if status == "PAUSED" else
                     "AND EXISTS (SELECT 1 FROM kilas_automation_runs r WHERE r.automation_id=a.id "
                     "AND r.user_id=a.user_id AND r.unread=" + ("TRUE" if db.BACKEND == "postgres" else "1") + ")"
                     if status == "UNREAD" else "AND a.status='ACTIVE'")
    rows = db.query_all("SELECT a.*,(SELECT r.result_text FROM kilas_automation_runs r "
                        "WHERE r.automation_id=a.id AND r.user_id=a.user_id AND r.result_text IS NOT NULL "
                        "ORDER BY r.id DESC LIMIT 1) AS latest_result "
                        "FROM kilas_automations a WHERE a.user_id=? AND a.deleted_at IS NULL " +
                        status_clause + " ORDER BY a.id DESC LIMIT ? OFFSET ?",
                        (user_id, MAX_PAGE + 1, (page - 1) * MAX_PAGE))
    return rows[:MAX_PAGE], len(rows) > MAX_PAGE


def create(user_id, spec):
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        plan = usage._plan(conn, user_id, _now())[0]
        count = usage._query(conn, "SELECT COUNT(*) FROM kilas_automations WHERE user_id=? "
                             "AND status='ACTIVE' AND next_run_at IS NOT NULL AND deleted_at IS NULL", (user_id,), one=True)[0]
        if count >= ACTIVE_LIMITS[plan]:
            raise AutomationError("Batas Automation aktif paketmu tercapai. Jeda yang lain atau tingkatkan paket.")
        row = usage._query(conn, "INSERT INTO kilas_automations(user_id,title,instruction,automation_type,"
                           "timezone,schedule_json,condition_json,next_run_at) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                           (user_id, spec["title"], spec["instruction"], spec["automation_type"],
                            spec["timezone"], json.dumps(spec["schedule"]), json.dumps(spec["condition"]),
                            _iso(spec["next_run_at"])), one=True)
        conn.commit()
        return row[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def edit(user_id, automation_id, spec):
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        row = usage._query(conn, "SELECT status FROM kilas_automations WHERE id=? AND user_id=? "
                           "AND deleted_at IS NULL", (automation_id, user_id), one=True)
        if not row:
            raise AutomationError("Automation tidak ditemukan.")
        next_run = _iso(spec["next_run_at"]) if row[0] != "PAUSED" else None
        usage._query(conn, "UPDATE kilas_automations SET title=?,instruction=?,automation_type=?,timezone=?,"
                     "schedule_json=?,condition_json=?,watch_state_json='{}',next_run_at=?,last_error_code=NULL,"
                     "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND deleted_at IS NULL",
                     (spec["title"], spec["instruction"], spec["automation_type"], spec["timezone"],
                      json.dumps(spec["schedule"]), json.dumps(spec["condition"]), next_run,
                      automation_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_status(user_id, automation_id, action):
    if action not in ("pause", "resume", "delete"):
        raise AutomationError("Aksi Automation tidak dikenal.")
    conn = usage._connect()
    try:
        _lock_user(conn, user_id)
        row = usage._query(conn, "SELECT status,schedule_json,timezone FROM kilas_automations "
                           "WHERE id=? AND user_id=? AND deleted_at IS NULL", (automation_id, user_id), one=True)
        if not row:
            raise AutomationError("Automation tidak ditemukan.")
        if action == "delete":
            usage._query(conn, "UPDATE kilas_automations SET status='PAUSED',next_run_at=NULL,"
                         "deleted_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                         (_iso(_now()), automation_id, user_id))
            usage._query(conn, "UPDATE kilas_automation_runs SET unread=? WHERE automation_id=? AND user_id=?",
                         (False if db.BACKEND == "postgres" else 0, automation_id, user_id))
        elif action == "pause":
            usage._query(conn, "UPDATE kilas_automations SET status='PAUSED',next_run_at=NULL,"
                         "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                         (automation_id, user_id))
        else:
            plan = usage._plan(conn, user_id, _now())[0]
            active = usage._query(conn, "SELECT COUNT(*) FROM kilas_automations WHERE user_id=? "
                                  "AND status='ACTIVE' AND next_run_at IS NOT NULL AND deleted_at IS NULL", (user_id,), one=True)[0]
            if row[0] != "ACTIVE" and active >= ACTIVE_LIMITS[plan]:
                raise AutomationError("Batas Automation aktif paketmu tercapai.")
            next_run = schedules.next_occurrence(json.loads(row[1]), row[2], _now())
            if not next_run:
                raise AutomationError("Jadwal sekali jalan sudah lewat. Ubah jadwal untuk mengaktifkan lagi.")
            usage._query(conn, "UPDATE kilas_automations SET status='ACTIVE',next_run_at=?,last_error_code=NULL,"
                         "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                         (_iso(next_run), automation_id, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def result(user_id, run_id):
    return db.query_one("SELECT r.*,a.title,a.timezone FROM kilas_automation_runs r "
                        "JOIN kilas_automations a ON a.id=r.automation_id "
                        "WHERE r.id=? AND r.user_id=? AND a.user_id=?", (run_id, user_id, user_id))


def results(user_id, automation_id, page=1):
    if not get(user_id, automation_id):
        return None
    page = max(1, min(int(page), 10000))
    return db.query_all("SELECT id,scheduled_for,completed_at,result_text,unread,status "
                        "FROM kilas_automation_runs WHERE automation_id=? AND user_id=? "
                        "AND result_text IS NOT NULL ORDER BY id DESC LIMIT ? OFFSET ?",
                        (automation_id, user_id, MAX_PAGE, (page - 1) * MAX_PAGE))


def mark_read(user_id, run_id):
    flag = False if db.BACKEND == "postgres" else 0
    db.execute("UPDATE kilas_automation_runs SET unread=? WHERE id=? AND user_id=?",
               (flag, run_id, user_id))


def _retry_due(conn, now):
    return usage._query(conn, "SELECT r.id,r.user_id FROM kilas_automation_runs r "
                        "JOIN kilas_automations a ON a.id=r.automation_id "
                        "WHERE r.status='QUEUED' AND r.retry_at<=? AND r.attempt_count<2 "
                        "AND a.status='ACTIVE' AND a.deleted_at IS NULL "
                        "ORDER BY r.retry_at,r.id LIMIT 1", (_iso(now),), one=True)


def claim_due(limit=10, now=None):
    """Claim bounded due occurrences, advancing schedules before provider work."""
    now = now or _now()
    claimed = []
    for _ in range(max(1, min(int(limit), MAX_BATCH))):
        conn = usage._connect()
        try:
            retry = _retry_due(conn, now)
            if retry:
                run_id, user_id = retry
                _lock_user(conn, user_id)
                suffix = " FOR UPDATE OF r SKIP LOCKED" if db.BACKEND == "postgres" else ""
                ready = usage._query(conn, "SELECT r.id FROM kilas_automation_runs r "
                                     "JOIN kilas_automations a ON a.id=r.automation_id "
                                     "WHERE r.id=? AND r.status='QUEUED' AND r.retry_at<=? "
                                     "AND r.attempt_count<2 AND a.status='ACTIVE' AND a.deleted_at IS NULL" + suffix,
                                     (run_id, _iso(now)), one=True)
                if not ready:
                    conn.commit()
                    continue
                usage._query(conn, "UPDATE kilas_automation_runs SET status='RUNNING',attempt_count=attempt_count+1,"
                             "started_at=?,lease_until=?,retry_at=NULL WHERE id=? AND status='QUEUED'",
                             (_iso(now), _iso(now + timedelta(minutes=30)), run_id))
                conn.commit()
                claimed.append(run_id)
                continue
            candidate = usage._query(conn, "SELECT id,user_id FROM kilas_automations "
                               "WHERE status='ACTIVE' AND deleted_at IS NULL "
                               "AND next_run_at<=? ORDER BY next_run_at,id LIMIT 1",
                               (_iso(now),), one=True)
            if not candidate:
                conn.commit()
                break
            _lock_user(conn, candidate[1])
            suffix = " FOR UPDATE SKIP LOCKED" if db.BACKEND == "postgres" else ""
            due = usage._query(conn, "SELECT id,user_id,automation_type,schedule_json,timezone,next_run_at "
                               "FROM kilas_automations WHERE id=? AND status='ACTIVE' AND deleted_at IS NULL "
                               "AND next_run_at<=?" + suffix, (candidate[0], _iso(now)), one=True)
            if not due:
                conn.commit()
                continue
            automation_id, user_id, kind, raw_schedule, zone, scheduled_for = due
            current_plan = usage._plan(conn, user_id, now)[0]
            rank = usage._query(conn, "SELECT COUNT(*) FROM kilas_automations WHERE user_id=? "
                                "AND status='ACTIVE' AND next_run_at IS NOT NULL AND deleted_at IS NULL AND id<=?",
                                (user_id, automation_id), one=True)[0]
            if rank > ACTIVE_LIMITS[current_plan]:
                usage._query(conn, "UPDATE kilas_automations SET status='PAUSED_QUOTA',next_run_at=NULL,"
                             "last_error_code='active_limit' WHERE id=? AND user_id=?",
                             (automation_id, user_id))
                conn.commit()
                continue
            scheduled = usage._as_utc(scheduled_for)
            schedule = json.loads(raw_schedule)
            next_run = (schedules.next_occurrence(schedule, zone, now)
                        if schedule["kind"] != "once" else None)
            usage._query(conn, "UPDATE kilas_automations SET next_run_at=?,last_run_at=?,"
                         "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='ACTIVE'",
                         (_iso(next_run), _iso(now), automation_id, user_id))
            stale = (now - scheduled > timedelta(days=7) if kind == "REMINDER" and schedule["kind"] == "once"
                     else now - scheduled > timedelta(hours=24) if kind == "REMINDER"
                     else now - scheduled > timedelta(hours=2))
            if stale:
                usage._query(conn, "INSERT INTO kilas_automation_runs(automation_id,user_id,scheduled_for,status,"
                             "completed_at,error_code) VALUES (?,?,?,'SKIPPED_DUPLICATE',?,?) "
                             "ON CONFLICT(automation_id,scheduled_for) DO NOTHING",
                             (automation_id, user_id, _iso(scheduled), _iso(now), "missed_window"))
                conn.commit()
                continue
            if kind != "REMINDER":
                plan, start, end = _plan_period(conn, user_id, now)
                count = usage._query(conn, "SELECT COUNT(*) FROM kilas_automation_runs r "
                                     "JOIN kilas_automations a ON a.id=r.automation_id "
                                     "WHERE r.user_id=? AND a.automation_type!='REMINDER' AND r.attempt_count>0 "
                                     "AND r.status NOT IN ('SKIPPED_QUOTA','SKIPPED_DUPLICATE') "
                                     "AND r.started_at>=? AND r.started_at<?",
                                     (user_id, _iso(start), _iso(end)), one=True)[0]
                if count >= RUN_LIMITS[plan]:
                    usage._query(conn, "INSERT INTO kilas_automation_runs(automation_id,user_id,scheduled_for,status,"
                                 "completed_at,error_code) VALUES (?,?,?,'SKIPPED_QUOTA',?,'run_limit') "
                                 "ON CONFLICT(automation_id,scheduled_for) DO NOTHING",
                                 (automation_id, user_id, _iso(scheduled), _iso(now)))
                    usage._query(conn, "UPDATE kilas_automations SET status='PAUSED_QUOTA',last_error_code='run_limit' "
                                 "WHERE id=? AND user_id=?", (automation_id, user_id))
                    conn.commit()
                    continue
            row = usage._query(conn, "INSERT INTO kilas_automation_runs(automation_id,user_id,scheduled_for,status,"
                               "attempt_count,started_at,lease_until) VALUES (?,?,?,'RUNNING',1,?,?) "
                               "ON CONFLICT(automation_id,scheduled_for) DO NOTHING RETURNING id",
                               (automation_id, user_id, _iso(scheduled), _iso(now),
                                _iso(now + timedelta(minutes=30))), one=True)
            conn.commit()
            if row:
                claimed.append(row[0])
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return claimed


def finish_run(run_id, *, status, text=None, metadata=None, usage_metadata=None, error=None, retry=False,
               watch_state=None):
    if status not in ("SUCCEEDED", "FAILED", "SKIPPED_QUOTA"):
        raise ValueError("invalid_run_status")
    conn = usage._connect()
    try:
        row = usage._query(conn, "SELECT automation_id,user_id,attempt_count FROM kilas_automation_runs "
                           "WHERE id=? AND status='RUNNING'", (run_id,), one=True)
        if not row:
            conn.commit()
            return False
        automation_id, user_id, attempts = row
        now = _now()
        again = bool(retry and attempts < 2)
        unread = bool(status == "SUCCEEDED" and text)
        usage._query(conn, "UPDATE kilas_automation_runs SET status=?,result_text=?,result_metadata_json=?,"
                     "usage_metadata_json=?,error_code=?,unread=?,completed_at=?,retry_at=?,lease_until=NULL "
                     "WHERE id=? AND user_id=? AND status='RUNNING'",
                     ("QUEUED" if again else status, (text or "")[:20000] if text else None,
                      json.dumps(metadata or {}), json.dumps(usage_metadata or {}), error,
                      unread if db.BACKEND == "postgres" else int(unread),
                      None if again else _iso(now), _iso(now + timedelta(minutes=1)) if again else None,
                      run_id, user_id))
        if status == "SUCCEEDED":
            usage._query(conn, "UPDATE kilas_automations SET last_success_at=?,last_error_code=NULL,"
                         "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                         (_iso(now), automation_id, user_id))
            if watch_state is not None:
                usage._query(conn, "UPDATE kilas_automations SET watch_state_json=? "
                             "WHERE id=? AND user_id=? AND deleted_at IS NULL",
                             (json.dumps(watch_state), automation_id, user_id))
        elif status == "SKIPPED_QUOTA":
            usage._query(conn, "UPDATE kilas_automations SET status='PAUSED_QUOTA',last_error_code=?,"
                         "updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                         (error or "quota", automation_id, user_id))
        elif not again:
            usage._query(conn, "UPDATE kilas_automations SET last_error_code=?,updated_at=CURRENT_TIMESTAMP "
                         "WHERE id=? AND user_id=?", (error or "temporary", automation_id, user_id))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_for_worker(run_id):
    return db.query_one("SELECT r.*,a.instruction,a.automation_type,a.condition_json,a.watch_state_json,"
                        "a.status AS automation_status,a.deleted_at,a.timezone FROM kilas_automation_runs r "
                        "JOIN kilas_automations a ON a.id=r.automation_id WHERE r.id=?", (run_id,))


def recover_stale(now=None):
    """Recover reminders; fail uncertain provider calls rather than replaying them."""
    now = now or _now()
    rows = db.query_all("SELECT r.id,r.attempt_count,a.automation_type FROM kilas_automation_runs r "
                        "JOIN kilas_automations a ON a.id=r.automation_id "
                        "WHERE r.status='RUNNING' AND r.lease_until<? ORDER BY r.id LIMIT 20", (_iso(now),))
    for row in rows:
        if row["automation_type"] == "REMINDER" and row["attempt_count"] < 2:
            db.execute("UPDATE kilas_automation_runs SET status='QUEUED',retry_at=?,lease_until=NULL "
                       "WHERE id=? AND status='RUNNING'", (_iso(now), row["id"]))
        else:
            finish_run(row["id"], status="FAILED", error="interrupted_unknown")
    return len(rows)
