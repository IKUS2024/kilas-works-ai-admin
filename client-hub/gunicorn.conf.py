"""Bounded image normalization (up to 10 x 6s CPU), PDF validation and AI retry."""
# Original AI extraction has at most two (5s connect + 45s read) attempts.
timeout = 180
