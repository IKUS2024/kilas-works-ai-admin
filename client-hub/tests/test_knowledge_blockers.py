"""Focused JSONB and cross-writer stale-form regressions (no external services)."""
import json
import unittest
from unittest.mock import patch
import requests
from test_knowledge_setup_v2 import KnowledgeTests, repo, db, knowledge, ai_onboarding


class BlockerTests(unittest.TestCase):
    setUp = KnowledgeTests.setUp
    state = KnowledgeTests.state
    form = KnowledgeTests.form

    def seed_config(self):
        repo.save_tenant_config(self.bid, knowledge.provisioning.build_tenant_config(self.bid))

    def save_category(self, value):
        form = self.form()
        form['category'] = value
        self.assertEqual(self.client.post(self.url, data=form).status_code, 302)
        self.assertEqual(repo.get_business_profile(self.bid)['category'], value)

    def test_string_config_save(self):
        self.seed_config()
        self.assertIsInstance(repo.get_tenant_config_row(self.bid)['config_json'], str)
        self.save_category('String config')

    def test_postgres_native_dict_save(self):
        self.seed_config()
        original = db._row_to_dict
        def native_jsonb(row, columns=None):
            result = original(row, columns)
            if result and isinstance(result.get('config_json'), str):
                result['config_json'] = json.loads(result['config_json'])
            return result
        original_query = db.query_one
        def native_query(*args, **kwargs):
            row = original_query(*args, **kwargs)
            if row and isinstance(row.get('config_json'), str):
                row['config_json'] = json.loads(row['config_json'])
            return row
        with patch.object(db, '_row_to_dict', side_effect=native_jsonb), \
             patch.object(db, 'query_one', side_effect=native_query):
            self.assertIsInstance(repo.get_tenant_config_row(self.bid)['config_json'], dict)
            self.save_category('JSONB config')
            self.save_category('JSONB edited again')
        self.assertEqual(repo.get_tenant_config_row(self.bid)['config']['business_type'], 'JSONB edited again')

    def test_shared_decoder_strings_bytes_native_and_malformed(self):
        for value in ({'a': 1}, [1], '{"a":1}', b'{"a":1}', bytearray(b'{"a":1}')):
            result = repo._coerce_json_column(value, (dict, list))
            self.assertEqual(result, [1] if isinstance(value, list) else {'a': 1})
        with self.assertRaises(json.JSONDecodeError):
            repo._coerce_json_column('{bad', (dict, list))

    def test_malformed_stored_config_aborts_save_without_writes(self):
        self.seed_config()
        before = self.state()
        form = self.form()
        cards = knowledge.editor(self.bid, before[1], before[2])
        parsed = {kind: knowledge.parse_rows(form, kind, cards[kind]) for kind in ('services', 'faqs')}
        db.execute('UPDATE tenant_configs SET config_json=? WHERE business_id=?', ('{bad', self.bid))
        with self.assertRaises(json.JSONDecodeError):
            knowledge.save(self.bid, {'category': 'Must not persist'}, parsed, *before, form['knowledge_revision'], self.uid)
        self.assertEqual(self.state(), before)
        self.assertIsNone(knowledge.latest(self.bid))

    def test_sequential_saves_and_one_archive_per_save(self):
        self.save_category('First')
        self.save_category('Second')
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM business_knowledge_revisions WHERE business_id=?', (self.bid,))['n'], 2)

    def test_two_tabs_rejects_old_then_reload_recovers(self):
        old = self.form()
        self.save_category('First tab')
        old['category'] = 'Old tab'
        self.assertEqual(self.client.post(self.url, data=old).status_code, 400)
        self.assertEqual(repo.get_business_profile(self.bid)['category'], 'First tab')
        self.save_category('Reloaded')

    def test_settings_invalidates_old_v2_form(self):
        old = self.form()
        response = self.client.post(f'/business/{self.bid}/settings', data={'operating_hours': '10-18'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(repo.get_business_profile(self.bid)['operating_hours'], '10-18')
        self.assertEqual(self.client.post(self.url, data=old).status_code, 400)
        self.assertEqual(repo.get_business_profile(self.bid)['operating_hours'], '10-18')
        self.save_category('After settings reload')

    def test_legacy_memory_invalidates_old_v2_form(self):
        old = self.form()
        data = {key: old[key] for key in knowledge.PROFILE_FIELDS}
        data.update(tone='Formal', services_raw=self.state()[1][0]['raw_input'],
                    faq_raw='\n'.join(r['raw_input'] for r in self.state()[2]))
        self.assertEqual(self.client.post(self.url, data=data).status_code, 302)
        self.assertEqual(self.client.post(self.url, data=old).status_code, 400)
        self.assertEqual(repo.get_business_profile(self.bid)['tone'], 'Formal')
        self.save_category('After legacy reload')

    def test_tenant_revision_isolation_and_foreign_token_rejected(self):
        uid = repo.create_user('other-blocker@test.com', 'unused')
        other = repo.create_business(uid, 'Other', 'AI_ADMIN_BASIC')
        repo.upsert_business_profile(other, {'tone': 'Private'})
        original = self.form()['knowledge_revision']
        repo.upsert_business_profile(other, {'tone': 'Private changed'})
        self.assertEqual(self.form()['knowledge_revision'], original)
        foreign = knowledge.editor(other, [], [])['revision']
        form = self.form(); form['knowledge_revision'] = foreign
        self.assertEqual(self.client.post(self.url, data=form).status_code, 400)
        self.assertEqual(self.client.get(f'/business/{other}/memory').status_code, 404)
        self.assertEqual(self.client.post(f'/business/{other}/memory', data=self.form()).status_code, 404)
        self.save_category('Own change')
        self.assertIsNone(knowledge.latest(other))
        self.assertEqual(repo.get_business_profile(other)['tone'], 'Private changed')

    def test_no_ai_or_network_for_load_save_readiness(self):
        with patch.object(ai_onboarding, 'normalize_business_data', side_effect=AssertionError('AI called')), \
             patch.object(requests.sessions.Session, 'request', side_effect=AssertionError('Network called')):
            self.assertEqual(self.client.get(self.url).status_code, 200)
            self.save_category('No AI')
            self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_config_only_mutation_invalidates_form(self):
        self.seed_config()
        old = self.form()
        config = repo.get_tenant_config_row(self.bid)['config']
        config['ai']['tone'] = 'Changed config'
        repo.save_tenant_config(self.bid, config)
        self.assertEqual(self.client.post(self.url, data=old).status_code, 400)
        self.save_category('Latest config')


if __name__ == '__main__':
    unittest.main()
