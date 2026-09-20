"""Hourly Render Cron entrypoint for Kilas Works follow-ups.

Safe staging behavior:
- FOLLOWUP_CRON_ENABLED must be exactly "true" before ANY HTTP request is made.
- Secret stays in Render env and is never printed.
- Logs contain only endpoint/status/count summaries, never phone numbers or message text.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _enabled():
    return (os.environ.get("FOLLOWUP_CRON_ENABLED") or "").strip().lower() == "true"


def _call(base_url, path, secret):
    query = urllib.parse.urlencode({"key": secret})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}?{query}",
        headers={"User-Agent": "KilasRenderFollowupScheduler/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            status_code = int(response.status)
            raw = response.read(65536)
    except urllib.error.HTTPError as exc:
        print(f"followup_scheduler endpoint={path} http={exc.code} result=failed")
        return False
    except (urllib.error.URLError, TimeoutError):
        print(f"followup_scheduler endpoint={path} result=network_error")
        return False

    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print(f"followup_scheduler endpoint={path} http={status_code} result=bad_json")
        return False

    if not isinstance(body, dict):
        print(f"followup_scheduler endpoint={path} http={status_code} result=bad_shape")
        return False

    summary = {
        "status": body.get("status"),
        "checked": body.get("checked"),
        "tenants_checked": body.get("tenants_checked"),
        "reminders_checked": body.get("reminders_checked"),
    }
    print(
        f"followup_scheduler endpoint={path} http={status_code} "
        f"summary={json.dumps(summary, separators=(',', ':'))}"
    )
    return status_code == 200 and body.get("status") == "ok"


def main():
    if not _enabled():
        print("followup_scheduler paused: FOLLOWUP_CRON_ENABLED is not true")
        return 0

    secret = (os.environ.get("RENDER_FOLLOWUP_CRON_SECRET") or "").strip()
    base_url = (os.environ.get("KILAS_BOT_BASE_URL") or "https://demo.kilasworks.id").strip()
    if not secret or not base_url.startswith("https://"):
        print("followup_scheduler configuration_error")
        return 2

    ok_platform = _call(base_url, "/cron/followups", secret)
    ok_tenants = _call(base_url, "/cron/tenant-followups", secret)
    return 0 if (ok_platform and ok_tenants) else 1


if __name__ == "__main__":
    raise SystemExit(main())
