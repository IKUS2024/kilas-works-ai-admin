## Live Translator focused hardening; production activation pending funding evidence — 2026-10-12

Continued the same worktree and main source 4124a831da6dbcf52fdfb9ee9c503ba7b26eb31a.
That Naskah release is LIVE on Client Hub deploy dep-db6a3uqd0e5s739vjv9g.
Naskah owner mode/owner 9/campaign/caps/price version read back unchanged this turn.
Do not reinterpret the owner's successful dictation test as Translator evidence.

Focused changes only:
- Live readiness now requires its own explicit owner ID and verified OpenAI
  Project ID. That project is passed through the existing AI Chat OpenAI adapter
  using OpenAI-Project; other callers retain their existing headers/behavior.
- Explicitly close the OpenAI stream when leaving translation, retaining usage
  settlement even if stream cleanup fails. End fences downstream stages; already
  dispatched provider work cannot be recalled and can still incur usage.
- Check the existing Voice Over Creator account/disabled-overage/remaining credits
  before Live STT and again before Live TTS; stop on denied/unknown/exhausted credit.
- Owner-mode Live QA admits at most four Live STT attempts/rolling24h independently
  of the old two-attempt QA restriction. Existing Naskah admission is unchanged.
  Future owner mode supports 20 Live/hour, 120 Live/rolling24h, with the existing
  finite monthly STT estimate cap. Do not enable ongoing Live before real QA PASS.
- Retain translated text in the existing supported audio-job original_script
  field and return it only through the owned active session; show text and real
  session state with textContent/aria-live. No new schema or raw source transcript
  in the session ledger. Existing audio reservations/settlement remain authoritative.

Focused local tests PASS: 16 Live backend tests, 23 Naskah/STT tests, 52 Audio tests,
12 JS lifecycle tests. Chromium mocked capture/network/playback PASS at widths
320/360/390/430/820/1440: 3-second silence, no mic during output, automatic resume,
End, late responses, empty speech, permission refusal, pair/voice selection, text
and state feedback, no horizontal overflow. No paid call in these tests.
Impeccable used only on Live presentation; detector advisories concern existing
palette/radii and static Jinja stylesheet resolution, not a new verified defect.
No design-system repair, global audit, Finance, Trading or migration changes.

Live remains OFF. No production paid STT/OpenAI/TTS or internal balance grant this
turn. Existing owner Audio balance is 0; no Live STT operations or active sessions.
IMPORTANT correction to the earlier handoff: usage._qa_quota_exempt already includes
the owner's email by default, and that env override is absent in production. Thus
the existing owner Audio exemption applies despite balance 0. No new balance grant
or billing exemption is needed or made. Live now has its own required finite output
allowance, summing existing owned Live audio jobs: completed actual duration and
conservative reservation for unsuccessful work. Planned QA cap 120 seconds per
rolling24h; ongoing owner mode, only after PASS, uses a finite UTC monthly cap
(maximum configurable 3600 seconds). This does not modify shared Audio billing.
No top-up, upgrade, key creation or overage permitted.

The official connected Chrome browser now works; no URL-security bypass was used.
The existing OpenAI billing tab shows authentication failure. The existing Kilas
tab also redirects to login on an authenticated account navigation. Read-only GET
for gpt-6-luna with the deployed AI Chat key returns 200, but no project identity
headers: model access does NOT establish project billing or prepaid balance.
Requested non-secret production Project ID/name and prepaid/auto-recharge evidence;
previous checkpoint identifies CV Kilas as intended organization. No verification
markers are set to bypass these missing facts.

After funding evidence and source release checks pass: pin the verified project,
admit only owner 9, set KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS=120 (not purchase), activate
Live QA, then ask owner to test /kilas-translator/live with safe short sentences:
1. Indonesia/English + Kilas Male, consent + Start. Speak Indonesian then stay
   silent 3 seconds; verify English text/audio and automatic listening resumes.
2. Speak English in the same session; verify Indonesian text/audio, no echo turn.
3. End while listening/processing/playback; mic indicator/audio must stop, no
   late result plays or listening restarts. Test Kilas Female with one short turn.
4. Report actual results/errors before any real PASS or ongoing-owner activation.
Disable only KILAS_LIVE_TRANSLATOR_ENABLED if necessary; preserve all Naskah flags.

Source commit/push/CI and Client Hub-only dormant deployment pending below.

---

## Owner-reported Naskah PASS; normal owner usage release prepared — 2026-10-12

The owner reports that the real Naskah microphone test succeeded. This is an
owner-reported hardware/transcription PASS, not an independently observed test and
not evidence of any Live Translator test. The owner now authorizes ongoing access
only for their account, existing Creator credits, no top-up/upgrade/overage.

Small scoped patch:
- audio_transcription_budget.py: explicit `owner` usage mode requires the owner
  allowlist, creates a finite UTC-month campaign that renews automatically, and
  applies 20/hour and 120/rolling24h protection only to microphone operation keys.
  QA and other operation types retain the existing two-attempt restriction.
  Existing per-owner/global concurrency, cost reservations, nonce/idempotency,
  cancellation and historical ledgers remain intact. No migration or ledger reset.
- audio_transcription_provider.py: read-only metadata from the same Voice Over
  runtime key; Creator must be active, overage disabled, and remaining credits
  positive before a new normal-mode microphone request. Fail closed on unknown
  funding. Provider quota denial also returns a specific insufficient-credit error.
- audio_routes.py: owner-mode dictation checks provider credit before reservation
  or paid STT and returns clear safe messages. No OpenAI, TTS or balance purchase.
- test_kilas_audio_video_script.py: five regression tests covering monthly/year
  rollover, required allowlist, >2 uses, hourly/daily limits, other-owner denial,
  monthly cost cap, exhausted/unknown credit, disabled-overage enforcement, and
  provider rejection/idempotency/unchanged usage accounting.

Local checks PASS in separate processes: 23 transcription/admission tests,
52 Audio tests, 11 Live Translator tests. Mock Chromium dictation PASS at widths
320/360/390/430/1440, zero paid calls. Final diff whitespace check PASS. Only these
four code/test files and this checkpoint are intended. Finance, Trading, Live
Translator implementation, provider credentials, schema and migrations unchanged.

Planned production settings: KILAS_VO_STT_USAGE_MODE=owner, allowed owner=9,
campaign base=owner9-naskah, global/account monthly estimate cap=22000000 microUSD
(USD22 estimate, NOT an added charge), existing Scribe price version, Naskah ON and
Live Translator OFF. Fixed QA expiry is ignored only in this explicit owner mode.
No perpetual QA campaign, no daily ledger reset, and no global activation.
Release pending commit/push, relevant CI, Client Hub-only deployment and readback.

---

## Naskah owner-only QA access READY; real microphone result PENDING — 2026-10-12 08:30 UTC

Official Render CLI authentication has recovered. Downloaded the official v2.28.0
Windows binary into the task's temporary directory and verified GitHub's SHA256
15eae402a24bbcd03c50f6b9283ee34407a090b53a84c3b788bd337eeb978b1d.
Invoking the supported `render login` reported already authenticated; subsequent
`render services` and a service-configuration GET succeeded. No manual token-refresh
workaround, new API key/account, browser-security bypass or user secret was used.
The previous manual Shell request below is now SUPERSEDED and is not required.

Fresh read-only metadata using the SAME runtime ELEVENLABS_API_KEY used by Voice
Over: tier creator; status active; count 17886; limit 129660; remaining 111774;
max_credit_limit_extension 0; allowed_to_extend_character_limit false;
can_extend_character_limit false; current_overage USD 0. No STT, TTS or OpenAI
paid generation was performed to obtain this metadata. No billing setting changed.
Public billing/PAYG docs explain included subscription credits are used first;
base Scribe v2 price is USD 0.22/hour, already matched by the existing estimate.
Zero internal Kilas Audio seconds is NOT evidence that ElevenLabs credits are empty.
Naskah does not depend on internal Audio balance or on OpenAI.

Authorized configuration-only activation, merged atomically into Client Hub:
- KILAS_VOICE_VIDEO_SCRIPT_ENABLED=true
- KILAS_VO_STT_ALLOWED_OWNER_ID=9
- KILAS_VO_STT_CAMPAIGN=qa-owner9-naskah-20261012-082743
- KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD=10000
- KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD=10000
- KILAS_VO_STT_EXPIRES_AT=2026-10-13T08:27:43Z
- KILAS_VO_STT_PRICE_VERSION=elevenlabs-scribe-v2-20261011-base-022usd-hour
- KILAS_LIVE_TRANSLATOR_ENABLED=false

The USD 0.01 campaign cap is an internal finite STT estimate, not an observed
supplier charge or a promise of exact billing. Existing reservation/dispatch
accounting, no automatic retry, role checks and two shared attempts/rolling 24h
remain unchanged. The active campaign is new; no prior campaign or ledger was reset.
All non-QA owners remain rejected by the existing owner gate. No global activation.

Render env update automatically created ONE configuration deployment:
- service: kilas-works-client-hub / srv-da7ti2psrm7s73dh9i2g
- deploy: dep-db69k8p42hec73be4nng
- source SHA unchanged: ab72eb7f8c234e0258a7e275d22e9a1ebb958983
- LIVE at 2026-10-12T08:29:13.215637Z
No source changes/commit/push, extra deploy trigger, AI Admin deploy or migration.
Remote main independently matched that SHA before the configuration update.

Verification after configuration deployment:
- All eight non-secret configuration values read back exactly.
- Production /healthz status ok, service Client Hub, DB backend postgres.
- Read-only DB confirms email irvankarnavi@gmail.com uniquely matches owner 9 and
  CLIENT_OWNER; both STT tables exist; shared STT attempts last24h=1; inflight=0;
  new QA campaign operations=0. There is ONE remaining attempt in the current window.
- Render error/fatal logs from 08:28:19 through 08:29:58 UTC returned no entries.
- These are configuration/server checks, NOT a hardware microphone/transcription PASS.

Owner test NOW available (expires 13 October 15:27:43 Asia/Bangkok / WIB):
1. Sign in as the owner QA account; open
   https://app.kilasworks.id/kilas-translator?mode=voiceover and refresh once.
2. Put `Naskah awal QA` in Naskah. Click Dikte and grant microphone permission.
3. Say one synthetic sentence for 5-10 seconds, then Stop rekaman ONCE.
4. Verify resulting text is appended, initial text remains, text can be edited,
   and Urungkan dikte restores the prior text. Report actual result/error and time.
5. Do NOT press Generate or repeatedly retry; this scenario needs STT only, no TTS
   or OpenAI. Stop if a quota/provider error appears. No real PASS until owner reports.

To stop: Batal dikte stops a pending recording; it cannot retract dispatched usage.
Server access expires automatically via the finite policy time. For earlier removal,
set KILAS_VOICE_VIDEO_SCRIPT_ENABLED=false in Client Hub and apply the configuration;
keep owner allowlist and accounting intact. Render may apply another configuration
rollout; do not trigger an additional source deploy.

Live Translator remains OFF. Its OpenAI project-funding checks and recorded owner
Audio allowance remain separate and do not hold Naskah. No top-up, upgrade,
overage, new account/key, Trading change or other product change was made.
Kilas AI work stops here pending owner microphone test results.

---

## Creator-credit owner QA authorization — 2026-10-12 08:04 UTC

The owner explicitly authorizes existing ElevenLabs Creator credits for bounded
owner-only QA, with no new account/key, top-up, upgrade or overage. Internal Kilas
Audio seconds are distinct from provider credits. Naskah STT has no Audio balance
or OpenAI dependency and must not be held behind Translator's OpenAI funding gate.

Verified without a paid generation:
- Official ElevenLabs billing documentation says subscription credits can be used
  across products; PAYG documentation says included subscription credits are used
  first. API prices express equivalent usage in dollars; do not infer separate
  mandatory charges solely from that presentation.
- Published Scribe v2 base API rate is USD 0.22/hour; TTS pricing varies by model.
  These are public rates, not a fresh account-specific entitlement/billing result.
- Existing Naskah uses the SAME ELEVENLABS_API_KEY as working Voice Over, Scribe v2,
  persisted finite reservation/dispatch accounting and no automatic POST retry.
- Existing Live uses that STT path, the existing AI Chat OpenAI integration, and
  the existing billed ElevenLabs TTS path. Its separate internal balance gate
  remains in force; zero internal seconds does not mean ElevenLabs credits empty.
- Render confirms deploy dep-db68nbad0e5s739qhqtg still LIVE at
  ab72eb7f8c234e0258a7e275d22e9a1ebb958983. No new deployment was triggered.
- Read-only production DB: owner 9, effective internal Audio balance 0, one shared
  STT attempt in rolling 24h, zero inflight. Existing limit is two attempts/day.

Access blocker: the existing Render CLI session expired at 06:25:29 UTC. A single
read-only service-env request using that existing credential returned HTTP 401.
No refresh-token workaround, alternate credential, browser security bypass or
new API key was attempted. The authorized Render MCP still reads deploy/DB state
but has no env-read or server-shell operation. No provider metadata or paid call
was dispatched during this check. Historical 04:19 UTC Creator credit/overage
metadata is not relabeled as a current account verification.

Required next manual action: use Client Hub's authenticated Render Shell to run
this read-only metadata check and return only its JSON output. It uses the current
runtime key in memory, prints no key, performs no STT/TTS/OpenAI generation, and
makes no configuration or data change:

```sh
python - <<'PY'
import os, json, requests
fields = ('KILAS_VOICE_VIDEO_SCRIPT_ENABLED', 'KILAS_VO_STT_ALLOWED_OWNER_ID',
          'KILAS_VO_STT_CAMPAIGN', 'KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD',
          'KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD', 'KILAS_VO_STT_EXPIRES_AT',
          'KILAS_VO_STT_PRICE_VERSION', 'KILAS_LIVE_TRANSLATOR_ENABLED')
out = {'configuration': {k: os.environ.get(k) for k in fields}}
key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
out['elevenlabs_key_configured'] = bool(key)
if key:
    try:
        r = requests.get('https://api.elevenlabs.io/v1/user/subscription',
                         headers={'xi-api-key': key}, timeout=15,
                         allow_redirects=False)
        out['subscription_http_status'] = r.status_code
        if r.status_code == 200:
            s = r.json()
            safe = ('tier', 'status', 'character_count', 'character_limit',
                    'max_credit_limit_extension', 'allowed_to_extend_character_limit',
                    'can_extend_character_limit', 'current_overage')
            out['subscription'] = {k: s.get(k) for k in safe}
    except requests.RequestException:
        out['subscription_error'] = 'metadata request failed; no retry'
print(json.dumps(out, indent=2))
PY
```

After the current Creator allowance and disabled overage are established, configure
only Naskah for owner 9 with a new finite campaign/expiry; do not re-use the expired
campaign ID with different policy fields. Keep Live OFF until its OpenAI project
funding, reference prerequisites and recorded owner-only Audio allowance are verified.
Render environment updates can trigger a configuration deployment of the same SHA;
do not issue a second trigger_deploy or a source redeploy without a code change.

Current disposition: neither feature was activated in this turn. Real microphone
QA remains NOT RUN, pending the owner's test. No balance/ledger was reset, no
usage was erased, no paid request was made, and Trading was not touched.

Sources checked:
- https://elevenlabs.io/docs/overview/administration/billing
- https://elevenlabs.io/docs/overview/administration/pay-as-you-go
- https://elevenlabs.io/pricing/api
- https://elevenlabs.io/docs/api-reference/user/subscription/get

---

## Owner-operated QA handoff — 2026-10-12; activation blocked, work held

The owner will perform real microphone QA and requested access only for their QA
account, no source redeploy without a change, no top-up or overage, no claimed
real-test pass until results are supplied, and a halt in Kilas AI work while
Trading is handled separately. No Trading work was undertaken here.

Fresh Render read confirms Client Hub deploy `dep-db68nbad0e5s739qhqtg` remains
LIVE on `ab72eb7f8c234e0258a7e275d22e9a1ebb958983`. No deploy, configuration write,
paid call, ledger update or activation was made during this handoff.

Read-only production database evidence:
- QA email resolves uniquely to owner ID `9`, role `CLIENT_OWNER`.
- STT campaign/operation, Live session and Audio balance tables exist.
- The QA account has no Audio balance row: effective prepaid balance is zero
  seconds. Live Translator requires the existing Audio balance; supplier credits
  alone do not satisfy this separate application balance gate.
- Both incumbent branded voice source rows are present; no clone was created.
- One STT operation exists in the last 24 hours and no STT operations are inflight.
  The existing shared rolling 24-hour limit is two attempts, so only one new STT
  attempt could currently be admitted. Dictation and Live share that limit.
- The QA campaign already used in the database is `pc-dictation-20261012-a`,
  global/account caps 1000 microUSD, estimated reserved 191 microUSD, not blocked,
  expiry `2026-10-12T03:30:55.735165+00:00` (10:30:55 Asia/Bangkok). It has expired.
  This is persisted campaign evidence, not a readback of the current process env;
  no fresh active campaign configuration could be inspected by available MCP.
- OpenAI production-key project association to prepaid CV Kilas remains
  unverified. Do not set model/STT/reference verification markers merely to
  bypass readiness. No API credential was read or disclosed.

Activation conditions still outstanding: inspect non-secret active finite STT
policy/expiry and provider verification configuration; verify current CV Kilas
project mapping, prepaid funds and disabled recharge/overage; establish valid
existing QA Audio allowance without a purchase or an unapproved balance grant.
Only then set `KILAS_VO_STT_ALLOWED_OWNER_ID=9` atomically with any enable flags.
Missing owner restriction must never be allowed while enabled. The source
already propagates that restriction through UI, admission, dispatch and worker.
The available Render connector cannot read service env values; its env-update
operation triggers a deploy automatically. Do not issue a blind update or an
extra trigger_deploy, and do not restart the same source merely to recheck it.

Manual next action: supply a non-secret readiness evidence bundle for the QA
account: selected STT policy/owner/expiry fields (exclude all keys and secrets),
CV Kilas project billing/limits evidence tied to the configured production key
without sharing the key, and the intended existing Audio allowance for QA.
No automatic increase in caps or extension of funding is authorized by this note.

### Test instructions — use only after QA-only access is confirmed ready

1. Sign in with the QA account. Open
   https://app.kilasworks.id/kilas-translator?mode=voiceover . Enter an existing
   marker such as `Naskah awal QA`. Click Dikte, allow the browser microphone
   manually, say a short synthetic sentence, then Stop rekaman once. Verify the
   result is appended, the initial text remains, and editing/Urungkan work.
   Do not press Generate: dictation must not initiate TTS.
2. Record the displayed result/error and test time; stop if a cap/funding error
   occurs. Do not repeatedly retry. Each dispatched STT call may consume supplier
   usage, including failed/cancelled requests. With the current remaining daily
   attempt, do not run both paid scenarios in the same quota window.
3. For an admitted Live test, open
   https://app.kilasworks.id/kilas-translator/live . Choose Indonesian/English
   and one existing Kilas voice, consent and Start. Speak one short synthetic
   sentence; wait silently at least three seconds. Verify English output plays,
   then listening resumes. Press End immediately. Confirm microphone indicator,
   audio and active session stop, with no late playback or automatic new turn.
4. Test the reverse English-to-Indonesian direction only when a further STT
   attempt and the unchanged finite budget permit it. Keep utterances short.
   Do not increase daily limits, add supplier funds, enable overage, create a
   voice clone or resubmit uncertain requests. Compare provider usage and the
   application's Audio seconds before/after, treating delayed supplier billing
   as unverified rather than free. Record actual platform/browser and outcomes.
5. A non-QA account must still see the controls disabled and be denied server
   access. No real microphone/provider result is marked PASS pending owner data.

### Stop access

During a session press End (or Batal dikte for dictation); this does not retract
already dispatched provider usage. To withdraw server access, set both
`KILAS_LIVE_TRANSLATOR_ENABLED=false` and
`KILAS_VOICE_VIDEO_SCRIPT_ENABLED=false` in Client Hub and apply the configuration.
Render must apply runtime environment changes, which can trigger a configuration
deployment even on the same source SHA; do not trigger a second source deploy.
Do not remove the owner allowlist, reset balances, erase ledgers or change keys.

Current disposition: both flags were last explicitly saved OFF and remain
unmodified by this handoff; QA access is NOT READY, real testing is NOT PASSED.
Stop Kilas AI work here pending owner evidence/results and explicit resumption.

---

# Naskah microphone and Live Translator — dormant production release

## Latest verified state — 2026-10-12 07:28 UTC

- Main and Client Hub production: `ab72eb7f8c234e0258a7e275d22e9a1ebb958983`.
- Code fix: `7e6da4c36374952dbf294b278f88a39dd4b89174`,
  `Fix Naskah microphone and Live Translator lifecycle guards`.
- Release checkpoint commit: `Document dormant audio release gates and supported browser recovery`.
- Client Hub deploy: `dep-db68nbad0e5s739qhqtg`, **LIVE**, finished
  `2026-10-12T07:27:33.94291Z`. Only Client Hub was deployed.
- Both service flags were explicitly saved as `false` through Render MCP before
  this deployment: `KILAS_VOICE_VIDEO_SCRIPT_ENABLED` and
  `KILAS_LIVE_TRANSLATOR_ENABLED`. No activation or other environment edits.
- All nine GitHub Actions workflows for this SHA completed successfully.
- Public production health and login return 200; both protected audio pages
  redirect unauthenticated requests to login. Six shipped JS/CSS assets match
  the exact Git blobs of the release commit byte-for-byte.
- Render error/fatal and Traceback/Exception queries returned zero logs with
  no pagination from release start `2026-10-12T07:26:37Z` through the check around
  `07:28 UTC`. This is a bounded observation, not a guarantee of future health.
- **Not verified:** authenticated production UI, hardware microphone, real STT,
  translation/TTS quality, provider billing, actual Android/iPad Safari.
  The features remain OFF and are not claimed complete or active.
- User confirmed Settings > Computer Use shows Manage and the correct Chrome
  profile. Computer Use was not retried after repeated URL-confidence denials.
  Next supported recovery step is restarting the desktop app and a new Work or
  Codex chat to clear session state, with the existing tab retained. If it still
  fails, /feedback with the chat ID and exact denial; never bypass URL checks.
- No Trading, Finance, credentials, pricing, schema/migration files, production
  customer data, or AI Admin service changes. No paid provider QA calls.

This final verification entry is saved in the isolated worktree after deployment;
it is a local checkpoint update, not an additional production code change. The
published code and main remain on the SHA above. Earlier entries below are
historical and are superseded by this current release state.

## Passing CI evidence

All runs below target the exact released SHA, with synthetic provider transports:

| Workflow | Run | Result |
| --- | --- | --- |
| Kilas AI Focused QA | 38216656207 | PASS |
| Kilas AI Revisions QA | 38216656267 | PASS |
| Kilas Content Chat QA | 38216656217 | PASS |
| Kilas AI Automation QA | 38216656209 | PASS |
| Kilas Live Translator QA (synthetic + PostgreSQL) | 38216656090 | PASS |
| Kilas Autonomous Agent QA | 38216656246 | PASS |
| Kilas Audio QA (focused + browser + PostgreSQL) | 38216656144 | PASS |
| Kilas Global UI QA (including Finance/localization) | 38216656093 | PASS |
| Kilas Chat Quality V2 QA (including WebKit) | 38216656218 | PASS |

Fresh local verification before publish: 88 Python tests PASS in separate
processes matching CI; 26 Node tests PASS; Naskah mock browser at
320/360/390/430/1440 and Live Translator at 320/360/390/430/820/1440 PASS.
WebKit CI here covers existing chat behavior, not actual iPad audio capture.

Production assets compared exactly: `kilas_dictation.mjs`,
`kilas_transcription_recorder.mjs`, `kilas_live_translator.mjs`,
`kilas_live_translator_engine.mjs`, `kilas_live_translator.css`, `kilas_audio.css`.
These public read-only HTTPS checks did not access the denied browser session,
copy its cookies, or perform authenticated/customer/provider operations.

---

# Naskah microphone and Live Translator — local checkpoint, 2026-10-12

## State and scope

Continued the existing detached worktree `.worktrees/audio-live-20261012` from
`83f2e85b24c7df6df7c1c17b112fb6ff73ce4388`. Existing edits in the original checkout
were preserved. The patch is saved on local branch
`fix/naskah-live-translator-local-qa-20261012`, without push or merge to main.
This checkpoint covers local code and synthetic tests only.
No production browser automation, paid provider test, deployment, feature flag
activation, production migration, or production data change was performed.
Trading, Finance, billing rules, provider credentials, and unrelated features
were not changed.

The last previously recorded Client Hub production evidence was LIVE commit
`06a80e7915682191d237d9462e0d748f126104e3`, deploy
`dep-db64ub942hec73atrhrg`. This is historical evidence from the preceding
checkpoint, not a fresh production verification. The local patch is not on
production. Do not infer activation or release readiness from mock results.

## Focused fixes

- `kilas_transcription_recorder.mjs`: repeated Stop during asynchronous flush no
  longer discards captured data; empty chunks produce a local empty state;
  track removal releases resources; stale recorder errors cannot stop a newer
  recording. Existing explicit gesture/consent checks, 179-second limit and
  supported MP4/WebM containers remain intact.
- `kilas_dictation.mjs`: empty/error states release busy UI, network failure
  clears obsolete processing text, cancellation ignores late responses, hidden
  tabs release the microphone, and archived-script reconstruction blocks an
  overlapping dictation start. Transcript still appends to the latest editable
  Naskah value and never triggers TTS.
- `kilas_live_translator_engine.mjs`: fence callbacks by session and capture
  cycle; late permission completion/rejection cannot cancel a newer session;
  empty capture resumes listening locally without STT, OpenAI, or TTS dispatch.
- `kilas_live_translator.mjs`: handle the recorder's empty state and expose End
  while session admission is pending. Existing silence detection, stop during
  playback, private audio fetch and no-paid-retry behavior remain in place.
- `live_translator.py`, `audio_routes.py`, `home_tasks.py`: pass the authenticated
  owner into the existing readiness gate at display, session admission, enqueue
  and worker boundaries. An owner-restricted preview can admit that owner while
  other accounts and missing-owner calls stay denied. No funding cap or provider
  verification gate was removed.
- Translator-only CSS prevents the active Translator link wrapping vertically
  and gives the local error alert readable contrast. Existing orb image and
  overall layout remain. Module/template cache keys were bumped for changed
  dependencies. No global stylesheet was changed.
- Existing revisions workflow now includes the focused dictation browser test
  and its file triggers. CI itself was not run remotely in this local checkpoint.

## Executed verification

All provider transports in these tests are synthetic. No actual speech-quality,
provider-billing, hardware microphone, Android, iPad, or Safari claim is made.

| Check | Result |
| --- | --- |
| Node recorder + append dictation + Live Translator engine | PASS: 26 tests |
| Python revisions + finite STT/video-script admission + existing Audio regression | PASS: 77 tests |
| Python Live Translator, including owner-restricted HTTP pipeline | PASS: 11 tests |
| Final revisions/video-script recheck after owner propagation | PASS: 25 tests (subset of the 77 above) |
| Local Naskah Chromium mock UI | PASS: 320, 360, 390, 430, 1440 px |
| Local Live Translator Chromium mock UI | PASS including final confirmation: 320, 360, 390, 430, 820, 1440 px |

Naskah browser scenarios: no microphone on load; explicit Start/Stop; preserve
edits made during capture; undo; empty capture makes no upload; permission denial;
server/network failure leaves text intact and clears progress; Cancel while
processing rejects late output; hidden-tab/pagehide release microphone; no page overflow.

Live Translator scenarios: End during pending admission; exactly three seconds
of silence after voice before a single turn; microphone absent during processing
and playback; no self-echo turn; automatic listening resumes after playback;
reverse language pair and existing female alias; End during a turn; empty capture
resumes without a provider turn; permission denial; default-off UI; no page
overflow. Backend tests cover tenant isolation, expiry, duplicates, actual local
media decoding, preserved accounting and cancellation fences between providers.

Impeccable was limited to the changed audio surface. Scoped scans exited 0 with
no primary findings. Advisory-only palette/radius warnings include incumbent
navigation values and the preserved black orb surface; the static template scan
cannot resolve Jinja stylesheet URLs. Local screenshots supply the rendered
evidence. No whole-product audit or design-system rewrite was performed.

Independent source/diff finish review found a stale no-speech recovery permission
rejection that could end a restarted session. The session/cycle guard and exact
regression were added; the regression passes. Reviewer disposition: acceptable
for local/mock scope, with live/provider verification still outstanding.

Local screenshots/reports (not shipping assets) are in the Windows temporary
directory under `kilas-dictation-browser` and `kilas-live-translator-browser`.
Only Chromium is installed for this checkpoint; MP4-only recorder behavior is a
unit simulation, not a Safari hardware test. Existing Python tests emitted
non-fatal temporary-file ResourceWarnings; their assertions passed.

## Remaining access gates and specific user actions

1. Restore the authorized production verification Chrome window with its real
   HTTPS address visible and sign in with the controlled QA account. Computer
   Use previously stopped because it could not confidently determine the
   Windows browser URL. URL policy must succeed in a subsequent verification
   session; do not disable it or bypass it through another browser-control path.
2. Open OpenAI Platform in **CV Kilas**, select the production project, and make
   its project/billing/limits pages inspectable (or supply non-secret evidence).
   Confirm the deployed key belongs to that project, prepaid funds are available,
   and auto-recharge/overage is disabled. A Personal-project balance or an API key
   existing in Render is not proof. Do not paste API keys or credentials.
3. Make the ElevenLabs plan/remaining credits and billing settings inspectable;
   verify STT and existing TTS entitlements against that account with usage-based
   extension disabled. No top-up, upgrade, new clone or paid resource is needed
   for the local checks. A previous immediate balance delta of zero is not proof
   that provider usage is free.
4. Once these gates pass, perform a bounded real microphone Naskah test and a
   bidirectional STT → existing OpenAI translation → existing Eleven TTS live
   session, recording before/after usage. Check actual Android/iPad Safari,
   microphone permission/End/background behavior, perceived latency and voice
   quality. Production rollout/activation and its QA remain separate pending
   work, not a completed feature at this checkpoint.

No large suite, unrelated architecture review, or browser-security workaround
was used to complete the independent local work.

## Release preparation update — 2026-10-12

The user explicitly authorized a dormant code release while browser/provider QA
remains blocked. Do not request the same active Kilas tab again. Both flags were
set to `false` on Client Hub through Render MCP (merge only, no credentials or
other environment values changed): `KILAS_VOICE_VIDEO_SCRIPT_ENABLED` and
`KILAS_LIVE_TRANSLATOR_ENABLED`.

Important connector behavior: updating these two environment variables also
triggered deploy `dep-db68gvijnfac73cr538g` at existing main
`83f2e85b24c7df6df7c1c17b112fb6ff73ce4388`, despite Git auto-deploy being disabled.
The connector has no cancel-deploy tool. This deploy is not evidence that the
local lifecycle patch shipped. A final patch deployment and exact SHA check
remain required after CI passes.

Fresh local checks: 88 Python tests PASS when invoked in separate processes as
in CI; 26 Node tests PASS; Naskah Chromium mock UI PASS at 320/360/390/430/1440.
An initial combined unittest invocation failed because test modules share global
fixture/database state; separate-process runs pass without weakening guards.
The previous main Revisions CI failure was its obsolete disabled-Dikte wording
assertion; this is already corrected by local code commit `7e6da4c3`.
No production provider request or hardware microphone QA has been performed.

Official connection recovery reference:
https://learn.chatgpt.com/docs/chrome-extension#troubleshooting
Check Settings > Computer Use shows Manage for Chrome and the extension is in
the active profile. Update desktop apps, restart the browser/app, and use a new
Work/Codex chat to clear chat-specific connection state if necessary. If that
fails, reinstall through Settings > Computer Use and use /feedback with the chat
ID and exact Windows URL-confidence denial. These are connection recovery steps,
not a documented override of that denial. Do not change blocklists/security
policy or use another control transport to bypass it. JS reset is documented for
timeouts, not as a remedy for a security denial. Paid/provider QA and activation
stay pending until safe URL verification and provider funding gates pass.

The original dirty checkout remains untouched. Only the isolated audio worktree
is used. Final CI, exact release SHA, deployment status and public endpoint/asset
verification will be appended after execution; no authenticated production
feature success is claimed at this checkpoint.
