# Resend forgot-password upgrade

Apply this delta at the repository root, preserving paths, then redeploy.

## Files
- client-hub/email_utils.py
- client-hub/tests/test_resend_forgot_password.py
- RESEND-FORGOT-PASSWORD-MANIFEST.md

## Changes
Password reset uses Resend HTTPS when RESEND_API_KEY is configured. SMTP is not required for this path. Legacy SMTP is used only when the Resend key is absent; Resend failure does not trigger SMTP retries. Failure logs omit recipients, credentials, tokens and reset URLs. Generic HTTP responses and existing reset security remain unchanged.

## Verification
23 focused forgot-password tests passed: 9 Resend tests and 14 existing reset tests. Provider calls were mocked; no live email delivery was tested. No full repository suite was run. No code changed after these tests.

## Environment
- RESEND_API_KEY: your actual Resend API key (re_...).
- RESET_EMAIL_FROM: Kilas Works <noreply@YOUR_VERIFIED_DOMAIN>.
- PUBLIC_APP_BASE_URL: your actual public HTTPS Client Hub origin.
- CLIENT_HUB_ENV: production. APP_ENV=production is also recognized; keep production settings consistent.
- Preserve the existing SECRET_KEY.
SMTP variables are unnecessary when Resend is configured.
The sender domain must be verified in Resend: https://resend.com/docs/dashboard/domains/introduction

## Database
No migration required.
