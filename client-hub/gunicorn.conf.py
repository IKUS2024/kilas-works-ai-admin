"""Bounded image normalization (up to 10 x 6s CPU), PDF validation and AI retry."""
# Original AI extraction has at most two (5s connect + 45s read) attempts.
timeout = 180


def post_worker_init(worker):
    import json
    import os
    from kilas_ai.live_gemini_budget import policy
    # Nonsecret release evidence only; never read keys or dispatch a request.
    enabled = os.environ.get('KILAS_LIVE_GEMINI_ENABLED', '').lower() in ('true', '1', 'on')
    armed = os.environ.get('KILAS_LIVE_GEMINI_QA_ARM', 'off') not in ('', 'off')
    configured = bool(policy())
    print(f'KILAS_GEMINI_GATE enabled={str(enabled).lower()} policy_valid={str(configured).lower()} qa_armed={str(armed).lower()}', flush=True)
    if configured:
        # SELECT-only verification; never create a session or provider request.
        try:
            from kilas_ai.live_gemini_readiness import audience_report, report
            readiness = report()
        except Exception:
            readiness = {'start_eligible':False, 'reason':'readiness_check_failed'}
        print('KILAS_GEMINI_OWNER_READY '+json.dumps(readiness,sort_keys=True), flush=True)
        try:
            audience = audience_report(readiness)
        except Exception:
            audience = {'audience':None, 'nonowner':None, 'nonowner_reason':'readiness_check_failed'}
        print('KILAS_GEMINI_AUDIENCE_READY '+json.dumps(audience,sort_keys=True), flush=True)
    # Default-off, once-only approved synthetic Gemini test in a separate process.
    from kilas_ai.live_gemini_smoke import launch
    launch()
