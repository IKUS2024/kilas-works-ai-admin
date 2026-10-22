"""Native PostgreSQL 18 projection with legacy metadata; disposable loopback schema only."""
import os,sys,uuid
from urllib.parse import urlsplit
from pathlib import Path
from unittest.mock import patch
if os.environ.get('KILAS_LIBRARY_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('127.0.0.1','localhost'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask
import db
from kilas_ai import library


def main():
    schema='library_qa_'+uuid.uuid4().hex
    conn=psycopg2.connect(os.environ['DATABASE_URL']);conn.autocommit=True
    def all_rows(query,params=()):
        with conn.cursor(cursor_factory=RealDictCursor) as c:c.execute(query.replace('?','%s'),params);return c.fetchall()
    def one_row(query,params=()):return next(iter(all_rows(query,params)),None)
    app=Flask(__name__)
    for endpoint,path in [('kilas_ai.autonomous_artifact','/jobs/<int:job_id>/files/<int:artifact_id>'),('kilas_ai.attachment_download','/threads/<int:thread_id>/files/<int:attachment_id>'),('kilas_ai.thread_page','/threads/<int:thread_id>')]:app.add_url_rule(path,endpoint,lambda:None)
    try:
        with conn.cursor() as c:
            c.execute('CREATE SCHEMA '+schema);c.execute('SET search_path TO '+schema)
            c.execute('''CREATE TABLE kilas_ai_threads(id bigint,user_id bigint,title text);
            CREATE TABLE kilas_ai_attachments(id bigint,thread_id bigint,user_id bigint,filename text,mime_type text,created_at timestamptz);
            CREATE TABLE kilas_audio_jobs(id bigint,user_id bigint,title text,created_at timestamptz,status text,voice_name text,content_origin text,operation_key text);
            CREATE TABLE kilas_video_projects(id bigint,user_id bigint,title text,updated_at timestamptz,status text,deleted_at timestamptz);
            CREATE TABLE kilas_agent_jobs(id bigint,user_id bigint,title text);
            CREATE TABLE kilas_agent_artifacts(id bigint,job_id bigint,name text,media_type text,created_at timestamptz,content text);
            CREATE TABLE kilas_agent_artifact_files(artifact_id bigint);
            CREATE TABLE kilas_live_translator_sessions(id bigint,user_id bigint);
            CREATE TABLE kilas_live_translator_turns(session_id bigint,audio_job_id bigint,operation_key text);
            INSERT INTO kilas_agent_jobs VALUES(1,10,'Legacy owned'),(2,20,'Foreign');''')
            payloads=['# Legacy Markdown','{broken JSON','{"input":true}','{"input": false}','[]','null']
            for n,content in enumerate(payloads,1):
                c.execute("INSERT INTO kilas_agent_artifacts VALUES(%s,1,%s,'text/plain',now(),%s)",(n,'legacy-'+str(n)+'.txt',content));c.execute('INSERT INTO kilas_agent_artifact_files VALUES(%s)',(n,))
            c.execute("INSERT INTO kilas_agent_artifacts VALUES(20,2,'foreign.txt','text/plain',now(),'# private');INSERT INTO kilas_agent_artifact_files VALUES(20)")
        with patch.object(db,'BACKEND','postgres'),patch.object(db,'query_one',side_effect=one_row),patch.object(db,'query_all',side_effect=all_rows):
            with app.test_request_context('/library'):
                result=library.collection(10,True)
                assert result['total']==5,result
                names={r['name'] for r in result['assets']};assert 'legacy-3.txt' not in names and 'foreign.txt' not in names
            with app.test_request_context('/library?q=legacy-1&type=document'):
                assert library.collection(10,True)['total']==1
            with app.test_request_context('/library?q=%25'):
                assert library.collection(10,True)['total']==0
        print('PASS: native PostgreSQL 18 union, legacy malformed/plain metadata, input/tenant isolation and literal search')
    finally:
        with conn.cursor() as c:c.execute('SET search_path TO public');c.execute('DROP SCHEMA IF EXISTS '+schema+' CASCADE')
        conn.close()


if __name__=='__main__':main()
