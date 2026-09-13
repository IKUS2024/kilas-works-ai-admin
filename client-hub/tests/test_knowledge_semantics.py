"""Canonical knowledge and real independent-connection SQLite lock regressions."""
import copy
import json
import threading
import unittest
from unittest.mock import patch, Mock
from test_knowledge_setup_v2 import KnowledgeTests, repo, db, knowledge


class SemanticTests(unittest.TestCase):
    setUp = KnowledgeTests.setUp
    state = KnowledgeTests.state
    form = KnowledgeTests.form

    def token(self):
        return self.form()['knowledge_revision']

    def test_unchanged_reload_and_timestamp_only_changes(self):
        original = self.token()
        self.assertEqual(original, self.token())
        for table, field in [('business_profiles', 'updated_at'), ('business_services', 'created_at'), ('business_faqs', 'created_at')]:
            db.execute(f'UPDATE {table} SET {field}=? WHERE business_id=?', ('2040-01-01', self.bid))
        self.assertEqual(original, self.token())

    def test_config_key_order_and_runtime_metadata_irrelevant(self):
        config = knowledge.provisioning.build_tenant_config(self.bid)
        repo.save_tenant_config(self.bid, config)
        original = self.token()
        config = dict(reversed(list(config.items())))
        config['whatsapp'] = {'credentials_reference': 'changed-reference', 'connection_status': 'CONNECTED'}
        config['feature_plan'] = {'package': 'unrelated-test-metadata'}
        config['status'] = 'unrelated-runtime-state'
        repo.save_tenant_config(self.bid, config)
        self.assertEqual(original, self.token())
        config['ai']['tone'] = 'Different knowledge'
        repo.save_tenant_config(self.bid, config)
        self.assertNotEqual(original, self.token())

    def test_driver_representations_are_semantically_equal(self):
        profile, services, faqs = self.state()
        profile['additional_languages'] = '["en"]'
        profile['appointment_enabled'] = 1
        profile['operating_hours'] = '{"b":2,"a":1}'
        config = {'ai': {'tone': 'Friendly', 'language': {'additional': ['en'], 'primary': 'id'}}}
        def read_string(sql, params):
            if 'tenant_configs' in sql: return [{'config_json': json.dumps(config)}]
            if 'ai_settings' in sql: return [{'normalized_config_json': '{"description":"Hello"}'}]
            if 'business_files' in sql: return [{'extracted_text': 'Knowledge file'}]
            return [{'business_name': 'Same'}]
        first = knowledge.revision_token(self.bid, 1, profile, services, faqs, read_string)
        profile['additional_languages'] = ['en']
        profile['appointment_enabled'] = True
        profile['operating_hours'] = {'a': 1, 'b': 2}
        for row in services + faqs: row['needs_review'] = bool(row['needs_review'])
        def read_native(sql, params):
            if 'tenant_configs' in sql: return [{'config_json': config}]
            rows = read_string(sql, params)
            if 'ai_settings' in sql: rows[0]['normalized_config_json'] = {'description': 'Hello'}
            return rows
        self.assertEqual(first, knowledge.revision_token(self.bid, 999, profile, services, faqs, read_native))
        config['ai']['language'] = b'{"primary":"id","additional":["en"]}'
        self.assertEqual(first, knowledge.revision_token(self.bid, 0, profile, services, faqs, read_native))

    def test_tied_service_order_and_faq_order_are_stable(self):
        repo.replace_business_services(self.bid, ['One', 'Two'])
        db.execute('UPDATE business_services SET sort_order=0 WHERE business_id=?', (self.bid,))
        profile, services, faqs = self.state()
        self.assertEqual([r['id'] for r in services], sorted(r['id'] for r in services))
        first = knowledge.revision_token(self.bid, 0, profile, services, faqs)
        self.assertEqual(first, knowledge.revision_token(self.bid, 0, profile, list(reversed(services)), list(reversed(faqs))))

    def test_profile_knowledge_change_invalidates(self):
        original = self.token()
        repo.upsert_business_profile(self.bid, {'appointment_rules_raw': 'Booking satu hari sebelumnya'})
        self.assertNotEqual(original, self.token())

    def test_settings_preserves_blank_protection_and_unsubmitted_fields(self):
        repo.upsert_business_profile(self.bid, {'operating_hours': '09-17', 'tone': 'Keep'})
        repo.save_business_settings(self.bid, {'operating_hours': '', 'appointment_enabled': False})
        row = repo.get_business_profile(self.bid)
        self.assertEqual(row['operating_hours'], '09-17')
        self.assertEqual(row['tone'], 'Keep')
        self.assertFalse(row['appointment_enabled'])

    def test_sqlite_read_helpers_do_not_release_business_lock(self):
        @db.knowledge_writer
        def operation(business_id):
            db.query_one('SELECT id FROM businesses WHERE id=?', (business_id,))
            db.query_all('SELECT id FROM businesses WHERE id=?', (business_id,))
            self.assertTrue(db.get_connection().in_transaction)
            repo.upsert_business_profile(business_id, {'tone': 'Uncommitted'})
            raise RuntimeError('rollback')
        with self.assertRaises(RuntimeError): operation(self.bid)
        self.assertEqual(repo.get_business_profile(self.bid)['tone'], 'ramah')

    def test_postgres_lock_sql_and_transaction_order_mock_only(self):
        conn, cursor = Mock(), Mock()
        conn.cursor.return_value = cursor
        cursor.rowcount = 1
        @db.knowledge_writer
        def operation(business_id):
            cursor.execute.assert_called_once_with('UPDATE businesses SET id = id WHERE id = %s', (business_id,))
            db._knowledge_commit(conn)
            conn.commit.assert_not_called()
        with patch.object(db, 'BACKEND', 'postgres'), patch.object(db, 'get_connection', return_value=conn):
            operation(self.bid)
        conn.commit.assert_called_once()

    def prepare_save(self):
        before = self.state()
        form = self.form()
        setup = knowledge.editor(self.bid, before[1], before[2])
        cards = {kind: knowledge.parse_rows(form, kind, setup[kind]) for kind in ('services', 'faqs')}
        fields = {key: form[key] for key in knowledge.PROFILE_FIELDS}
        fields['category'] = 'V2 update'
        return lambda: knowledge.save(self.bid, fields, copy.deepcopy(cards), *before, form['knowledge_revision'], self.uid)

    def concurrent_writer_first(self, writer, expected_archives=0):
        save = self.prepare_save()
        held, release, attempting = threading.Event(), threading.Event(), threading.Event()
        results = []
        connections = []
        @db.knowledge_writer
        def hold_writer(business_id):
            writer()
            held.set()
            if not release.wait(5): raise AssertionError('release timeout')
        def run(fn, mark=False):
            try:
                conn = db.get_connection()
                connections.append(conn)
                if mark:
                    conn.set_trace_callback(lambda sql: attempting.set() if 'UPDATE businesses SET id = id' in sql else None)
                fn()
                results.append('ok')
            except Exception as exc:
                results.append(exc)
            finally:
                db.get_connection().close()
                db._local.conn = None
        first = threading.Thread(target=run, args=(lambda: hold_writer(self.bid),))
        second = threading.Thread(target=run, args=(save, True))
        first.start()
        try:
            self.assertTrue(held.wait(5))
            second.start()
            self.assertTrue(attempting.wait(5))
            self.assertTrue(second.is_alive())
        finally:
            release.set()
            first.join(5)
            if second.ident: second.join(5)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(len({id(c) for c in connections}), 2)
        self.assertEqual(sum(v == 'ok' for v in results), 1)
        self.assertEqual(sum(isinstance(v, ValueError) for v in results), 1, str(results))
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM business_knowledge_revisions WHERE business_id=?', (self.bid,))['n'], expected_archives)

    def test_concurrent_config_writer_then_v2_rejected(self):
        config = knowledge.provisioning.build_tenant_config(self.bid)
        repo.save_tenant_config(self.bid, config)
        config['ai']['tone'] = 'Config wins'
        self.concurrent_writer_first(lambda: repo.save_tenant_config(self.bid, config))
        self.assertEqual(repo.get_tenant_config_row(self.bid)['config']['ai']['tone'], 'Config wins')

    def test_concurrent_settings_writer_then_v2_rejected(self):
        self.concurrent_writer_first(lambda: repo.save_business_settings(self.bid, {'operating_hours': '10-18'}))
        self.assertEqual(repo.get_business_profile(self.bid)['operating_hours'], '10-18')

    def test_concurrent_legacy_writer_then_v2_rejected(self):
        profile, services, faqs = self.state()
        fields = {k: profile.get(k) or '' for k in knowledge.PROFILE_FIELDS if k != 'category'}
        fields['tone'] = 'Legacy wins'
        self.concurrent_writer_first(lambda: repo.save_live_business_memory(self.bid, fields,
            [r['raw_input'] for r in services], [r['raw_input'] for r in faqs], self.uid))
        self.assertEqual(repo.get_business_profile(self.bid)['tone'], 'Legacy wins')

    def test_concurrent_v2_saves_cannot_both_pass(self):
        first_save = self.prepare_save()
        self.concurrent_writer_first(first_save, expected_archives=1)

    def test_unrelated_config_update_preserved_by_existing_v2_form(self):
        config = knowledge.provisioning.build_tenant_config(self.bid)
        repo.save_tenant_config(self.bid, config)
        form = self.form()
        config['whatsapp']['connection_status'] = 'CONNECTED'
        config['new_runtime_metadata'] = {'keep': True}
        repo.save_tenant_config(self.bid, config)
        form['category'] = 'Knowledge edit'
        self.assertEqual(self.client.post(self.url, data=form).status_code, 302)
        current = repo.get_tenant_config_row(self.bid)['config']
        self.assertEqual(current['whatsapp']['connection_status'], 'CONNECTED')
        self.assertEqual(current['new_runtime_metadata'], {'keep': True})
        self.assertEqual(current['business_type'], 'Knowledge edit')

    def test_provisioning_builds_snapshot_only_after_shared_lock(self):
        original = knowledge.provisioning.build_tenant_config
        def checked(business_id):
            self.assertEqual(db._local.knowledge_business, business_id)
            self.assertTrue(db.get_connection().in_transaction)
            return original(business_id)
        with patch.object(knowledge.provisioning, 'validate_tenant_config', return_value=(True, [])), \
             patch.object(knowledge.provisioning, 'build_tenant_config', side_effect=checked):
            knowledge.provisioning.provision_tenant(self.bid, {'id': self.uid, 'role': 'KILAS_ADMIN'})
        self.assertIsNotNone(repo.get_tenant_config_row(self.bid))

    def test_v2_first_config_writer_reads_new_state_after_waiting(self):
        repo.save_tenant_config(self.bid, knowledge.provisioning.build_tenant_config(self.bid))
        save = self.prepare_save()
        held, release, attempting = threading.Event(), threading.Event(), threading.Event()
        errors = []
        original = knowledge.revision_token
        def hold_fingerprint(*args, **kwargs):
            result = original(*args, **kwargs)
            held.set()
            if not release.wait(5): raise AssertionError('release timeout')
            return result
        @db.knowledge_writer
        def config_writer(business_id):
            config = repo.get_tenant_config_row(business_id)['config']
            self.assertEqual(config['business_type'], 'V2 update')
            config['runtime_note'] = 'Preserved'
            repo.save_tenant_config(business_id, config)
        def run(fn, trace=False):
            try:
                conn = db.get_connection()
                if trace:
                    conn.set_trace_callback(lambda sql: attempting.set() if 'UPDATE businesses SET id = id' in sql else None)
                fn()
            except Exception as exc: errors.append(exc)
            finally:
                db.get_connection().close(); db._local.conn = None
        with patch.object(knowledge, 'revision_token', side_effect=hold_fingerprint):
            first = threading.Thread(target=run, args=(save,))
            second = threading.Thread(target=run, args=(lambda: config_writer(self.bid), True))
            first.start()
            try:
                self.assertTrue(held.wait(5))
                second.start()
                self.assertTrue(attempting.wait(5))
                self.assertTrue(second.is_alive())
            finally:
                release.set(); first.join(5)
                if second.ident: second.join(5)
        self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        config = repo.get_tenant_config_row(self.bid)['config']
        self.assertEqual(config['business_type'], 'V2 update')
        self.assertEqual(config['runtime_note'], 'Preserved')
