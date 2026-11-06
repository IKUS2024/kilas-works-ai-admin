"""SaaS admin separation, no-GET-side-effects and support tenant isolation."""
import unittest
from unittest.mock import patch
import test_client_hub_v1 as fixture
from public_chat import schema
from kilas_core import customer_schema,job_schema,finance_bridge_schema

repo,db=fixture.repo,fixture.db

class ControlTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db();schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema();finance_bridge_schema.apply_schema()
        self.owner=repo.create_user('owner@test.invalid','hash')
        self.aid=repo.create_user('admin@test.invalid','hash',role='KILAS_ADMIN')
        self.bid=repo.create_business(self.owner,'Business Satu','AI_ADMIN')
        self.other=repo.create_business(self.owner,'Business Dua','AI_ADMIN')
        self.client=fixture.fresh_client()
        with self.client.session_transaction() as session:session.update(user_id=self.aid,role='KILAS_ADMIN',_csrf_token='token')

    def test_admin_sections_are_readonly_functional(self):
        count=db.query_one('SELECT COUNT(*) AS n FROM audit_log')['n']
        for section in ('overview','businesses','whatsapp','subscriptions','cost','finance','system'):
            result=self.client.get('/platform/'+section)
            self.assertEqual(result.status_code,200,section)
            self.assertIn('Platform Admin',result.text)
        detail=self.client.get(f'/platform/business/{self.bid}')
        self.assertEqual(detail.status_code,200)
        self.assertIn('Keluar',detail.text)
        self.assertIn('/logout',detail.text)
        overview=self.client.get('/platform/overview')
        self.assertIn('Keluar',overview.text)
        self.assertIn('/logout',overview.text)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM audit_log')['n'],count)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_transactions')['n'],0)
        response=self.client.get('/admin/')
        self.assertEqual(response.status_code,303)
        self.assertIn('/platform/',response.location)

    def test_support_has_permanent_banner_cross_tenant_denied_and_writes_audited(self):
        data={'csrf_token':'token'}
        response=self.client.post(f'/platform/business/{self.bid}/support',data=data)
        self.assertEqual(response.status_code,303)
        home=self.client.get(response.location)
        self.assertEqual(home.status_code,200)
        self.assertIn('Anda sedang mengakses Business Satu sebagai Kilas Admin',home.text)
        self.assertNotIn('Business Dua',home.text)
        self.assertEqual(self.client.get(f'/business/{self.other}/assist-whatsapp').status_code,404)
        self.assertEqual(self.client.post(f'/business/{self.other}/train',data=data).status_code,404)
        self.assertEqual(self.client.get(f'/business/{self.bid}/assist-whatsapp').status_code,200)
        self.client.post(f'/business/{self.bid}/assist-whatsapp',data=data)
        self.assertIsNotNone(db.query_one("SELECT 1 FROM audit_log WHERE business_id=? AND action='ADMIN_SUPPORT_WRITE'",(self.bid,)))
        self.client.post('/platform/support/exit',data=data)
        with self.client.session_transaction() as session:self.assertNotIn('support_business_id',session)

    def test_customer_cannot_read_platform_or_start_support(self):
        with self.client.session_transaction() as session:session.update(user_id=self.owner,role='CLIENT_OWNER')
        self.assertEqual(self.client.get('/platform/').status_code,403)
        self.assertEqual(self.client.post(f'/platform/business/{self.bid}/support',data={'csrf_token':'token'}).status_code,403)
        self.assertEqual(self.client.get('/platform/system').status_code,403)

    @patch.dict('os.environ', {'INTERNAL_SERVICE_SECRET':'private-bridge'})
    def test_system_reports_only_allowlisted_configuration_and_sanitizes_failures(self):
        import platform_control as control
        with patch.object(control.assist_connections,'bridge',return_value={
                'status':'ok','whatsapp':True,'openai':True,'claude':False,
                'secret':'do-not-display','commit':'do-not-display'}) as bridge:
            result=self.client.get('/platform/system')
            self.assertEqual(result.status_code,200)
            self.assertIn('Reachable and authenticated',result.text)
            self.assertNotIn('do-not-display',result.text)
            self.assertNotIn('private-bridge',result.text)
            bridge.assert_called_once_with('health',{})
        with patch.object(control.assist_connections,'bridge',side_effect=RuntimeError('private-error')):
            result=self.client.get('/platform/system')
            self.assertEqual(result.status_code,200)
            self.assertIn('Unreachable or configuration not yet verified',result.text)
            self.assertNotIn('private-error',result.text)

    @patch.dict('os.environ', {'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true'})
    def test_internal_kilas_workspace_does_not_grant_customer_tenant_access(self):
        import platform_workspace
        internal=platform_workspace.ensure_business()
        for section in ('customers','jobs'):
            self.assertEqual(self.client.get('/admin/'+section,follow_redirects=True).status_code,200)
            self.assertEqual(self.client.get(f'/business/{self.bid}/'+section).status_code,404)
        self.client.post(f'/platform/business/{self.bid}/support',data={'csrf_token':'token'})
        for section in ('customers','jobs'):
            self.assertEqual(self.client.get(f'/business/{internal["id"]}/'+section).status_code,404)
        with self.client.session_transaction() as session:
            session.clear();session.update(user_id=self.owner,role='CLIENT_OWNER')
        for section in ('customers','jobs'):
            self.assertEqual(self.client.get(f'/business/{internal["id"]}/'+section).status_code,404)

if __name__=='__main__':unittest.main()
