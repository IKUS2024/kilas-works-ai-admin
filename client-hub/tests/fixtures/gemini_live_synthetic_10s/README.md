# Ten-second nonprivate QA sources

The existing offline eSpeak NG sentences are preserved in full, sped up with
FFmpeg `atempo=1.6`, then silence-padded to exactly 10 seconds, mono PCM16/16kHz.
No paid generation, recorded person or clone is involved. These fast synthetic
voices test protocol and direction; they do not establish natural speech quality.
Source text is the same as ../gemini_live_synthetic/README.md.

Prepared harness: `python -m kilas_ai.live_gemini_smoke_10s`. Default OFF and not
registered in startup. Exact run marker gmlqa20261023-10s, two independent tests,
no retry, 10 seconds source each, 30 seconds accepted output each, 45-second
connection deadline, maxOutputTokens=512, process alarm105s, existing once-only
PostgreSQL marker and cleanup, retained reserve $0.10 each. Received token usage
is observed and stops at $0.09 per test. Source generation cost is zero.

Do not arm until provider-side total output bounds are established. Local output
and time guards bound what the app receives; they cannot retroactively cap tokens
generated upstream. A ledger reservation is not a provider invoice ceiling.
