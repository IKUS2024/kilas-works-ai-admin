# Native Translator continuous-session implementation — 2026-10-16

## Release scope and actual verification

This release implements bounded physical connections within one owned logical
session. It remains **safe OFF**. No provider inference, real microphone capture,
browser test, credential change, supplier-setting change or funding purchase was
performed for this implementation. Synthetic sockets, PCM, DOM and clocks prove
application behavior only; they do not establish audible Android quality or the
provider's final-word behavior.

Baseline remote main was `bcd2fce734b6b325a3d96a4a015b92b17eb97f69`.
Implementation tasks were delegated to GPT-6.1 Sol agents at `ultra` reasoning
as explicitly requested, with integration and independent review in cloud.

## Continuous session and final audio

One Start owns one session until End. The same AudioWorklet/microphone remains
active through technical connection renewal. Initial VAD/pre-roll is preserved:
standby before the first voice sends no PCM to a provider. After first voice,
PCM including subsequent silence continues, and ongoing usage is disclosed.
The shared capture's continuous option is opt-in; original Translator capture
retains its silence/idle/utterance behavior.

A physical turn receives at most 59 seconds of client PCM within the server's
60-second input cap. At its boundary, every sample is partitioned exactly once:
subsequent samples enter a bounded carry queue rather than being replayed to the
old connection. The old input is flushed and sends audioStreamEnd once. The
next turn starts only after old output closes and every accepted frame has been
cursor-consumed. It uses a new operation key and a new durable budget reservation
before the provider connection. No automatic retry/reconnect/regeneration exists.

The player retains one audio clock across turns. Renewal does not cancel old
accepted audio. A reset is scoped to the corresponding provider turn. Terminal
responses are parsed for valid final frames before handling failure, and generic
technical errors stop capture/network work then drain the accepted PCM queue.
A stalled/failed player and explicit End still cancel immediately. End invalidates
late admissions, owns only its session, and blocks further renewals.

The continuous model does not promise final turnComplete. A qualified terminal
turn still sets `tail_confirmed=true`. Otherwise a fixed four-second post-EOS
receive window closes the physical transport with `completion_kind=bounded_drain`,
`tail_confirmed=false` and `tail_code=gemini_tail_unconfirmed`. COMPLETED here
means bounded connection/accounting completion, **not proof of full translation**.
The UI retains that warning while playing the received audio.

The [official example](https://github.com/google-gemini/gemini-live-api-examples/blob/3bcae1162d1bc6955672153310e4f84eba6621ff/command-line/python/translate.py)
also waits four seconds after sending input, then cancels. This supports a finite
transport window, not a semantic completion guarantee. No silence, socket close
or generationComplete alone is promoted to proof of the final word.

Server hard lease remains 90 seconds and includes admission delay. Durable
reservation-to-dispatch age is at most20 seconds, leaving headroom before the
existing 120-second stale-operation fence. End is rechecked after durable dispatch
before connecting. Admission cleanup always releases its transport semaphore,
even if one accounting cleanup fails. Finished same-session RAM relays can be
removed when the next fully consumed turn is admitted, avoiding a four-turn limit.
Standing native rate accounting treats renewals of the same logical session as
one user start, with existing20/hour and120/day admission limits; other Live/STT
operations still count individually. A separate80-native-leases/hour guard
bounds manual rapid renewal. Historical QA remains conservatively counted.
No operation-key/nonce replay fence or cost reservation is relaxed.

Every scheduled audio node has a wall-clock deadline, so a slowly advancing
audio clock cannot keep playback or a failure drain pending indefinitely.
Input carry and pending playback each retain their existing eight-second bounds.
Exceeding them stops visibly, without replaying omitted/unaccepted input.

## Conservative local allowance

Parent supplied read-only billing evidence: Rp500,000 loaded, split into
Rp450,450 prepayment + Rp49,550 VAT11%; walletRp499,829 reflects Rp171 booked,
while spend pageRp462.47 is higher and not reconciled. These are not interchangeable
final usage figures. Auto-reload is OFF. The actual USD/IDR billing conversion
was not shown. [Google billing](https://ai.google.dev/gemini-api/docs/billing/#prepay)
allows overages during approximately ten minutes of billing latency.

The owner approves **totalRp500,000 including historical usage and tax**, no
automatic top-up and owner-only use. `owner_lifetime` has no QA expiry and counts
all retained `gml-` allowances, including the historical USD0.40 across four
provider dispatches, unknowns and cancellations. Campaign rotation cannot reset
that total. Do not add the same dashboard transactions twice.

The new explicit `conservative_internal` valuation mode distinguishes an internal
accounting assumption from verified actual FX. It requires affirmative configuration:

| Setting suffix after KILAS_LIVE_GEMINI_ | Meaning / proposed value, not set live |
| --- | --- |
| POLICY | owner_lifetime |
| TOTAL_IDR | 500000, inclusive of tax/historical use |
| IDR_VALUATION_MODE | conservative_internal |
| INTERNAL_VALUATION_ACK | yes, explicitly acknowledges an assumption |
| IDR_PER_USD_INTERNAL | 25000; minimum allowed, not claimed actual FX |
| INTERNAL_GUARD_IDR | 250000 maximum, within approved total |
| BUDGET_MICRO_USD | 10000000 proposed, including historical allowance |
| LEASE_RESERVE_MICRO_USD | 250000 minimum in this mode |

Existing enable/billing/owner/campaign checks still apply, with no spending defaults.
The immutable campaign policy pins valuation/guard/approval; changing them under
the same campaign fails closed. The read-only status helper is advisory only;
actual admission/dispatch remain authoritative under the PG lock. At the proposed
values, USD0.40 historical +38 newUSD0.25 reservations =USD9.90. This is a local
conservative admission bound, **not an absolute supplier invoice guarantee**.
No financial period auto-renews, no historical cost is refunded, and no new
approval or funding is inferred from an installed key.

## Synthetic-only private capture

Only trusted server code selecting the pinned ID/EN fixture can mint a capture
capability. It verifies the canonical WAV SHA, PCM format, every ordered input
chunk and complete input finish before publishing. Ordinary browser/microphone
routes accept no capture option and cannot mint this capability. Passive smoke
instrumentation does not arm or execute any new paid test.

The bundle contains `source.wav` (16kHz), `output.wav` (24kHz) and `timeline.json`.
The output records raw received provider segments, not audible playback. Resets,
byte offsets, transcript/protocol events, numeric usage and terminal diagnostics
are recorded so an analyst can reconstruct generation changes. Content or
credentials are never emitted in logs. Missing, partial or mismatched fixture
input cannot be persisted.

Exports are bound to configured QA owner ID/email plus a fresh DB CLIENT_OWNER
check, independently of paid activation. Storage is private temporary0700/files0600,
opaque identifiers, at most four bounded bundles, ten-minute TTL cleanup and no
arbitrary caller path/URL. Normal session audio remains RAM-only. Bundles may be
lost on deployment/restart; this is not durable audio history.

Authenticated read-only routes, all private/no-store/nosniff:

- `GET /kilas-translator/live/gemini/fixtures` lists available owner bundles.
- `GET /kilas-translator/live/gemini/fixtures/<opaque>/zip` downloads the bundle.
- The final kind may instead be `json`, `wav` or `source.wav`.

Exports work while Gemini is OFF and after fixture cleanup End. There is no
HTTP capture-start or arbitrary-upload capture route. One future explicitly
chosen synthetic test can produce an artifact that is listened to and analyzed
repeatedly offline for final-word alignment, silence, repetition and sample rate
without additional paid inference. This release does not execute that test.

## Activation requirements remaining

Review exact release/CI and choose explicit owner-only local policy values within
the existing authorization; acknowledge conservative valuation honestly rather
than set a false verified-FX flag. Reconcile any usage outside the local ledger,
keep supplier auto-reload OFF, and retain billing-lag headroom. No new key,
subscription, purchase or supplier cap mutation is required by this code release.

The first real-wire/device validation remains outstanding: actual final-word
completeness, source/target quality, first-audible delay, output timing and
headset/speaker behavior. All unconfirmed-tail warnings must remain visible.
Budget reservation, graceful transport completion and successful mocks alone
must not be reported as verified end-to-end speech.
