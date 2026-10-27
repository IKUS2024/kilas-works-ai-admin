# Copilot CI regression triage — 2026-10-27

Baseline: production/main `1a529a13ba83cff1341add371af3b5632d52cb27`.
Prior PR #169 head `b764df2fee1d0a770b810514f3c92998f99434a8` has
the identical Git tree `b71181a79c24d2ddf5bc83c45e54eada870fb601`.
Thus its PR-only workflow evidence is also evidence for the unchanged baseline.
Candidate failures below were inspected at `8023b83c` and `518a9223`.
No check, assertion or required protection was disabled to publish this change.

| Workflow | Diagnosis and baseline evidence (Actions run IDs) |
| --- | --- |
| Conversation Copilot | New contracts, metering, responsive synthetic microphone/browser and synchronous-worker disconnect test pass: 40559359815. No paid calls. |
| Finance Onboarding / Client Session | Pass: 40559359482 / 40559359874. |
| Six reference UI | Introduced old-shell fixture mismatch. Historical Chat/Call reference fixtures now explicitly use reversible legacy mode. Assertions retained; current Copilot is tested separately with primary mode ON. Baseline 40480575468 passed. Must pass again after fix. |
| HD Image and Document | Introduced old-primary-page expectations in AgentChatExperience. Scoped legacy fixture retains its 44 assertions/tests and functionality; local 44 pass. Baseline 40480575675 passed. Must pass again after fix. |
| Chat Quality | Same baseline browser old heading, Unlimited AI Chat offer and WebKit flex expectation; 40480575328 (WebKit job 122109551117) and main 40480985186. No Chat engine changes. |
| Autonomous | Same missing PostgreSQL conversations table, sandbox user_id fixture, stale browser auth and offer failures: main 40480985191. The additional AgentChatExperience mismatch is fixed as above. |
| AI Automation | Same stale auth, missing conversations table, English-vs-Indonesian activation label and browser fixture: main 40480985229. |
| Chat Recovery | Same workspace_runtime image-edit fixture error: main 40480985396. |
| Global UI | Same Home 4 failures and combined Finance 10 failures/2 errors: main 40480985176. |
| Phase 6 | Baseline and candidate freshly rerun in isolated offline harness: identical core_simulator 9 failures/1 error, stale auth 401 versus expected route responses. |
| Phase 8 | Baseline and candidate freshly rerun: identical whatsapp 3 failures/2 errors, stale auth 401/303. Prior baseline PR run 40480575370. |
| Phase 9 | Baseline and candidate freshly rerun: identical workspace 3 failures, obsolete Finance navigation/home assertions. Baseline 40480575307. |
| Phase 10 | Baseline and candidate freshly rerun: subscription_lifecycle same line 602 dashboard status assertion. Baseline 40480575376/job 122109550401; migration rehearsal passes. |
| Phase 7 | Existing Finance bridge/runtime assertions already fail at baseline 40480575423/job 122109551636. Isolated Finance baseline is a long-running job; do not claim the whole workflow green. Finance implementation is unchanged. |
| Master Completion | Baseline and candidate freshly rerun: identical one Assist language correction failure (None vs forced en). Baseline 40480575167. |
| Trading | Baseline and candidate freshly rerun: identical Trading 7 failures, Bridge 26 failures/7 errors from stale auth/pairing fixtures. Old login browser fixture and PostgreSQL use the same unauthenticated state. No Trading implementation changes. |

Fresh comparisons use the same installed dependencies and `scripts/run_offline_tests.py`
in separate baseline/candidate trees, network blocked by the harness. Logs are
`/tmp/copilot-triage-{baseline,candidate}-test_*.log` and summary
`/tmp/kilas-copilot-triage.json`. These are genuine failures, not claimed passes.

The default-primary browser suite additionally guards Voice Over unsaved drafts:
dismiss its existing leave confirmation and verify the script and route remain.
The new navigation must opt into that existing guard, rather than bypass it.

Production provider availability is checked read-only. Previous production
startup already reported ElevenLabs configured/ready and Gemini enabled with
zero remaining budget. Synthetic screenshot accounts are deliberately unfunded;
their unavailable-provider labels do not represent a production configuration
change. No provider flags, budget, subscription, credentials or engine behavior
are reconfigured. Real audio/paid-provider tests remain NOT RUN.
