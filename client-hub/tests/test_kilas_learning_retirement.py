"""Retired Learning is absent from UI/history; no provider IO or historical purge."""
import unittest
from unittest.mock import patch
from flask import render_template
import test_kilas_audio as fixture
import test_kilas_audio_history as history_fixture
from kilas_ai import learning,learning_store,learning_realtime,providers,audio_store

db=fixture.f.db


class RetirementTests(unittest.TestCase):
 setUp=fixture.AudioTests.setUp
 seed=history_fixture.AudioHistoryTests.seed

 def archived(self,*,owner=None,by_key=False):
  owner=owner or self.user
  ident,_=learning_store.create(owner,'retired-start-synthetic-'+str(owner),'en','id','beginner','kilas-male')
  turn='learn-'+ident+'-greeting';learning_store.claim(owner,ident,turn,'greeting')
  job=self.seed(1,owner)[0]
  db.execute("UPDATE kilas_audio_jobs SET operation_key=?,title='Learning · English',result_content=?,seconds_charged=2 WHERE id=?",(turn+'-audio',b'preserve-historical-audio',job))
  if not by_key:db.execute('UPDATE kilas_learning_turns SET audio_job_id=? WHERE id=?',(job,turn))
  return ident,turn,job

 def test_all_shared_navigation_surfaces_and_refresh_have_no_learning_entry(self):
  with patch.object(providers,'_openai',side_effect=AssertionError('no paid QA')),patch.object(learning,'queue') as paid:
   for path in ('/products/start','/kilas-ai','/kilas-translator?mode=voiceover','/kilas-translator/live','/kilas-ai/library'):
    for _ in range(2):
     response=self.client.get(path,follow_redirects=True)
     self.assertEqual(response.status_code,200,(path,response.status_code))
     self.assertNotIn('href="/kilas-learning',response.text)
     self.assertNotIn('data-home-task="learning"',response.text)
     self.assertNotIn('<span>Learning</span>',response.text)
     self.assertNotIn('data-learning-form',response.text)
   paid.assert_not_called()

 def test_even_old_registered_context_cannot_render_learning_button(self):
  with fixture.f.app.app.test_request_context('/products/start'):
   for navigation in (True,False):
    html=render_template('kilas_ai/_home_task_selector.html',kilas_learning_registered=True,
                         kilas_live_translator_available=True,feature_navigation=navigation,
                         selected_feature='voiceover')
    self.assertNotIn('/kilas-learning',html);self.assertNotIn('<span>Learning</span>',html)
    for label in ('AI Chat','Translator','Voice Over'):self.assertIn('<span>'+label+'</span>',html)
    self.assertNotIn('name="product" value="finance"',html)

 def test_retired_home_cannot_reappear_under_archived_pipeline_reactivation(self):
  with patch.object(learning,'PRODUCT_ACTIVE',True),patch.object(learning,'queue') as paid:
   self.assertEqual(self.client.get('/kilas-learning').status_code,404)
   self.assertEqual(self.client.get('/kilas-learning').status_code,404)
   paid.assert_not_called()

 def test_home_task_and_product_handoffs_cannot_open_learning(self):
  with patch.object(learning,'queue') as paid,patch.object(providers,'_openai') as model:
   self.assertEqual(self.client.post('/kilas-ai/home-task',data={'csrf_token':'audio-csrf','task':'learning'}).status_code,400)
   self.assertEqual(self.client.post('/products/start',data={'csrf_token':'audio-csrf','product':'learning'}).status_code,400)
   paid.assert_not_called();model.assert_not_called()

 def test_all_entry_input_status_and_audio_apis_remain_disabled_despite_old_flags(self):
  self.assertFalse(learning.PRODUCT_ACTIVE)
  ident,turn,job=self.archived();before=dict(db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,)))
  paths=[('POST','/sessions'),('POST','/sessions/'+ident+'/input'),
         ('POST','/sessions/'+ident+'/input/'+turn+'/chunks/0'),
         ('POST','/sessions/'+ident+'/input/'+turn+'/commit'),
         ('GET','/session'),('GET','/sessions/'+ident),
         ('GET','/sessions/'+ident+'/turns/'+turn),('GET','/sessions/'+ident+'/turns/'+turn+'/clips/0')]
  with patch.dict('os.environ',{'KILAS_LEARNING_ENABLED':'true','KILAS_LEARNING_REALTIME_ENABLED':'true'}),patch.object(learning,'queue') as paid,patch.object(learning_realtime.websocket,'create_connection') as socket,patch.object(providers,'_openai') as model:
   for method,path in paths:
    result=self.client.open('/kilas-learning'+path,method=method,data={'csrf_token':'audio-csrf'})
    self.assertEqual(result.status_code,410,path);self.assertEqual(result.json['code'],'learning_disabled')
   paid.assert_not_called();socket.assert_not_called();model.assert_not_called()
  self.assertEqual(dict(db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,))),before)

 def test_history_filters_owned_learning_before_count_and_preserves_title_only_voiceover(self):
  ordinary=self.seed(5);db.execute("UPDATE kilas_audio_jobs SET title='Learning · English' WHERE id=?",(ordinary[0],))
  _,_,retired=self.archived()
  first=audio_store.history_page(self.user)
  self.assertEqual(first['history_total'],5);self.assertEqual(first['history_page_count'],2)
  self.assertNotIn(retired,[r['id'] for r in first['history']])
  ids=[r['id'] for p in (1,2) for r in audio_store.history_page(self.user,p,through=first['history_anchor'])['history']]
  self.assertEqual(ids,list(reversed(ordinary)))
  self.assertFalse(audio_store.is_learning_output(self.user,ordinary[0]))
  self.assertEqual(self.client.get('/kilas-translator/jobs/'+str(ordinary[0])).status_code,200)

 def test_derived_owned_turn_key_hides_output_even_before_audio_link_was_written(self):
  _,_,job=self.archived(by_key=True)
  self.assertTrue(audio_store.is_learning_output(self.user,job))
  self.assertEqual(audio_store.history_page(self.user)['history_total'],0)

 def test_standalone_audio_without_learning_tables_remains_supported(self):
  for backend,row in (('sqlite',{'n':0}),('sqlite',{'n':1}),('postgres',{'present':False})):
   with self.subTest(backend=backend,row=row),patch.object(db,'BACKEND',backend),patch.object(db,'query_one',return_value=row) as query:
    self.assertEqual(audio_store.learning_output_clause(),'(0=1)')
    self.assertNotIn('FROM kilas_learning',query.call_args.args[0])

 def test_foreign_learning_relation_cannot_hide_an_ordinary_owned_voiceover(self):
  job=self.seed(1)[0]
  ident,_=learning_store.create(self.other,'retired-foreign-start','en','id','beginner','kilas-male')
  turn='learn-'+ident+'-greeting';learning_store.claim(self.other,ident,turn,'greeting')
  db.execute('UPDATE kilas_learning_turns SET audio_job_id=? WHERE id=?',(job,turn))
  self.assertFalse(audio_store.is_learning_output(self.user,job));self.assertEqual(audio_store.history_page(self.user)['history_total'],1)

 def test_generic_saved_job_entry_download_edit_and_status_are_blocked_without_data_loss(self):
  _,_,job=self.archived();before=dict(db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,)))
  with patch.object(providers,'_openai',side_effect=AssertionError('no regeneration')),patch.object(learning,'speech',side_effect=AssertionError('no regeneration')):
   for suffix in ('','/status','/script','/result','/reconstruct-script'):
    result=self.client.get('/kilas-translator/jobs/'+str(job)+suffix)
    self.assertEqual(result.status_code,404,suffix)
   result=self.client.post('/kilas-translator/jobs/'+str(job)+'/reconstruct-script',data={'csrf_token':'audio-csrf'})
   self.assertEqual(result.status_code,404)
  self.assertEqual(dict(db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,))),before)
  self.assertEqual(db.query_one('SELECT result_content FROM kilas_audio_jobs WHERE id=?',(job,))['result_content'],b'preserve-historical-audio')


if __name__=='__main__':unittest.main()
