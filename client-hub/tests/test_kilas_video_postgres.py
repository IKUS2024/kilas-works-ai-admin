"""0082 additive rehearsal and owner/reference/revision preservation on loopback PostgreSQL only."""
import os
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit
if os.environ.get('KILAS_AI_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import video_schema,video_store,usage


def main():
    isolated='video_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    def options():
        values=original();return dict(values,options=values['options']+' -c search_path='+isolated)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith('0082_')]):db.init_schema()
            before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert video_schema.apply_release()==[video_schema.NAME];assert video_schema.apply_release()==[]
            after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after-before=={'kilas_video_projects','kilas_video_revisions','kilas_video_references','kilas_video_releases'}
            from kilas_ai.autonomous_store import transaction
            with transaction() as conn:
                owner=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES('video@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            project=video_store.create(owner,'Synthetic Video QA',{},'video-pg-key-123456789',images=[{'filename':'qa.png','mime_type':'image/png','byte_size':3,'content':b'abc'}])
            assert bytes(video_store.references(owner,project)[0]['content'])==b'abc'
            assert video_store.references(owner+1000,project)==[];assert video_store.get(owner+1000,project) is None
            assert video_store.claim(owner,project,0);assert not video_store.claim(owner,project,0)
            video_store.save(owner,project,0,{'title':'Synthetic Plan'}, {},'Original')
            assert video_store.get(owner,project)['version']==1
            assert video_schema.apply_release()==[]
            assert video_store.get(owner,project)['version']==1
            assert not video_store.claim(owner,project,0)
            for version,subject in [(1,'baju'),(2,'makanan')]:
                assert video_store.claim(owner,project,version)
                brief={'subject':subject,'revision_number':version+1,'revision_kind':'REPLACE_CORE'}
                video_store.save(owner,project,version,{'title':'Arahan '+subject},{'_brief':brief},'Ganti jadi '+subject)
                active=video_store.get(owner,project)
                assert active['title']=='Arahan '+subject and active['version']==version+1
                assert json.loads(active['options_json'])['_brief']==brief
            snapshots=db.query_all('SELECT version,spec_json FROM kilas_video_revisions WHERE project_id=? ORDER BY version',(project,))
            assert [s['version'] for s in snapshots]==[1,2,3]
            assert json.loads(snapshots[-1]['spec_json'])['brief']['subject']=='makanan'
            assert video_store.claim(owner,project,3)
            connected={'title':'Rencana makanan tersambung','continuity_bible':{'subject':'Food on the same plate'},
                       'scenes':[{'title':'Pembuka','purpose':'Tunjukkan makanan','image_prompt':'A still food frame on the same white plate.',
                                  'production_prompt':'Create the first food shot with the same plate.'}],
                       'parts':[{'number':1,'start':0,'end':10,'duration':10,'master_prompt':'Create the first food shot.',
                                 'image_prompt':'A still opening frame of the same food on a white plate.'},
                                {'number':2,'start':10,'end':20,'duration':10,'master_prompt':'Continue the same food shot.',
                                 'image_prompt':'A still close-up frame of the same food on the white plate.'}]}
            brief={'subject':'makanan','revision_number':4,'plan_mode':'multi','clip_timeline':[{'number':1,'start':0,'end':10,'duration':10},{'number':2,'start':10,'end':20,'duration':10}]}
            controls={'plan_mode':'multi','total_duration':'20','clip_strategy':'10','_brief':brief}
            video_store.save(owner,project,3,connected,controls,'Klip tersambung')
            current=video_store.get(owner,project)
            assert current['version']==4 and json.loads(current['spec_json'])==connected
            assert json.loads(current['options_json'])==controls
            latest=db.query_one('SELECT spec_json FROM kilas_video_revisions WHERE project_id=? AND version=4',(project,))
            assert json.loads(latest['spec_json'])=={'plan':connected,'brief':brief}
            assert video_schema.apply_release()==[]
            video_store.delete(owner,project);assert video_store.get(owner,project) is None
            assert db.query_one('SELECT id FROM kilas_video_projects WHERE id=?',(project,))
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()
    print('PASS: PostgreSQL 0082 additive/idempotent/bytea/owner/revision/lease/soft-delete preservation')


if __name__=='__main__':main()
