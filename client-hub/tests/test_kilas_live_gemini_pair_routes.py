"""Two-way HTTP protocol and tenant fences; disposable SQLite, offline only."""
import io
import os
import unittest
from unittest.mock import Mock, patch

import test_kilas_live_gemini as fixture
import test_kilas_audio as audio
from auth_test_helpers import authenticate
from kilas_ai import live_gemini as native, live_gemini_pair as pair, live_gemini_budget as budget
from kilas_ai import live_translator_store as sessions, audio_store
from kilas_ai import audio_routes, audio_branded_voices as branded


class PairRouteTests(unittest.TestCase):
    setUp=fixture.GeminiTests.setUp
    config=fixture.GeminiTests.config
    lifetime=fixture.GeminiTests.lifetime
    shared=fixture.GeminiTests.shared
    login_other=fixture.GeminiTests.login_other
    key=fixture.GeminiTests.key

    def fields(self,**extra):
        return {'csrf_token':'audio-csrf','language_a':'id','language_b':'en',
                'consent':pair.INPUT_MODE,'translation_mode':'two_way',
                'output_order':pair.OUTPUT_ORDER,**extra}

    def create(self,user=None,voice=None):
        owner=self.user if user is None else user
        ident=sessions.create(owner,'id','en',voice or pair.VOICE)
        self.addCleanup(sessions.end,owner,ident)
        return ident

    def assert_disabled_native_default(self):
        with patch.object(audio_routes,'render_template',wraps=audio_routes.render_template) as render,patch.object(branded,'public_choices') as classic_voices,patch.object(native,'connect') as connect,patch.object(pair,'start') as start:
            for path in ('/kilas-translator/live','/kilas-translator?mode=live'):
                response=self.client.get(path,follow_redirects=True)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.request.path,'/kilas-translator/live/gemini')
                self.assertTrue('Translator belum tersedia untuk akun ini.' in response.text)
                self.assertTrue('class="btn" disabled>Start</button>' in response.text)
                self.assertTrue('id="live-setup-form"' not in response.text)
            self.assertTrue(render.call_args_list)
            self.assertTrue(all(call.args[0]=='kilas_translator/gemini.html' for call in render.call_args_list))
            classic_voices.assert_not_called();connect.assert_not_called();start.assert_not_called()

    def test_budget_limited_default_stays_native_for_owner_and_member_without_classic_fallback(self):
        with self.config(),self.shared(KILAS_LIVE_GEMINI_BUDGET_MICRO_USD='500000'):
            # Offline ledger evidence leaves less than one complete pair.
            capability=budget.claim(self.user,'f'*48,self.key(9))
            budget.dispatch(capability);budget.finish(capability,False)
            for owner in (self.user,self.other):
                if owner==self.other:self.login_other()
                self.assertTrue(native.ready(owner))
                self.assertLess(budget.status(owner,streams=2)['remaining_micro_usd'],500000)
                self.assertFalse(pair.ready(owner))
                self.assertIsNone(sessions.active(owner))
                self.assert_disabled_native_default()
                self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,404)
                self.assertIsNone(sessions.active(owner))

    def test_busy_default_without_live_session_stays_native_and_does_not_create_another_operation(self):
        with self.config(),self.shared():
            for owner in (self.user,self.other):
                if owner==self.other:self.login_other()
                else:authenticate(self.client,audio.f.repo.get_user_by_id(owner),_csrf_token='audio-csrf')
                capability=budget.claim(owner,'d'*48,self.key(owner+20))
                try:
                    self.assertTrue(native.ready(owner))
                    self.assertEqual(budget.status(owner,streams=2)['reason'],'already_processing')
                    self.assertFalse(pair.ready(owner))
                    self.assertIsNone(sessions.active(owner))
                    self.assert_disabled_native_default()
                    self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,404)
                    self.assertEqual(audio.f.db.query_one("SELECT COUNT(*) AS n FROM kilas_vo_stt_operations WHERE user_id=? AND status='RESERVED'",(owner,))['n'],1)
                finally:
                    budget.finish(capability,False)

    def test_all_authenticated_roles_receive_accurate_pair_session_schema_without_dispatch(self):
        audio.f.db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,300)',(self.other,))
        with self.config(),self.shared(),patch.object(native,'connect') as connect,patch.object(pair,'start') as start:
            for role in ('CLIENT_MEMBER','MEMBER','KILAS_ADMIN'):
                with self.subTest(role=role):
                    self.login_other(role)
                    response=self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields())
                    self.assertEqual(response.status_code,201)
                    self.assertEqual(response.json['input_mode'],pair.INPUT_MODE)
                    self.assertEqual(response.json['translation_mode'],'two_way')
                    self.assertEqual(response.json['output_order'],pair.OUTPUT_ORDER)
                    self.assertEqual(response.json['streams'],['id','en'])
                    self.assertNotIn('target_language',response.json)
                    self.assertEqual(response.json['max_input_ms'],60000)
                    self.assertEqual(response.json['max_output_ms'],90000)
                    self.assertEqual(response.headers['Cache-Control'],'private, no-store')
                    ident=response.json['session_id']
                    self.assertEqual(audio.f.db.query_one('SELECT voice_alias FROM kilas_live_translator_sessions WHERE id=?',(ident,))['voice_alias'],pair.VOICE)
                    self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,409)
                    for path in ('/kilas-translator','/kilas-translator/history','/kilas-translator/jobs/0?mode=live',
                                 '/kilas-translator/live/gemini/fixtures','/kilas-translator/live?classic=1'):
                        self.assertEqual(self.client.get(path).status_code,404,path)
                    self.assertEqual(self.client.post('/kilas-translator/jobs',data=self.fields()).status_code,404)
                    self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.other,))['n'],0)
            start.assert_not_called();connect.assert_not_called()

    def test_pair_requires_explicit_mode_and_matching_consent_before_session_creation(self):
        with self.config(),self.shared(),patch.object(native,'connect') as connect,patch.object(pair,'start') as start:
            for changed in ({'consent':'gemini-live-v1'}, {'consent':'yes'},
                            {'translation_mode':'one_way'}, {'translation_mode':'unknown'}):
                self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields(**changed)).status_code,400)
            missing=self.fields();missing.pop('translation_mode')
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=missing).status_code,400)
            no_csrf=self.fields();no_csrf.pop('csrf_token')
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=no_csrf).status_code,400)
            self.assertIsNone(sessions.active(self.user))
            start.assert_not_called();connect.assert_not_called()

    def test_progressive_capability_must_match_fresh_consent_before_any_session_or_operation(self):
        with self.config(),self.shared(),patch.object(native,'connect') as connect,patch.object(pair,'start') as start:
            for changed in ({'consent':pair.LEGACY_INPUT_MODE},
                            {'output_order':pair.LEGACY_OUTPUT_ORDER},
                            {'output_order':'unknown'}, {'output_order':''}):
                self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields(**changed)).status_code,400)
            missing=self.fields();missing.pop('output_order')
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=missing).status_code,400)
            self.assertIsNone(sessions.active(self.user))
            for table in ('kilas_audio_jobs','kilas_vo_stt_operations'):
                self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM '+table+' WHERE user_id=?',(self.user,))['n'],0)
            start.assert_not_called();connect.assert_not_called()

    def test_cached_pair_v1_forms_and_turns_keep_legacy_marker_and_full_turn_contract(self):
        audio.f.db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,300)',(self.user,))
        with self.config(),self.shared(),patch.object(native,'connect') as connect:
            for order in (None,pair.LEGACY_OUTPUT_ORDER):
                fields=self.fields(consent=pair.LEGACY_INPUT_MODE)
                if order is None:fields.pop('output_order')
                else:fields['output_order']=order
                response=self.client.post('/kilas-translator/live/gemini/sessions',data=fields)
                self.assertEqual(response.status_code,201)
                self.assertEqual(response.json['input_mode'],pair.LEGACY_INPUT_MODE)
                self.assertEqual(response.json['output_order'],pair.LEGACY_OUTPUT_ORDER)
                ident=response.json['session_id'];key=self.key(7 if order is None else 8)
                row=audio.f.db.query_one('SELECT voice_alias FROM kilas_live_translator_sessions WHERE id=?',(ident,))
                self.assertEqual(row['voice_alias'],pair.LEGACY_VOICE)
                base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+key
                with patch.object(pair.Thread,'start'):
                    response=self.client.post(base,data=self.fields())
                self.assertEqual(response.status_code,202)
                relay=pair.owned(self.user,ident,key)
                try:
                    self.assertFalse(relay.progressive)
                    self.assertEqual(response.json['input_mode'],pair.LEGACY_INPUT_MODE)
                    self.assertEqual(response.json['output_order'],pair.LEGACY_OUTPUT_ORDER)
                    self.assertEqual(relay.frames,[])
                    connect.assert_not_called()
                finally:
                    budget.finish(relay.capability,False)
                    audio_store.fail(self.user,relay.job,'synthetic')
                    sessions.end(self.user,ident);pair.cancel(self.user,ident)
                    native._slots.release();native._slots.release()

    def test_cached_one_way_admission_and_turn_cannot_select_pair_backend(self):
        audio.f.db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,300)',(self.user,))
        old={'csrf_token':'audio-csrf','language_a':'id','language_b':'en','consent':'gemini-live-v1'}
        with self.config(),self.shared(),patch.object(pair,'start') as paired,patch.object(native,'start') as one_way,patch.object(native,'connect') as connect:
            response=self.client.post('/kilas-translator/live/gemini/sessions',data=old)
            self.assertEqual(response.status_code,201)
            self.assertEqual(response.json['input_mode'],'gemini-live-v1')
            self.assertEqual(response.json['translation_mode'],'one_way')
            ident=response.json['session_id'];self.addCleanup(sessions.end,self.user,ident)
            self.assertEqual(audio.f.db.query_one('SELECT voice_alias FROM kilas_live_translator_sessions WHERE id=?',(ident,))['voice_alias'],native.VOICE)
            response=self.client.post('/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+self.key(),data=self.fields())
            self.assertEqual(response.status_code,202)
            self.assertEqual(response.json['input_mode'],'gemini-live-v1')
            one_way.assert_called_once_with(self.user,ident,self.key())
            paired.assert_not_called();connect.assert_not_called()

    def test_pair_turn_backend_and_schema_come_from_owned_session_marker(self):
        ident=self.create();base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+self.key()
        with self.config(),self.shared(),patch.object(pair,'start') as paired,patch.object(native,'start') as one_way,patch.object(native,'connect') as connect:
            response=self.client.post(base,data={'csrf_token':'audio-csrf','translation_mode':'one_way','target_language':'fr'})
            self.assertEqual(response.status_code,202)
            self.assertEqual(response.json,{'status':'LISTENING','input_mode':pair.INPUT_MODE,'translation_mode':'two_way',
                                           'output_order':pair.OUTPUT_ORDER,'streams':['id','en']})
            paired.assert_called_once_with(self.user,ident,self.key())
            one_way.assert_not_called();connect.assert_not_called()

    def test_landing_preserves_existing_one_way_session_and_defaults_new_sessions_to_pair(self):
        with self.config(),self.shared(),patch.object(native,'connect') as connect:
            response=self.client.get('/kilas-translator/live/gemini')
            self.assertTrue('data-gemini-translation-mode="two_way"' in response.text)
            ident=self.create(voice=native.VOICE)
            before=dict(audio.f.db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,)))
            response=self.client.get('/kilas-translator/live/gemini')
            self.assertTrue('data-gemini-translation-mode="one_way"' in response.text)
            self.assertTrue('value="gemini-live-v1"' in response.text)
            self.assertEqual(dict(audio.f.db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,))),before)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
            response=self.client.get('/kilas-translator/live/gemini')
            self.assertTrue('data-gemini-translation-mode="two_way"' in response.text)
            self.assertTrue('value="'+pair.INPUT_MODE+'"' in response.text)
            paired=self.create()
            self.assertEqual(self.client.get('/kilas-translator/live').location,'/kilas-translator/live/gemini')
            self.assertEqual(sessions.status(self.user,paired)['status'],'ACTIVE')
            connect.assert_not_called()

    def test_real_pair_admission_reserves_two_streams_and_one_aggregate_audio_job(self):
        self.login_other()
        audio.f.db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,300)',(self.other,))
        ident=self.create(self.other);key=self.key()
        base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+key
        with self.config(),self.shared(),patch.object(native,'connect') as connect:
            policy=budget.policy()
            with patch.object(pair.Thread,'start'):
                response=self.client.post(base,data={'csrf_token':'audio-csrf'})
            self.assertEqual(response.status_code,202)
            relay=pair.owned(self.other,ident,key)
            try:
                rows=audio.f.db.query_one("SELECT COUNT(*) AS n,SUM(charge_micro) AS total FROM kilas_vo_stt_operations WHERE user_id=? AND status='RESERVED'",(self.other,))
                self.assertEqual((rows['n'],rows['total']),(2,500000))
                job=audio.f.db.query_one('SELECT reserved_seconds,initial_reserved_seconds FROM kilas_audio_jobs WHERE id=? AND user_id=?',(relay.job,self.other))
                self.assertEqual(job['reserved_seconds'],90)
                self.assertEqual(job['initial_reserved_seconds'],90)
                self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.other,))['n'],1)
                second=base.rsplit('/',1)[0]+'/'+self.key(2)
                self.assertIn(self.client.post(second,data={'csrf_token':'audio-csrf'}).status_code,(409,429))
                self.assertEqual(budget.policy(),policy)
                connect.assert_not_called()
            finally:
                budget.finish(relay.capability,False)
                audio_store.fail(self.other,relay.job,'synthetic')
                sessions.end(self.other,ident)
                pair.cancel(self.other,ident)
                native._slots.release();native._slots.release()

    def test_pair_admission_requires_budget_for_both_streams(self):
        with self.config(),self.shared(KILAS_LIVE_GEMINI_BUDGET_MICRO_USD='500000'),patch.object(native,'connect') as connect:
            # Synthetic ledger settlement only: no socket/provider dispatch.
            capability=budget.claim(self.user,'e'*48,self.key(8))
            budget.dispatch(capability);budget.finish(capability,False)
            self.assertTrue(native.ready(self.user))
            self.assertEqual(budget.status(self.user,streams=2)['reserve_micro_usd'],500000)
            self.assertFalse(pair.ready(self.user))
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,404)
            self.assertIsNone(sessions.active(self.user))
            connect.assert_not_called()

    def test_owned_pair_poll_chunk_and_finish_use_pair_relay(self):
        ident=self.create();key=self.key();base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+key
        relay=Mock();relay.snapshot.return_value={'input_mode':pair.INPUT_MODE,'translation_mode':'two_way','frames':[],'streams':{'id':{'target_language':'id'},'en':{'target_language':'en'}}}
        with self.config(),self.shared(),patch.object(pair,'owned',return_value=relay) as owned,patch.object(native,'owned') as legacy:
            response=self.client.get(base+'?after=7&translation_mode=one_way')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json,relay.snapshot.return_value)
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            relay.snapshot.assert_called_once_with(7)
            self.assertEqual(self.client.post(base+'/chunks/0',data={'csrf_token':'audio-csrf','pcm':(io.BytesIO(b'\x01\x00'*80),'part.pcm','application/octet-stream')}).status_code,202)
            relay.accept.assert_called_once_with(0,b'\x01\x00'*80)
            self.assertEqual(self.client.post(base+'/finish',data={'csrf_token':'audio-csrf','count':'1'}).status_code,202)
            relay.finish_input.assert_called_once_with(1)
            self.assertEqual(owned.call_count,3)
            legacy.assert_not_called()

    def test_pair_input_validation_stops_aggregate_relay(self):
        ident=self.create();base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+self.key()
        relay=Mock()
        with self.config(),self.shared(),patch.object(pair,'owned',return_value=relay):
            self.assertEqual(self.client.post(base+'/chunks/0',data={'csrf_token':'audio-csrf'}).status_code,400)
            self.assertEqual(self.client.post(base+'/finish',data={'csrf_token':'audio-csrf','count':'-1'}).status_code,400)
            self.assertEqual(relay.stop.call_count,2)
            relay.accept.assert_not_called();relay.finish_input.assert_not_called()

    def test_foreign_principal_cannot_reach_pair_start_frames_input_or_cleanup(self):
        ident=self.create();base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+self.key()
        self.login_other()
        with self.config(),self.shared(),patch.object(pair,'start') as start,patch.object(pair,'owned') as owned,patch.object(native,'connect') as connect:
            self.assertEqual(self.client.get(base).status_code,404)
            for path in (base,base+'/chunks/0',base+'/finish',
                         '/kilas-translator/live/sessions/'+ident+'/end',
                         '/kilas-translator/live/sessions/'+ident+'/turns/'+self.key()+'/cancel'):
                self.assertEqual(self.client.post(path,data={'csrf_token':'audio-csrf','count':'0'}).status_code,404,path)
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/'+ident).status_code,404)
            self.assertEqual(sessions.status(self.user,ident)['status'],'ACTIVE')
            start.assert_not_called();owned.assert_not_called();connect.assert_not_called()

    def test_pair_recovery_remains_owned_and_available_when_native_policy_is_off(self):
        self.login_other();ident=self.create(self.other)
        before=dict(audio.f.db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,)))
        with self.config(KILAS_LIVE_GEMINI_ENABLED='false'),self.shared(),patch.object(native,'cancel') as cancel,patch.object(native,'connect') as connect:
            self.assertEqual(self.client.get('/kilas-translator/live').location,'/kilas-translator/live/gemini')
            response=self.client.get('/kilas-translator/live/gemini')
            self.assertEqual(response.status_code,200)
            self.assertIn('data-gemini-ready="false"',response.text)
            self.assertTrue('value="'+pair.INPUT_MODE+'"' in response.text,'Recovery keeps the paired consent protocol.')
            self.assertEqual(dict(audio.f.db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,))),before)
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json['session']['session_id'],ident)
            self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
            cancel.assert_called_once_with(self.other,ident)
            self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json,{'session':None})
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,404)
            connect.assert_not_called()

    def test_existing_pair_v1_member_keeps_owned_routes_and_recovery_without_upgrade(self):
        self.login_other();ident=self.create(self.other,voice=pair.LEGACY_VOICE)
        key=self.key();base='/kilas-translator/live/gemini/sessions/'+ident+'/turns/'+key
        before=dict(audio.f.db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,)))
        relay=Mock();relay.snapshot.return_value={**pair.protocol(before),'frames':[]}
        with self.config(),self.shared(),patch.object(native,'connect') as connect,patch.object(pair,'start') as start,patch.object(pair,'owned',return_value=relay):
            for path in ('/kilas-translator/live','/kilas-translator?mode=live'):
                self.assertEqual(self.client.get(path).location,'/kilas-translator/live/gemini')
            page=self.client.get('/kilas-translator/live/gemini')
            self.assertTrue('value="'+pair.LEGACY_INPUT_MODE+'"' in page.text)
            self.assertTrue('name="output_order"' not in page.text)
            self.assertEqual(dict(audio.f.db.query_one('SELECT * FROM kilas_live_translator_sessions WHERE id=?',(ident,))),before)
            response=self.client.post(base,data=self.fields())
            self.assertEqual(response.status_code,202)
            self.assertEqual(response.json['input_mode'],pair.LEGACY_INPUT_MODE)
            self.assertEqual(response.json['output_order'],pair.LEGACY_OUTPUT_ORDER)
            start.assert_called_once_with(self.other,ident,key)
            self.assertEqual(self.client.get(base+'?output_order='+pair.OUTPUT_ORDER).json['input_mode'],pair.LEGACY_INPUT_MODE)
            self.assertEqual(self.client.post(base+'/chunks/0',data={'csrf_token':'audio-csrf','pcm':(io.BytesIO(b'\x01\x00'*80),'part.pcm','application/octet-stream')}).status_code,202)
            self.assertEqual(self.client.post(base+'/finish',data={'csrf_token':'audio-csrf','count':'1'}).status_code,202)
            with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false'}):
                self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json['session']['session_id'],ident)
                self.assertEqual(self.client.get('/kilas-translator/live/sessions/'+ident).status_code,200)
                page=self.client.get('/kilas-translator/live/gemini')
                self.assertTrue('value="'+pair.LEGACY_INPUT_MODE+'"' in page.text)
                self.assertTrue('data-gemini-ready="false"' in page.text)
                self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/turns/'+key+'/cancel',data={'csrf_token':'audio-csrf'}).status_code,200)
                self.assertEqual(self.client.post('/kilas-translator/live/sessions/'+ident+'/end',data={'csrf_token':'audio-csrf'}).status_code,200)
                self.assertEqual(self.client.get('/kilas-translator/live/sessions/active').json,{'session':None})
            row=audio.f.db.query_one('SELECT voice_alias,status FROM kilas_live_translator_sessions WHERE id=?',(ident,))
            self.assertEqual((row['voice_alias'],row['status']),(pair.LEGACY_VOICE,'ENDED'))
            connect.assert_not_called()

    def test_disabled_or_unauthenticated_account_cannot_admit_pair(self):
        import customer_auth
        with self.config(),self.shared(),patch.object(pair,'start') as start,patch.object(native,'connect') as connect:
            anonymous=audio.f.app.app.test_client()
            self.assertEqual(anonymous.get('/kilas-translator/live/gemini').status_code,302)
            self.login_other()
            customer_auth.set_account_disabled(self.other)
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,303)
            # Admin authentication is separate; native admission still checks
            # the disabled state from the database for this existing role.
            self.login_other('KILAS_ADMIN')
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/sessions',data=self.fields()).status_code,404)
            self.assertIsNone(sessions.active(self.other))
            start.assert_not_called();connect.assert_not_called()


if __name__=='__main__':
    unittest.main()
