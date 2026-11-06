# Credit activation gates — November 6, 2026

This is an inactive implementation checkpoint. Production activation, configuration, schema/backfill, public PR publication, merge and deployment remain held. No paid API call, real transfer, new credential, role grant or access change was made. This continuation starts from `33c86e61e4f40a9ce012a5b14f6be7d112dc7867`.

## Completed inactive code

Existing Work text, public search, watch extraction, default/selected document authorship, generated code and native project authorship now share account/job/step-bound wallet consent. The candidate requires explicit `work_allocation=per_successful_logical_step`; there is no default Work tariff or Free Work allowance. Quiet watch observations additionally require explicit `watch_billing=per_completed_observation`. These are supported candidate semantics, not accepted customer terms.

Each logical step has a stable request identity, an exact input/configuration fingerprint, a spending ceiling and a durable dispatch fence. Internal provider requests have bounded operation/model/call/input/output contracts and hash-only audit records. They do not become extra Chat messages or spend legacy premium capacity after the Work wallet has paid. Unknown delivery retains the hold and cannot create a fresh paid attempt on restart. Known pre-dispatch failure releases it. Successful settlement occurs in the same transaction as the durable job result; completed steps survive the consent pause. Active jobs cannot be financially reconciled from underneath a worker.

Owner exemption still uses the exact server identity. Existing real paid plans retain legacy Work access and accounting. Deterministic local file creation and explicit local code inspection/patch/diff do not acquire a fabricated AI tariff. Sandbox execution, projects requesting execution, market-provider charging and automatic model planning remain gated for new wallet customers. No legacy execution credit is converted or charged alongside a new wallet fee.

The disabled cutoff candidate now loads an immutable activation version, policy-release identity, tariff digest, meter version, schema checksum and baseline checksum. Under explicit candidate configuration, it holds new customer admission until the record is valid and credit admission is enabled. Strict preparation checks actual pending operations and authoritative successful history rather than trusting a zero-count snapshot claim. Lifetime image history cannot disappear on restart. Missing source-duration evidence fails review rather than becoming guessed minutes or a renewed trial. Baseline replay is idempotent; no historical debit or purchased-balance conversion is performed.

Candidate guards cover the common AI admission, standalone Audio, Translator turn admission, Interpreter creation and new AI purchases, including the obsolete legacy monthly/expiring purchase endpoints. Already accepted Work/Translator child operations retain their captured funding and can settle after rollback. Issued wallet invoices and private proof review remain reachable after new purchasing is disabled; bank transfer instructions are hidden while paused. New purchases and new spending consent remain disabled. Existing legacy invoices and balances are unchanged.

Candidate configuration is **not installed**. It requires a separately reviewed additive migration, a fresh aggregate audit under the admission hold, drain/classification of accepted operations, complete authoritative baselines and approved configuration before any activation. A code candidate is not evidence that this production procedure has occurred.

## Evidence and access limits

OpenAI's current [token-counting documentation](https://help.openai.com/en/articles/4936856-understanding-and-counting-tokens) explicitly states that `/v1/responses/input_tokens` is free and separate from generation. The [API reference](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count) defines a count response, not generated content, and accepts complete Responses inputs. The [GPT-6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) supports Responses. Existing synthetic contract tests verify exact count/generation payload equivalence, image/category/text bounds, a 32,000-input-token ceiling, 2,048 output tokens, timeout/malformed/over-limit denial and success-only customer receipt settlement.

No existing OpenAI key is available in this executor. Deployed model/endpoint access was therefore not probed, and no credential was obtained or replaced. Real-image readability and generation quality remain unverified; counting a payload cannot prove extraction quality. Those require an authorized existing-runtime check and separately authorized generation/quality testing. The previous uncertainty about whether counting itself bills is resolved by primary documentation; it is not an outstanding pricing question.

A bounded read-only audit found one existing admin reviewer account and no owner-to-admin exemption. Admin login uses a signed browser session; no authorized admin session is accessible to this executor, and a role/password record does not prove an identified operator can sign in. The smallest owner action is to confirm an already-authorized reviewer can sign in and reach the restricted payment-review page. If no approved operator controls that account, identify the reviewer and separately authorize the narrow access change. Do not share a password in chat, grant admin to bypass billing or broaden proof access.

Fresh read-only aggregates at `2026-11-06T05:22:28.422292Z` and `2026-11-06T05:24:30.219355Z` found zero non-owner current Interpreter leases, completed translation jobs requiring source classification, nonterminal Work jobs, active Audio jobs, pending AI operations, active supplier operations or live turns requiring drain/classification. No personal rows, transcripts, payment data or balances were exported. This observation must be repeated at actual cutover; it is not a permanent waiver of the audit.

### Exact-source runtime proof follow-up

The read-only retained receipt is `SUCCEEDED`, with a completed job, confirmed cleanup, document PASS and download validation. Its recorded runtime is `cp311`, with root-owned wheels, no network install and no host execution. Its document fingerprint is `7eba594fa618d6caf8f2836e8ef4cac6a657904a6e52147ee8db92f4c0411472`. This is retained evidence for its original source, not candidate acceptance.

| Source | Large fingerprint | Document fingerprint |
| --- | --- | --- |
| Repository base `5968534f` | `a3a10d9a4380c4f578cff6b9739679f177ca939fac823a4227c0b75377e51178` | `acd2f39d38889988de001d9ebe92e8c16cf1de2bf12f490655d30315aa06c86b` |
| Earlier feature base `33c86e61` | `ac61d50a98985651603ef59c932e62c80711f9834cd61df8f266140538a57344` | `f8196aa2e1cd22c087776b7200a87a65b9a9351e83691af8a09150ed08bef154` |
| Inactive candidate `d57dc816` | `82c16050c071c11a2a60653df21e4b44ebd43b18f31f76067b859f4b1b8aa939` | `76e3c4ec15ce1a5ec879c1f957c28264f6a6e0a40ee70929b0a4a1a6ee7a1d97` |

The only large-profile fingerprint input changed between `33c86e61` and `d57dc816` is `autonomous_runner.py`. General execution boundary, access, credit and compatibility-verifier files are unchanged from `5968534f`. None of these base/candidate document fingerprints matches the retained receipt; the mismatch was not first introduced by this last continuation. This comparison does not assert what source is currently deployed.

Fresh acceptance was not attempted. `document-runtime-20261019-v1` is already consumed and its approval expired on October 20, 2026 at 10:02:37 UTC. The contract requires a real isolated E2B runtime, verified boundary evidence, actual generated/downloaded documents and confirmed teardown. This executor has neither the E2B SDK nor an existing E2B key. A local synthetic PASS cannot replace that evidence. A separately reviewed candidate-bound acceptance procedure, authorized existing runtime access and explicit bounded paid-VM authorization are required before that action can proceed. No expiry, operation key, source pin, receipt, approval flag or runtime guard was changed.

All 15 focused document-runtime and large-proof tests pass offline. Added regressions mutate runner bytes only inside a mock, verify both fingerprints change and capability fails closed, preserve the original synthetic receipt byte for byte, and reject replay despite a synthetic armed approval. These are validator tests, not a claim of remote acceptance. No broad suite was repeated for this test/document-only follow-up. The remaining pricing, operational access, receipt quality, migration and release gates below still apply.

## Decisions and actions still required

| Area | Exact remaining gate |
| --- | --- |
| Chat | Confirm post-free behavior and any paid `CHAT` tariff; selected Free 70/day and 500/month remain separate from Work internals |
| Image | Accept bounded `IMAGE` model/quality/size/input terms and the proposed price, or keep it inactive; reference/edit and the old Medium suggestion are not approved |
| Voice Over | Accept `VOICE` rates/model/character counting, Free-duration proration and output bounds; no clone tariff is invented |
| Translator | Accept `INTERPRETER` separately from `TRANSLATOR`; Gemini 3.8, Gemini 3.5, classic STT/text/TTS and uploaded Dubbing have different economics; approve engine-specific bounds or exclude unapproved engines |
| Receipt | Decide any Free allowance and the price per valid readable receipt; accept physical/readability/output limits and verify actual model access/quality |
| Work | Decide pricing/allocation for `WORK_TEXT`, `WORK_WEB`, `WORK_WATCH`, `WORK_DOCUMENT`, `WORK_CODE` and `WORK_PROJECT`; the current candidate supports one bounded successful logical step, not automatic billing per internal API call |
| Work planning/watch | Decide whether automatic planning is included in a job price or separately priced; `WORK_PLAN` is unimplemented/inactive. Decide whether quiet watch observations are billable, with caps and explicit consent |
| Sandbox/market | Decide a reviewed `WORK_EXECUTION` funding transition that avoids double charging legacy capacity and retains supplier/access guards. `WORK_MARKET` remains unpriced and inactive; no Trading changes were made |
| Speech measurement | Accept or validate the digital-silence meter; it is not proven linguistic VAD. No idle page time is charged |
| Operations | Confirm an identified authorized reviewer can operate manual review; no automatic QRIS/VA settlement is claimed |
| Cutover | Review migration/schema checksums, authoritative cutoff loading, fresh audit, drain/classification, rollback and approved configuration; apply nothing automatically |
| Runtime acceptance | The large/document acceptance gates hash `autonomous_runner.py`. Candidate fingerprints differ from `33c86e61`; a read-only aggregate found one retained document PASS, but zero receipts matching either base or candidate. Core general-execution boundary files are unchanged. Exact-source acceptance/compatibility review is required before release; no proof records, hashes, approval flags or credentials were rewritten and no paid VM was run |
| Release | Obtain the pending specific public PR publication permission, independent review and hosted CI, then use only the normal authorized release path and exact-commit production verification |

## Validation

- 13 new Work path tests pass: text, search/watch, default/selected document authorship, generated code, native project authorship, multi-step preservation, consent/expiry/input/model/account boundaries, no extra Chat quota, interruption, funding denial and deliberately unpriced paths.
- Four Work store tests and four cutoff-loader tests pass on PostgreSQL, including simultaneous admission, one dispatch/settlement, cancellation, restart/unknown holds, active-operation reconciliation denial, rollback settlement, immutable manifests and lifetime-baseline preservation.
- The affected adapter suite passes 19 tests, including an accepted Translator Audio child completing after rollback without consuming legacy Audio seconds. Existing native credit pipeline tests pass 6 cases. Credit route tests pass 9 cases, including issued invoice/private proof access after rollback with new purchasing still disabled.
- Eight browser journeys pass for en/id/es/zh at 393 and 1440 px: non-image Work approval/resume, one synthetic dispatch, issued paused invoices, hidden bank instructions, no horizontal overflow or JavaScript errors. Local screenshots/report: `/tmp/kilas-credit-work-steps-browser`. No screenshots were published.
- The affected existing Work/document/workspace aggregate passes 79 of 80 tests. The lone `test_image_edit_passes_two_original_inputs_without_fallback` failure reproduces unchanged on the exact `33c86e61` base, with the same `selected_image.py` invalid-response path. No image behavior or assertion was changed to hide it.
- Scoped credit/new-test E9/F lint and whitespace checks pass. Six changed-file lint findings reproduce exactly on `33c86e61`; unrelated repository baseline evidence is reused; this is not an all-green hosted CI claim.

Hosted dispatch remains unavailable through the connector, with the existing CLI credential invalid. No replacement credential or alternate write route was attempted. Public PR creation was previously denied for missing specific publication permission and was not retried. No production verification, activation, migration, real financial activity, merge or deployment is claimed.
