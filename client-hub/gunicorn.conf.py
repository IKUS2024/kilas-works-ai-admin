"""Bounded image normalization (up to 10 x 6s CPU), PDF validation and AI retry."""
# Original AI extraction has at most two (5s connect + 45s read) attempts.
timeout = 180


def post_worker_init(worker):
    import os
    from kilas_ai.live_gemini_budget import policy
    # Nonsecret release evidence only; never read keys or dispatch a request.
    enabled = os.environ.get('KILAS_LIVE_GEMINI_ENABLED', '').lower() in ('true', '1', 'on')
    armed = os.environ.get('KILAS_LIVE_GEMINI_QA_ARM', 'off') not in ('', 'off')
    print(f'KILAS_GEMINI_GATE enabled={str(enabled).lower()} policy_valid={str(bool(policy())).lower()} qa_armed={str(armed).lower()}', flush=True)
    # Default-off, once-only approved synthetic Gemini test in a separate process.
    from kilas_ai.live_gemini_smoke import launch
    launch()
