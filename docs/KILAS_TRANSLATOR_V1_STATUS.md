# Kilas Translator v1 checkpoint — 2026-10-04

**Client Hub release LIVE; authenticated production UI/preservation QA passed. ElevenLabs activation and real audio generation remain blocked by missing server configuration.** The source release is `3060290d825d5515401014f472d0a996f20b1e3f`, with all eight CI workflows green. This record preserves initial-checkpoint limitations below and appends completed release evidence. The final documentation-only commit will contain the identical application tree and must be deployed to keep main and production aligned.

## Product and implementation

Kilas Translator is an authenticated CLIENT_OWNER utility at `/kilas-translator`, exposed from the product start/navigation. It has two modes: Translate uploads MP4/MP3/WAV/M4A and translates the audio track; Voice Over turns a script into speech with a curated provider-account voice. Both produce a private MP3 preview/download. Video output is not produced. The white Manrope/orange workbench extends the incumbent customer design; existing DESIGN.md and .impeccable/design.json are preserved.

Translate offers Auto Detect and explicit source/target languages. Provider-detected source language is persisted when it belongs to the supported language allowlist; unsupported or absent metadata retains Auto Detect. Upload inspection reads actual media duration before submission. Defaults are 25 MB and 600 seconds; environment limits are bounded at 50 MB and 600 seconds. Local FFmpeg decoding validates signatures/MIME, extracts only the first audio track and restricts protocols to local files/pipes. Voice scripts accept 1–4,000 characters. The UI shows an estimate and conservative reservation; those do not promise final duration.

Recent history, job states and results persist per owner. A completed job displays a native audio player, Download MP3 and its recorded charge. Status polling resumes persisted Dubbing jobs without issuing another paid submission. Queued/processing, missing-provider, zero-balance, insufficient-balance and failure states remain explicit. History timestamps display UTC date and time. Private media responses prohibit shared caching and enforce owner access.

## Shared prepaid Audio seconds

| Pack | Seconds | Price |
| --- | ---: | ---: |
| 1 minute | 60 | Rp19.000 |
| 5 minutes | 300 | Rp89.000 |
| 10 minutes | 600 | Rp169.000 |

Audio balance is shared by Translate and Voice Over and is separate from Kilas AI subscription capacity. Translate settles `ceil(source_ms / 1000)`; Voice Over settles `ceil(actual_generated_mp3_ms / 1000)`. Reservations make pending work unavailable for another request without deducting the final charge early. Completion settles once; failure releases the reservation. Output exceeding the allowed reservation fails without deducting balance. Only the existing internal QA allowlist supplies exemption; ordinary accounts require paid seconds.

Account locks, one concurrent active Audio operation, owner/operation-key uniqueness and stored fingerprints protect reservation/settlement. Paid provider POSTs are not automatically retried after ambiguous failures. Stranded work expires after the existing three-minute unsubmitted or two-hour provider timeout bounds. Purchase uses dedicated Audio orders and the incumbent bank-transfer details; proof upload and authorized admin verification credit seconds idempotently. Audio purchase does not activate or alter a Kilas AI subscription.

## Provider boundary

The adapter uses ElevenLabs Dubbing v1 for Translate and `eleven_multilingual_v2` for Voice Over with `mp3_44100_128` output. The release owner reports verification against current official provider documentation. Source confirms the TTS payload does not send unsupported `language_code`: the model detects the script language. The language selector records intent and asks the user to write in that language; it does not enforce or translate the script.

Voice choices come from actual voices available in the configured account, with stable preferred-name/provider-ID ordering and at most four male plus four female choices. The interface must not promise all eight when fewer account voices are available. The API key is read on the server and sent only in the provider authentication header.

Read-only Render environment inspection reported `ELEVENLABS_API_KEY` absent. Configuration requested by the owner remains pending; no secret belongs in chat or this file. The authenticated QA session had expired and the login browser window on port 9333 was opened for the owner's continuation. **Real ElevenLabs processing, account voice availability, voice preservation, generated-speech quality and live billing consumption have not been exercised.** Synthetic provider fixtures cannot establish those outcomes.

## Schema and protected behavior

Additive migration 0083 introduces Audio balances, orders and jobs; its scoped PostgreSQL release function adds the Audio checksum release table and applies the migration once under an advisory lock. The SQL contains no Finance-table alteration. The native PostgreSQL test rehearses an isolated disposable loopback schema, checksum/idempotency, concurrent verification/reservation, byte storage, single settlement, ownership and unchanged FREE subscription entitlement. That test is authored and pending CI execution.

Audio uses existing authentication, CSRF, account-lock and payment-review authorities. The implementation intent is no Finance, Google or Assist business-behavior change. Shared navigation and integration edits belong to the current larger worktree, so protected regression results remain required release evidence; additive source review alone does not certify production preservation. Existing video capacity gates are retained and expose zero/exhausted quota before paid model work or project creation.

## Evidence supplied by the build thread

| Check | Checkpoint result and limit |
| --- | --- |
| Focused Audio backend | 25 tests PASS locally; provider calls mocked |
| Audio browser | PASS at 320, 360, 390, 430, 768, 1024 and 1440px; synthetic upload, shared seconds, MP3 play/download, voice choice, history/reload, checkout/paywalls, white controls, native file-selector style and unbroken prices; no overflow or JavaScript errors |
| Independent finish reviewer | **ship** verdict pass; three material fixes scored resolved: native file-selector readability, tablet pricing wrap, UTC history date/time. This verdict scores that fix list, not real-provider behavior |
| Design context/detector | Ran once in the build thread; historical Assist-only PRODUCT context drift reported and left untouched |
| Kilas AI | Usage/tools/connectors/hardening/i18n suites PASS locally |
| Global UI | Browser acceptance PASS locally |
| Kilas Video | Four unit suites and storyboard browser acceptance PASS locally |
| Finance/Assist | Local runs reached Windows `WinError 32` while removing temporary SQLite databases; a clean Linux CI pass remains required. These are not recorded as passing runs |
| PostgreSQL 0083 | Targeted native additive/accounting test authored; execution pending CI |
| CI/release | No push, CI or deployment at this checkpoint |

`.github/workflows/kilas-audio-qa.yml` defines separate Ubuntu focused, Chromium browser and PostgreSQL 18 jobs. Browser artifacts are captured by the test into the temporary `kilas-audio-browser` directory. The latest reviewer packet copied into `.impeccable/review` is exactly: `translate-320.png`, `translate-360.png`, `translate-390.png`, `translate-430.png`, `translate-768.png`, `translate-1024.png`, `translate-1440.png`, `voiceover-390.png`, `result-390.png`, `paywall-360.png` and `invoice-430.png`. Documentation visually inspected the current tablet Translate and mobile result captures, confirming readable file controls, intact pack prices and explicit UTC history time. Auxiliary `pricing-768.png` predates these fixes and is not current verdict evidence. The focused 25-test suite was rerun PASS after detected-source persistence was added, as reported by the build thread.

## Documentation handoff

The ordinary-extension record is `.impeccable/surfaces/client-hub-templates-kilas-translator-home-html.md`. Documentation checked PRODUCT.md, the newest master-status entries, DESIGN.md, Impeccable document/new-work guidance, Audio templates/CSS/JS, provider/service/routes/store/media/schema, migration and focused/browser/PostgreSQL test sources. Root system files were preserved. Historical PRODUCT audit-only language is disclosed as pre-existing drift and has not been repaired or promoted into the current Audio direction.

Before a release is claimed complete, append the exact reviewed source commit/tree, clean required Linux CI and native PostgreSQL results, final capture locations, provider configuration/live QA outcome, approved deployment IDs and production verification evidence. The release owner will append that evidence; this checkpoint does not imply those steps occurred.

## Release progression ? 2026-10-04

Implementation committed and pushed directly to main: `3060290d825d5515401014f472d0a996f20b1e3f` ? `Release Kilas Translator with shared Audio Balance and Video quota gates`. All eight workflows passed on this exact commit: Audio QA 37189842596; Video QA 37189842656; Global UI QA 37189842630; AI Focused QA 37189842624; Chat Quality V2 QA 37189842567; Autonomous Agent QA 37189842598; AI Automation QA 37189842612; Client Session Timeout QA 37189842574. Native PostgreSQL Audio and Video jobs passed. Finance/Assist Linux regression checks passed, resolving the release concern from Windows temporary-file locks.

Only existing Client Hub `srv-da7ti2psrm7s73dh9i2g` was triggered: `dep-db116rnavr4c739pdrcg`, at 2026-10-04T08:50:54Z, exact implementation SHA above. Deployment was still building when this entry was written. No AI Admin, Cron, new resource, plan upgrade or environment modification was made. Only targeted additive Audio migration 0083 is added to production boot; no data reset or existing Finance/Google/Assist logic change. Unrelated pre-existing dirty worktree documents and line-ending-only files remain excluded from the release.

Last configuration/session probe: ElevenLabs key absent; production QA login expired. The owner was asked to configure the key directly in Render (no key in chat) and sign in again in the existing verification window. Real provider QA and authenticated internal-account production QA remain pending. Normal zero-balance production QA is prepared with one isolated synthetic account and will run only after LIVE.

## Production verification ? completed 2026-10-04

Source deployment `dep-db116rnavr4c739pdrcg` became LIVE at 2026-10-04T08:51:56Z on `3060290d825d5515401014f472d0a996f20b1e3f`. `/healthz` returned 200, status ok, PostgreSQL backend. Authenticated Translator renders demonstrate additive Audio tables are available. The isolated native PostgreSQL CI rehearsal passed before deployment; no historical migration replay or data reset was requested.

Executed against https://app.kilasworks.id:

- One isolated synthetic normal account registered via the normal flow. Translator exposes zero-balance paywall, both processing buttons disabled; direct job POST returns 402/zero_balance. Video missing-quota paywall disables generation; direct plan POST returns 402/video_quota_missing. No provider job was generated for that account.
- Translator Translate/Voice Over layouts and pricing passed no-horizontal-overflow at 320, 360, 390, 430, 768, 1024 and 1440px. Home links to Translator, official Services https://kilasworks.id, and no normal Assist/workspace navigation.
- Existing controlled internal account has no zero-balance paywall. A direct synthetic submit reaches 503/not_configured instead of a balance denial, proving the server-side exemption without creating a provider job or debit.
- Authenticated Home, Kilas AI, Google connections, Kilas Video, Settings, Finance Home, Finance balances, Finance transactions, Finance invoices and Finance reports loaded successfully and had no overflow at all seven widths. Finance/Google screens were only read.
- Existing controlled Video project reopened with storyboard image and final video prompts; copied all image prompts, all video prompts and the complete package to the clipboard and checked exact content. Refresh preserved the active revision; the project fit all seven widths. No new Video generation was invoked.
- One short synthetic AI Chat arithmetic test received its real streaming answer, remained persisted after refresh, and did not refocus the coarse-pointer mobile composer at completion.
- Production finance_ui.js, finance_ui.css, kilas_video.css and kilas_ai.js matched normalized pre-release baseline assets. No Finance calculation, ledger, route, Google connector, WhatsApp or hidden Assist source was modified by this release.
- Render app error/critical log query from 2026-10-04T08:51:56Z through the post-QA check returned no entries (hasMore false). This describes that log filter/time window, not an unrestricted error-free claim.

Production evidence is `%TEMP%/kilas-audio-production-qa/report.json`, plus seven zero-balance screenshots in that folder. It contains no credentials or provider key. The only new production QA data were the isolated synthetic account and a controlled synthetic Chat conversation; unrelated customer data and existing payment/Finance records were untouched.

### Remaining activation requirement

Final read-only Render configuration probe still reports **ELEVENLABS_API_KEY absent**. Actual ElevenLabs voices, real Dubbing output and real TTS output were **not tested**. Translate/Voice Over provider code and MP3/accounting flows passed mocked CI; they are intentionally unavailable in production until the owner adds the key directly to Client Hub Environment. No secret should be sent in chat. After configuration, run exactly one very short controlled Voice Over and one Translate with the internal account; do not repeat paid submissions automatically. Missing-key internal submit safely returns 503 and normal zero-balance returns 402 first. No provider charge was consumed in this QA.

### Final alignment procedure

This checkpoint is a documentation-only follow-up to the fully green and production-verified source commit. Confirm application tree equality to that commit, push this document to main, wait for checks triggered by the document commit, and deploy only existing Client Hub again. Report the resulting final HEAD SHA and LIVE deployment ID directly in the final release response; no additional paid QA generation is needed for the identical application tree.
