# Cancelled Learning: remove user-facing surfaces and soft-hide retained output

2026-10-15. Owner reconfirmed cancellation and authorized reversible UI/route
removal and direct main/live deployment. Historical data, incurred usage and
provider configuration must remain intact. Translator (including incremental
processing and speed 0.93), Voice Over and unrelated products remain supported.

## Verified cause and scope

Before edits, main/live were `ecf442c15bbf7c24e873c60a90f06614296dbd0b`.
`learning.PRODUCT_ACTIVE` was already source-disabled, and the production startup
log at 14:57:26 UTC reported `active=false`, `sessions_ended=0`,
`history_retained=true`. There is no evidence the cancelled backend reactivated.

However, the old Learning task tuple, conditional link/icon and feature URL
branch remained in shared navigation templates. More concretely, the common
audio history excluded Live Translator outputs but not Learning outputs. A
read-only owner-scoped production query found **8 completed Learning outputs**
(audio job IDs 138–150), **833199 bytes**, still eligible for Voice Over/history
and generic saved-job links. These are verified residual exposure paths; the
precise location in the owner's screenshot cannot be confirmed here.

Screenshot `libfile_e33a38f80f008191a49f8d1ce8030f2d` resolved to
`1000332865.jpg`, 228524 bytes. The current supported Library helper returned
`download failed`; no pixels were inspected, and no transfer was retried or
guessed. The audit proceeded from the explicit owner report, source and safe
production metadata. The executor was available despite a parent-side
environment-disconnected notice; actual shell/Git/connector calls succeeded.

## Removal and preservation

- Remove the Learning option, icon entry, conditional rendering/context flag and
  feature URL branch from shared Home/task/feature navigation. The same templates
  serve desktop/mobile and refreshed views. Finance's existing entry/form and
  all remaining task controls stay as implemented; no shared CSS/base redesign.
- The Learning home controller now always returns 404, even when archived unit
  tests explicitly reactivate the historical pipeline in Python. Existing
  `PRODUCT_ACTIVE=false` remains source-level authoritative: old enable flags
  cannot open new sessions, input chunks/commits, status or clip APIs (410).
  Generic Home-task/product handoffs also reject Learning. Retained authenticated
  owner End/cancel endpoints are cleanup only, not a feature entry or paid start.
- Filter retired audio by an **owned Learning session/turn relationship**,
  matching audio_job_id or the deterministic turn-id + `-audio` key. This handles
  a crash before the explicit audio link was written, and cannot misclassify an
  ordinary Voice Over merely titled "Learning" or a foreign owner's relation.
  Filter before history counts, snapshot anchors and four-item pagination.
- The common history filter covers Voice Over, upload history and AI Library
  audio listings. The common owned-job guard rejects retired outputs from saved
  job pages, status, script editing/reconstruction and downloads. Internal store
  access/accounting retains the original rows and bytes.
- No DELETE, purge, migration, provider call/key deletion, new plan, global
  session reset, Translator cancellation or financial adjustment is added.
  Learning's previously established deactivation/retention cleanup remains.

The retained-output baseline digest (IDs/status/duration/charged+reserved seconds,
original-script hash and audio hash) is `d9be4ef467f049615a15720cbd29c07f`.
Recheck count/bytes/digest after deployment; preserve all eight rows unchanged.

## Checks and limits

Nine new retirement tests cover common pages and refresh, stale template flags,
permanent home closure, all creation/input/read/audio gates, Home/product
handoffs, source-based history pagination, foreign-owner/title false positives,
generic saved-job rejection and byte/ledger preservation. Existing Learning
pipeline/retention tests remain as internal historical regressions; obsolete
page-render tests now render an isolated archived template fixture, not a public
route. Two old auth-fixture cookie mutations were replaced by the existing
legitimate authentication helper while preserving owner-isolation assertions.

Offline suites: Learning retirement, historical Learning, Audio/history, Home,
unified AI, Live incremental/whole output and session-output retention. Local
Chromium checks use only loopback, synthetic stored MP3/data and blocked provider
network; five 390/1440-pixel cases verify Learning is absent before/after refresh
while pagination, form/file/audio state and the remaining controls work.
No paid AI QA or physical mic capture. Python syntax/diff checks run locally;
ruff is unavailable locally and remains a CI check.

Production verification checks exact main/deploy SHA, startup disabled-state and
readiness markers, post-restart errors and the retained-data baseline. Direct
public HTTP verification may remain blocked by this cloud's outbound CONNECT
403 gateway; do not describe that as an application response or claim real owner
browser acceptance. A pre-existing open browser document changes on refresh;
its old API calls remain denied by the backend.
