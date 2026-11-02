# Kilas AI managed model and sponsored testing rollout

This is an independently reversible Chat offering, not an extension of the old dated all-app trial. It does not change Translator/Voice Over funding, Finance, Creative Services, account roles, customer wallets or previously stored model preferences.

## Configuration (all default OFF)

| Server flag | Enabled behavior |
| --- | --- |
| `KILAS_AI_MANAGED_MODELS_ENABLED` | New Chat turns use exact `gpt-6-luna`; new generation/edit uses exact `gpt-image-2.5-sunburst`. Normal picker replaced by Kilas AI label. No automatic model/provider fallback. |
| `KILAS_AI_CHAT_FREE_TEST_ENABLED` | Existing authenticated accounts may use interactive owned Chat/search/document authoring without subscription/customer credit debit; explicit request provenance is required. |
| `KILAS_AI_IMAGE_FREE_TEST_ENABLED` | Existing authenticated accounts may generate/edit images requested interactively without subscription/customer credit debit; explicit request provenance is required. |

No trial end date or new application dollar cap is inferred. Existing server rate, concurrent-request, technical upload/resource, operation idempotency, ownership, CSRF and execution/connector permission checks remain. This does not grant external actions, remote VM execution, audio or video funding. Technical upload bounds remain 8 MiB/photo, 2 MiB/document and 10 MiB total/message; larger document support is not implied.

Previously accepted jobs retain their explicit author/image model. Model preference rows remain intact for rollback. Disabling flags restores normal commercial policy for new operations; previously sponsored usage remains excluded from customer capacity after rollback.

Migration `0113_kilas_chat_sponsorship` adds `kilas_ai_usage.customer_charge_exempt` (default0 for historical records), `customer_charge_origin`, and a private `kilas_ai_interactive_job_origins` sidecar table. Trusted Chat handlers mint origin values after ownership checks; client dictionaries/flags are not accepted. Immediate artifact creation registers a durable owner-scoped ONE_SHOT grant outside model prompts. Scheduled/recurring/watch and generic autonomous jobs receive no grant, even if they have an owned conversation. Category CHAT/WEB alone is never sufficient. Scheduled jobs retain stored model choices and ordinary commercial billing. Workers consume accepted immediate-operation grants with their global free flags OFF; disabling new grants never retroactively charges an accepted artifact operation. The exemption is persisted at reservation and respected at settlement even if flags change in flight. Actual provider costs/tokens and conservative unknown-cost estimates remain visible to operational accounting. Customer top-up reserve/settle is skipped for sponsored operations. No wallet/ledger/history is deleted. Admission is endpoint scoped, not a role or global QA override.

## Provider compatibility and quality

Official model references: [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), [image guide](https://developers.openai.com/api/docs/guides/image-generation), [edits reference](https://developers.openai.com/api/reference/python/resources/images/methods/edit).

Existing read-only Models API readiness logs on Hub at 2026-11-02 15:47 UTC reported both exact IDs `verified`. That proves access at that snapshot, not paid inference quality or perpetual availability. Recheck before activation. Chat retains adaptive depth/output budget, context checkpoints, file/image understanding, search and native tool/document workflows. Selected-model quality repair stays on the same model. No claim of identical intelligence across models is made.

Sunburst uses native generation/edit endpoints with default high quality / 2048x2048 (the existing options resolver can adapt aspect ratio/resolution from the prompt). Original compatible reference bytes are preserved. No undocumented Sunburst input-fidelity parameter is invented, no resize of generated output and no fallback to Mini. High quality still requires live evaluation of text legibility, prompt adherence and edit fidelity.

Explicit provider quota/billing rejection gets a safe recovery message and no retry. Confirmed rejected requests without prior billed stages record zero; already billed retrieval stages remain accounted. Interrupted/ambiguous network results retain conservative cost observability. Images/documents waiting on exhausted provider balance do not automatically loop.

## Activation hold: billing boundary not verified

Do not enable public sponsorship or run paid acceptance until the existing OpenAI project/organization billing arrangement is confirmed compatible with the owner's existing-balance-only instruction. No provider payment setting, key or subscription may be created/changed to resolve this implicitly. Existing prepaid credit is not proof auto-recharge is off or PAYG cannot continue. [OpenAI prepaid billing guidance](https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing) also warns cutoff can be delayed, creating a negative credit balance. Kilas cannot promise an instantaneous zero-balance cutoff from these flags.

The owner/parent is checking this setting. Pending, not denied. All flags remain inactive in production. No paid API calls have been made for this change. No changes to the separately suspended old `kilas-works-ai-admin` WhatsApp service are part of this release.

## Release / verification

1. Finish exact-head mocked regression, browser and disposable PostgreSQL checks. Inspect screenshots; no real customer accounts/files in QA artifacts.
2. Resolve the billing gate and reconfirm existing exact model access. Keep production credentials in place, never copy them into artifacts/executor.
3. Normal draft PR → ready → merge. No formal self-approval or protection bypass.
4. After parent approves coordination, deploy existing Client Hub `srv-da7ti2psrm7s73dh9i2g` with flags OFF first to apply0113; then deploy existing cron `crn-dau073vlk1mc73d6ilc0` at the SAME final merge SHA with all three new flags OFF. Cron consumes only persisted interactive-job grants; its scheduled workloads retain billing/model behavior. Let old invocations finish naturally before activating the three Hub flags after billing approval. Preserve cron schedule/plan/credentials and existing runner gates. Environment updates may trigger a deploy even with autodeploy off; observe uncertain outcomes before triggering another. Do not resume/deploy old ai-admin. Static fallback needs no deployment for an AI-only change.
5. Verify exact active commit, additive migration/startup, health, authenticated admission and UI. Then perform only the separately permitted small live acceptance: context correction, grounded search/file reading, one generation and one edit as needed. Record billable usage, never secret balance/credential values. Stop on quota rejection; no speculative retry batch.
6. Roll back new admission by turning Hub flags OFF, retaining exemption-aware code on BOTH services and all provenance/ledger/history. Already accepted immediate job grants remain free to the customer until that ONE_SHOT operation completes; they are not new scheduled grants. Never roll back to a binary that ignores exemptions after sponsored rows exist. Never drop0113 or erase user data to roll back.

Local test reports and screenshots are mocked quality contracts; they are not real-model acceptance or proof every account/provider workflow has been exercised in production.
