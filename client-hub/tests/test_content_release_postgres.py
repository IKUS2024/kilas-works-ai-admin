"""Opt-in loopback PostgreSQL QA, isolated schema and synthetic records only."""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL = os.environ.get('KILAS_CONTENT_POSTGRES_QA_URL', '')
pytestmark = pytest.mark.skipif(not URL, reason='Disposable loopback PostgreSQL required')


@pytest.fixture
def postgres(monkeypatch):
    import psycopg2
    import psycopg2.extras
    from psycopg2 import sql
    import db
    from kilas_ai import content_schema
    parsed = urlparse(URL)
    assert parsed.hostname in ('127.0.0.1', 'localhost', '::1'), 'Never run this QA against production'
    schema = 'kilas_content_qa_' + uuid.uuid4().hex
    admin = psycopg2.connect(URL)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    prior = getattr(db._local, 'conn', None)
    db._local.conn = None
    monkeypatch.setattr(db, 'BACKEND', 'postgres')
    monkeypatch.setattr(db, 'DATABASE_URL', URL)
    monkeypatch.setattr(db, 'psycopg2', psycopg2, raising=False)
    original = db._postgres_connect_kwargs
    monkeypatch.setattr(db, '_postgres_connect_kwargs', lambda: {**original(), 'options': original()['options'] + ' -c search_path=' + schema})
    conn = db.get_connection()
    with conn.cursor() as cur:
        cur.execute('''CREATE TABLE users(id BIGINT PRIMARY KEY,role TEXT);
            INSERT INTO users VALUES(1,'CLIENT_OWNER'),(2,'CLIENT_OWNER');
            CREATE TABLE kilas_ai_conversations(id BIGINT PRIMARY KEY,user_id BIGINT,title TEXT,archived_at TEXT);
            INSERT INTO kilas_ai_conversations VALUES(1,1,'Synthetic',NULL),(2,2,'Other',NULL);
            CREATE TABLE kilas_ai_threads(id BIGINT PRIMARY KEY,user_id BIGINT,title TEXT);
            CREATE TABLE protected_sentinel(id INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO protected_sentinel VALUES(1,'unchanged');''')
        for name in ('0082_kilas_video_postgres.sql', '0083_kilas_audio_postgres.sql'):
            cur.execute((ROOT / 'migrations' / name).read_text())
        cur.execute("INSERT INTO kilas_video_projects(user_id,title,idea,version,spec_json,operation_key,created_at,updated_at) VALUES(1,'Synthetic','brief',1,%s,'synthetic-video','now','now')", ('{"voice_over":"Source version one"}',))
        cur.execute("INSERT INTO kilas_audio_jobs(user_id,operation_key,fingerprint,mode,title,source_language,target_language,estimated_seconds,reserved_seconds,status,result_content,created_at,updated_at) VALUES(1,'synthetic-audio','fixture','translate','Synthetic','id','en',1,0,'COMPLETED',%s,'now','now')", (b'0000ftypSYNTHETIC',))
    conn.commit()
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', lambda *a, **kw: pytest.fail('External provider attempted'))
    assert content_schema.apply_release() == [content_schema.NAME]
    assert content_schema.apply_release() == []
    try:
        yield db
        assert db.query_one('SELECT value FROM protected_sentinel WHERE id=1')['value'] == 'unchanged'
        assert bytes(db.query_one('SELECT result_content FROM kilas_audio_jobs WHERE id=1')['result_content']) == b'0000ftypSYNTHETIC'
    finally:
        conn.close()
        db._local.conn = prior
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


def test_postgres_projects_revisions_links_and_isolation(postgres):
    from kilas_ai import content_projects as p
    project = p.create(1, 'Synthetic', '', 'project-operation-01')
    assert p.create(1, 'Synthetic', '', 'project-operation-01') == project
    assert p.get(2, project) is None
    assert p.save_script(1, project, 0, 'First', 'script-operation-001') == 1
    assert p.save_script(1, project, 0, 'First', 'script-operation-001') == 1
    with pytest.raises(p.Conflict):
        p.save_script(1, project, 0, 'Stale', 'script-operation-002')
    assert p.save_script(1, project, 1, '', 'script-operation-003', 'video', 1) == 2
    postgres.execute("UPDATE kilas_video_projects SET version=2,spec_json=? WHERE id=1", ('{"voice_over":"New source"}',))
    assert p.script(1, project, 2)['content'] == 'Source version one'
    assert p.script(1, project, 2)['source_version'] == 1
    assert p.target(1, 'audio', 1)['result_is_video'] == 1
    p.link(1, project, 'audio', 1, 2)
    p.link(1, project, 'audio', 1, 2)
    assert len(p.links(1, project)) == 1
    with pytest.raises(LookupError):
        p.target(2, 'audio', 1)


def test_postgres_chat_exact_versions_retry_voice_snapshot_and_cancel(postgres):
    from kilas_ai import chat_content as c, content_projects as p
    recording = c.create_recording(1, 1, 'Synthetic', 'intro', 'record-operation-001', True)
    assert c.create_recording(1, 1, 'Synthetic', 'intro', 'record-operation-001', True) == recording
    with pytest.raises(LookupError):
        c.recording(2, 2, recording)
    assert c.edit_transcript(1, 1, recording, 1, 'Reviewed', 'transcript-op-001') == 2
    assert c.edit_transcript(1, 1, recording, 1, 'Reviewed', 'transcript-op-001') == 2
    with pytest.raises(p.Conflict):
        c.edit_transcript(1, 1, recording, 1, 'Stale', 'transcript-op-002')
    translation = c.run_mock(1, 1, recording, 2, 'translate', 'en', 'translate-op-001')
    assert c.run_mock(1, 1, recording, 2, 'translate', 'en', 'translate-op-001') == translation
    voice = c.run_mock(1, 1, recording, 2, 'voice', 'en', 'voice-operation-001', translation, 'stock_demo')
    assert 'Tidak ada audio' in c.action(1, 1, voice)['output_text']
    project = p.create(1, 'Project', '', 'project-operation-02')
    c.attach_project(1, 1, project)
    snap = c.run_mock(1, 1, recording, 2, 'project_script', 'id', 'snapshot-operation1', expected_project_version=0)
    assert c.run_mock(1, 1, recording, 2, 'project_script', 'id', 'snapshot-operation1', expected_project_version=0) == snap
    assert p.script(1, project, 1)['content'] == 'Reviewed'
    c.cancel(1, 1, translation)
    c.cancel(1, 1, translation)
    assert c.action(1, 1, translation)['status'] == 'CANCELLED'
    with pytest.raises(ValueError):
        c.run_mock(1, 1, recording, 2, 'voice', 'en', 'voice-operation-002', translation, 'stock_demo')


def test_postgres_migration_checksum_guard(postgres):
    from kilas_ai import content_schema
    postgres.execute('UPDATE kilas_content_releases SET checksum=? WHERE name=?', ('synthetic-wrong', content_schema.NAME))
    with pytest.raises(RuntimeError, match='checksum_mismatch'):
        content_schema.apply_release()


def test_postgres_concurrent_retries_create_one_record_and_action(postgres):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from kilas_ai import chat_content as c
    def parallel(call):
        barrier = Barrier(4)
        def worker(_):
            try:
                barrier.wait(timeout=5)
                return call()
            finally:
                conn = getattr(postgres._local, 'conn', None)
                if conn:
                    conn.close()
                postgres._local.conn = None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker, range(4)))
        assert len(set(results)) == 1
        return results[0]
    ident = parallel(lambda: c.create_recording(1, 1, 'Concurrent', 'intro', 'concurrent-record-01', True))
    parallel(lambda: c.run_mock(1, 1, ident, 1, 'translate', 'en', 'concurrent-action-01'))
    assert postgres.query_one('SELECT COUNT(*) AS n FROM kilas_chat_demo_recordings')['n'] == 1
    assert postgres.query_one('SELECT COUNT(*) AS n FROM kilas_chat_demo_actions')['n'] == 1
