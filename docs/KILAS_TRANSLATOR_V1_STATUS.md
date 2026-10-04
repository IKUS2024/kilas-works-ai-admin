# Kilas Translator v1 checkpoint — 2026-10-04

**Implemented locally; release, CI and real-provider QA pending.** This checkpoint records the Audio implementation and supplied local evidence, not a production release. All task edits remain uncommitted on main at this checkpoint. Production baseline supplied by the release owner: `64913babbbe66349736b3886a2296f38763ea72a`, LIVE deployment `dep-db10746gekts73bj1vng`; Client Hub service `srv-da7ti2psrm7s73dh9i2g`.

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
