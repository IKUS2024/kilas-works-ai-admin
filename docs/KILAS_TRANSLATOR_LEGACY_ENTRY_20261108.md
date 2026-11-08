# Translator legacy-entry repair

Baseline: `5968534f8b8d03b6095ac5ed2262caf5038482d7`.

The reported screenshot was inspected as pixels. Production read-only browser
inspection reproduced its exact allowance warning on `/kilas-translator/live/gemini`.
The current `/kilas-translator/interpreter/readiness` simultaneously returned
`available: true`, `funding: operator`. The old entry page was checking the
historical native trial ledger, not the current interpreter funding policy.

The legacy GET now redirects to the current interpreter only when operator
funding is explicitly configured, the interpreter is ready for this authenticated
account, and no unexpired active legacy/classic session exists. This also repairs
old bookmarks and the existing Classic return link. Active sessions retain their
original protocol and explicit End/recovery; their rows are never migrated by
navigation. Trial-only and unavailable configurations retain their existing gates.

No funding, balances, historical charges, consent, provider credentials, voice
transport, POST endpoints, Finance, payment configuration or production data changed.

Validation:
- Six new authenticated route regressions. Four failed on the unchanged baseline;
  all six pass after the seven-line route fix.
- Route fixtures cover exhausted trial/operator owner and member navigation, exact
  ledger/balance/session preservation, active one-way/pair v1/pair v2/classic,
  explicit End, expiry, Classic return navigation, anonymous/disabled accounts,
  disabled feature, invalid funding and missing provider key.
- Seven offline Python suites pass: new entry, interpreter, legacy pair routes,
  legacy Gemini, native budget, AI Call and audio. Network blocked by the repository
  offline runner. All 44 interpreter JavaScript lifecycle tests pass.
- Focused Ruff E9/F and diff whitespace checks pass. New route suite added to both
  applicable Gemini CI test lists.
- Native-streaming CI initially stopped before tests because ubuntu-latest moved
  to Ubuntu 26.04, unsupported by the pinned Playwright 1.58.2. That job now uses
  Ubuntu 24.04; all test steps and assertions remain intact.

These checks do not certify real speech recognition, translation quality or
physical-device microphone/speaker behavior. No paid provider QA was performed.
CI, merge and deployment outcomes must be verified separately for the final SHA.
