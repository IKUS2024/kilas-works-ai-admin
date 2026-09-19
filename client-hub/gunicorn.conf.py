"""Allow bounded PDF inspection + extraction/vision fallback to finish safely."""
# Two bounded provider calls can take up to 100s; PDF validation is capped at 8s.
# The default 30s kills the worker before the bank provider's existing 45s timeout.
timeout = 120
