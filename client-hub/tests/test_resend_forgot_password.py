"""Focused reset-email provider tests; no external delivery."""
import os
import sys
import io
import contextlib
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import test_business_hub_v2_phase_a as fixture
import email_utils as mail

class ResendResetTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_db()
        self.env = patch.dict(os.environ, {'RESEND_API_KEY':'re_private_test',
            'RESET_EMAIL_FROM':'Kilas Works <noreply@example.test>', 'APP_ENV':'production',
            'CLIENT_HUB_ENV':'production','PUBLIC_APP_BASE_URL':'https://app.kilasworks.id',
            'SMTP_HOST':'','SMTP_USERNAME':'','SMTP_PASSWORD':''})
        self.env.start();self.addCleanup(self.env.stop)
        self.url='https://app.kilasworks.id/reset-password/private-token'

    def response(self,status=200,payload=None):
        return Mock(status_code=status,json=Mock(return_value=payload if payload is not None else {'id':'email-test-id'}))

    def test_resend_success_without_smtp(self):
        with patch.object(mail.requests,'post',return_value=self.response()) as post,patch.object(mail.smtplib,'SMTP') as smtp:
            self.assertTrue(mail._deliver_password_reset_email('recipient@example.test',self.url))
        smtp.assert_not_called()
        self.assertEqual(post.call_args.args[0],'https://api.resend.com/emails')
        args=post.call_args.kwargs
        self.assertEqual(args['headers']['Authorization'],'Bearer re_private_test')
        self.assertEqual(args['json']['to'],['recipient@example.test'])
        self.assertIn(self.url,args['json']['text'])
        self.assertEqual(args['json']['from'],'Kilas Works <noreply@example.test>')
        self.assertFalse(args['allow_redirects']);self.assertEqual(args['timeout'],(5,10))

    def test_resend_non_2xx_never_falls_back_or_logs_payload(self):
        for status in (302,401,422,429,500):
            with self.subTest(status=status),patch.object(mail.requests,'post',return_value=self.response(status,{'message':self.url})) as post,patch.object(mail.smtplib,'SMTP') as smtp,contextlib.redirect_stdout(io.StringIO()) as logs:
                self.assertFalse(mail._deliver_password_reset_email('recipient@example.test',self.url))
            smtp.assert_not_called();self.assertIn(str(status),logs.getvalue());self.assertNotIn('private-token',logs.getvalue())

    def test_timeout_and_network_errors_redacted(self):
        for error in (mail.requests.Timeout,mail.requests.ConnectionError):
            with self.subTest(error=error),patch.object(mail.requests,'post',side_effect=error('re_private_test '+self.url+' recipient@example.test')),patch.object(mail.smtplib,'SMTP') as smtp,contextlib.redirect_stdout(io.StringIO()) as logs:
                self.assertFalse(mail._deliver_password_reset_email('recipient@example.test',self.url))
            smtp.assert_not_called()
            for secret in ('re_private_test','private-token','recipient@example.test'):self.assertNotIn(secret,logs.getvalue())

    def test_missing_sender_fails_safely_without_smtp(self):
        with patch.dict(os.environ,{'RESET_EMAIL_FROM':''}),patch.object(mail.requests,'post') as post,patch.object(mail.smtplib,'SMTP') as smtp:
            self.assertFalse(mail._deliver_password_reset_email('recipient@example.test',self.url))
        post.assert_not_called();smtp.assert_not_called()

    def test_missing_all_delivery_config(self):
        with patch.dict(os.environ,{'RESEND_API_KEY':''}),patch.object(mail.requests,'post') as post,patch.object(mail.smtplib,'SMTP') as smtp:
            self.assertFalse(mail.send_password_reset_email('recipient@example.test',self.url))
        post.assert_not_called();smtp.assert_not_called()

    def test_smtp_fallback_only_when_resend_absent(self):
        with patch.dict(os.environ,{'RESEND_API_KEY':'','SMTP_HOST':'smtp.test','SMTP_USERNAME':'test','SMTP_PASSWORD':'test'}),patch.object(mail.requests,'post') as post,patch.object(mail.smtplib,'SMTP') as smtp:
            self.assertTrue(mail._deliver_password_reset_email('recipient@example.test',self.url))
        post.assert_not_called();smtp.assert_called_once()

    def test_malformed_success_response_is_not_acceptance(self):
        for response in (self.response(200,{}),Mock(status_code=200,json=Mock(side_effect=ValueError(self.url)))):
            with patch.object(mail.requests,'post',return_value=response),contextlib.redirect_stdout(io.StringIO()) as logs:
                self.assertFalse(mail._deliver_password_reset_email('recipient@example.test',self.url))
            self.assertNotIn('private-token',logs.getvalue())

    def test_production_queue_accepts_resend_without_smtp(self):
        with patch.object(mail.requests,'post',return_value=self.response()) as post:
            self.assertFalse(mail.send_password_reset_email('recipient@example.test',self.url))
            mail._mail_queue.join()
            post.assert_called_once()

    def test_registered_and_unknown_have_same_response_for_every_provider_outcome(self):
        fixture.repo.create_user('registered@example.test',fixture.security.hash_password('password123'))
        client=fixture.fresh_client();client.get('/forgot-password')
        for outcome in ('success','api_error','timeout','network','missing'):
            fixture.security._RESET_REQUEST_ATTEMPTS.clear()
            kwargs={'return_value':self.response(500 if outcome=='api_error' else 200)}
            if outcome in ('timeout','network'):
                kwargs={'side_effect':(mail.requests.Timeout if outcome=='timeout' else mail.requests.ConnectionError)('private-token')}
            with self.subTest(outcome=outcome),patch.dict(os.environ,{'RESEND_API_KEY':'' if outcome=='missing' else 're_private_test'}),patch.object(mail.requests,'post',**kwargs):
                registered=client.post('/forgot-password',data={'email':'registered@example.test'})
                unknown=client.post('/forgot-password',data={'email':'unknown@example.test'})
                mail._mail_queue.join()
            self.assertEqual(registered.status_code,200);self.assertEqual(registered.data,unknown.data)

if __name__=='__main__':unittest.main()
