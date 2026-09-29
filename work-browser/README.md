# Kilas Work browser process (unreleased)

This is a separate, disposable browser runtime for Work. It has no database, Finance/Assist data, or OpenAI API key. Client Hub owns account authorization, durable job checkpoints, quota and billing. Every request is signed by Client Hub with `KILAS_WORK_BROWSER_SECRET` (minimum 32 characters) and scoped to an account ID and job ID. Browser contexts and downloads are isolated per job and never shared between accounts.

For a dedicated Render service, build with `pip install -r requirements.txt && python -m playwright install --with-deps chromium`, and start with `gunicorn --workers 1 --threads 1 app:app`. Set the same high-entropy `KILAS_WORK_BROWSER_SECRET` in Client Hub and this service. The service needs enough memory for Chromium; no production deployment has been approved or performed. A restart intentionally loses ephemeral browser state. Client Hub must mark a running job paused and require inspection before retrying any uncertain side effect.

This directory is a staging implementation only. Do not enable Work or create the service until full browser integration, tests, cost review, and production approval are complete.
