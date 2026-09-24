"""Shared Phase 5 action assertions for SQLite and disposable PostgreSQL."""
import json
from unittest.mock import patch
from kilas_core import actions, jobs, understanding
from kilas_core.playbook_definitions import PLAYBOOKS


def interpret(fields=None, **changes):
    fields = fields or {}
    data = dict(intent='REQUEST', fields=fields, evidence={key: 'pesan' for key in fields}, corrections=[], ambiguous=[])
    data.update(changes)
    return understanding.parse(json.dumps(data), 'pesan')


class ActionCases:
    def snapshot(self, bid=7, cid='conv'):
        with jobs.transaction() as tx:
            return actions.snapshot(tx, bid, cid)

    def apply(self, fields=None, *, bid=7, cid='conv', expected=None, event='event-one', **changes):
        expected = self.snapshot(bid, cid) if expected is None else expected
        with jobs.transaction() as tx:
            return actions.apply(tx,bid,cid,expected=expected,book=PLAYBOOKS['LOGISTICS'],
                                 interpretation=interpret(fields, **changes),event_id=event)

    def test_linked_create_later_update_and_system_audit(self):
        first, reply = self.apply({'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang'})
        self.assertEqual(first['customer_id'], 'alice')
        self.assertEqual(first['conversation_id'], 'conv')
        self.assertEqual(first['status'], 'NEEDS_INFORMATION')
        self.assertIn('volume', reply)
        second, reply = self.apply({'volume_cbm':'0.2 m³'}, event='event-two')
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(second['fields']['origin'], 'Guangzhou')
        self.assertEqual(second['status'], 'READY_FOR_QUOTE')
        self.assertEqual(jobs.list_jobs(7)[1], 1)
        with jobs.transaction() as tx:
            records = tx.execute('SELECT * FROM audit_log')
            self.assertEqual(len(records), 3)
            self.assertTrue(all(r['actor_user_id'] is None and json.loads(r['detail'])['origin']=='WEB_PLAYBOOK' for r in records))

    def test_scope_and_same_data_other_tenant(self):
        row, _ = self.apply({'item':'baju'})
        other, _ = self.apply({'item':'baju'},bid=8,cid='foreign')
        self.assertNotEqual(row['id'], other['id'])
        self.assertEqual(other['customer_id'], 'other')
        with self.assertRaises(jobs.JobError):
            self.apply({'item':'baju'},bid=7,cid='foreign')
        with self.assertRaises(jobs.JobError):
            self.apply({'item':'baju'},bid=8,cid='foreign',expected=self.snapshot())

    def test_stale_owner_edit_not_overwritten(self):
        row, _ = self.apply({'item':'baju'})
        before = self.snapshot()
        manual = jobs.update_job(7,row['id'],expected_version=row['version'],actor_id=1,
                                operation_key='owner-edit-000001',title='Owner title',fields={**row['fields'],'reference':'Manual'})
        with self.assertRaises(jobs.JobError) as error:
            self.apply({'weight':'20 kg'},expected=before,event='event-two')
        self.assertEqual(error.exception.code, 'stale_version')
        updated, _ = self.apply({'weight':'20 kg'},event='event-three')
        self.assertEqual(updated['title'], 'Owner title')
        self.assertEqual(updated['fields']['reference'], 'Manual')

    def test_atomic_failure_no_partial_job_or_audit(self):
        with patch.object(jobs,'_update_job',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                self.apply({'item':'baju'})
        self.assertEqual(jobs.list_jobs(7)[1],0)
        with jobs.transaction() as tx:
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM audit_log')['n'],0)
            self.assertEqual(tx.one('SELECT COUNT(*) AS n FROM kw_core_job_operations')['n'],0)

    def test_uncertainty_persisted_until_correction(self):
        row, _ = self.apply({'origin':'Guangzhou'})
        row, reply = self.apply({'origin':'Shanghai'},event='event-two')
        self.assertEqual(row['fields']['uncertain_fields'],'origin')
        row, reply = self.apply({'item':'baju'},event='event-three')
        self.assertIn('pastikan asal',reply)
        row, reply = self.apply({'origin':'Shanghai'},event='event-four',corrections=['origin'])
        self.assertEqual(row['fields']['origin'],'Shanghai')
        self.assertEqual(row['fields']['uncertain_fields'],'')

    def test_multiple_jobs_or_new_request_require_owner(self):
        first, _ = self.apply({'item':'baju'})
        row, reply = self.apply({'item':'sepatu'},event='event-two',intent='NEW_REQUEST')
        self.assertEqual(row['version'],first['version'])
        self.assertIn('bantuan tim',reply)
        jobs.create_job(7,'alice',conversation_id='conv',title='Other',kind='SHIPMENT',actor_id=1,operation_key='owner-create-0001')
        row, reply = self.apply({'weight':'20 kg'},event='event-three')
        self.assertIsNone(row)
        self.assertIn('ganda',reply)

    def test_public_actor_validation_still_requires_real_user(self):
        for actor in (None, jobs._WEB_PLAYBOOK_ACTOR):
            with self.assertRaises(jobs.JobError):
                jobs.create_job(7,'alice',title='Forged actor',actor_id=actor,operation_key='forged-actor-0001')
