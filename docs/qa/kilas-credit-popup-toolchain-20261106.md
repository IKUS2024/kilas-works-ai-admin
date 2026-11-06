# Credit consent popup: hosted toolchain investigation

Diagnostic source: `3f42232d444954128f69d70f0610f3eac0f04b04`.
[Hosted diagnostic run 42190631465](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/42190631465).

Playwright 1.64.1's Chromium 156.0.8078.0 aborts in
`third_party/blink/renderer/core/timing/window_performance.cc:1051`:
`info.processing_start_time >= render_start_time`, followed by signal 6.
The same native abort occurs on the actual wallet approval popup and a tiny
localhost-only page with no Kilas application, account, provider or customer
data. The independent control without pytest/socket integration reproduces it.
This establishes a browser/toolchain failure outside the wallet implementation;
it does not identify a particular upstream fix or prove every runner resource
limit. The runner reports four CPUs and about 8 GiB of shared memory; cgroup
memory/pid values are unavailable, rather than assumed unlimited.

Both separate headless-shell and full Chromium previously crashed. Switching
headless modes alone did not fix it. In the diagnostic job, Work and Work-step
journeys pass; the wallet popup remains red. No failed result is relabeled.

Local Playwright 1.62.0 / Chromium 151.0.7922.173 passes the guarded and standalone
minimal controls and all original wallet approval, decline, abort, account-bound
resume, duplicate dispatch, locale and viewport checks. Its bundled browser
manifest pins Chromium 151.0.7922.34. The focused CI workflow therefore pins the
released `playwright==1.62.0` toolchain for a hosted comparison under the same
runner, fixtures, assertions and network restrictions. This is a test-toolchain
pin, not a customer-browser setting or a claim that Chromium 156 is repaired.
Hosted acceptance of this pin remains pending until its exact-head run passes.

The minimal regression stays in CI both guarded and standalone. Every real
wallet/Work browser case still runs, and any failed case makes the job fail.
Future toolchain updates must pass the minimal popup and the real financial
consent journeys before changing the pin. No browser security feature, proof
gate, financial assertion or production behavior is disabled by this change.

The application consent JavaScript blob is unchanged from `61bf7b75` through the
diagnostic candidate: `5bec981db3a1d93d972cf079bb28c914d7a92352`. Runtime proof
inputs and retained evidence are unchanged. No paid generation, E2B call,
production mutation, merge, deployment, credential or role change occurred.

Reviewer readiness is independently unresolved: no approved administrative
session is available in the selected environment. A database role/password row
is not evidence that an approved operator can sign in. The smallest owner action
is to confirm an already-authorized operator can sign in to the existing
restricted `/admin/kilas-ai/payments` page; no password should be shared. If no
approved operator controls that access, a separate narrow access decision is
needed. The owner exemption does not confer reviewer privileges.
