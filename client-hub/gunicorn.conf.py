"""Bounded image normalization (up to 10 x 6s CPU), PDF validation and AI retry."""
# Original AI extraction has at most two (5s connect + 45s read) attempts.
timeout = 180


def post_worker_init(worker):
    # Default-off, once-only approved synthetic Gemini test in a separate process.
    from kilas_ai.live_gemini_smoke import launch
    launch()
