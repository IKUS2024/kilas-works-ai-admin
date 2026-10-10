# Immutable offline policy fixtures

These are the exact reviewed owner-supplied offline policy source bytes, with
no MT5/network implementation. validate_trace.py retains the original pin and
fixture-only semantics. The standalone preflight checks all three SHA256 pins
before importing them into an isolated temporary code directory.

The JSON fixture one directory above is synthetic: documentation-only quotes,
synthetic session identity and192.0.2.1 test address. It is never broker evidence.
No private report, account balance/history or credentials are included.
