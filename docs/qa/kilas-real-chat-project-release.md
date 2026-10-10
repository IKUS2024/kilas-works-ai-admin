# Real inline project controls, after the serialized Trading release

## Result

The existing Kilas AI conversation now has real project controls under `KILAS_CONTENT_PROJECTS_ENABLED`, independently of the synthetic chat/listening flags. An owner can choose/create a project, persist the conversation link, review/edit a script, save an immutable revision, reopen prior revisions, download an exact TXT snapshot and open the existing VoiceOver draft for that snapshot. General chat retains its original composer and dispatch. Saving project data preserves the draft message in that composer. Copying a chat answer into the reviewed script is explicit; no answer is automatically promoted or sent to a provider.

The synthetic panel no longer contains its own project selector. Mock audio/transcript actions remain under `KILAS_CHAT_CONTENT_DEMO_ENABLED`; listening remains under `KILAS_LISTENING_DEMO_ENABLED`. With both off, the real panel renders no mock audio, STT, translation, TTS or capture controls and does not read/create synthetic recording/transcript/action rows.

## Configuration proposal and audience

Only after the coordinated release and activation approval, merge these three environment keys without replacing other environment variables:

```text
KILAS_CONTENT_PROJECTS_ENABLED=true
KILAS_CHAT_CONTENT_DEMO_ENABLED=false
KILAS_LISTENING_DEMO_ENABLED=false
```

This serves **all existing CLIENT_OWNER users with Kilas AI access**, not an owner-only preview. Inline controls require the already-existing Automation/chat gate; do not change AI/Automation/auth flags to manufacture access. Existing subscription/provider checks remain authoritative when a user explicitly generates through the old Video/Translator forms. Opening the draft does not submit a generation. Video Plan still provides storyboard/prompts; it does not render MP4. Video/AI handoffs use the project's brief; VoiceOver uses the exact selected script revision.

Current Render flag values are not verified: available connector tools expose environment updates but no read-only getter. The code defaults remain off. Code deployment and activation are separate operations, and no activation should be inferred from this report.

## Data and rollback

No schema/checksum changes from `aa06a7e`. The checksum-guarded SQLite/PostgreSQL migration previously tested and released remains in use. It runs at startup when either content/chat flag is enabled. It creates only additive content/chat tables, including empty synthetic tables; it never enables synthetic routes. The real selector reuses `kilas_chat_demo_projects` solely as the historical owner/conversation/project metadata binding. New real operations do not create synthetic artifacts or provider jobs.

Project creation, active-binding change and conversation link commit atomically. Selection uses compare-and-swap and exact retries; a stale tab cannot restore an older selection, and a conflicting create rolls back the newly inserted project. Script saves lock the current binding on PostgreSQL, check human review, use version CAS and reuse exact operation-key retries. Revisions and prior project links remain intact when selecting another project.

Rollback: set `KILAS_CONTENT_PROJECTS_ENABLED=false`, leave both mock/listening flags false, and restart/redeploy the same service. Keep the tables/data/checksum marker. No deletion, billing/auth change or provider credential change is needed. Restoring the flag restores saved bindings and revisions. No production migration execution is claimed until activation/startup is verified.

## QA

- 54 combined HTTP/browser/PostgreSQL tests passed on the integrated main basis `690bf1d` (13 real-project cases, including parameterized validation and desktop/mobile browser; 6 PostgreSQL cases; existing project/chat/listening regressions).
- 13 legacy suites / 295 tests passed, with sockets blocked and provider credentials removed in test subprocesses. Covers AI foundation/chat/attachments/tools/agent/chat experience, Video/v2/parts/storyboard/recovery, audio and personal voice.
- Chromium desktop 1440px/mobile 390px verified no horizontal overflow, explicit project creation with double-submit suppression, retained general-chat composer text, reviewed v1/v2 saves, reload of v1, exact TXT download and actual Translator draft population. External requests and real media APIs were hard blocked. Some surrounding services are synthetic fixtures; production authenticated UI is not claimed tested.
- Disposable PostgreSQL 18 verified real create/link/save without synthetic artifacts, ownership, migration checksum/idempotency, rollback on stale selection and four concurrent retries producing one project/link/revision.
- SQL/helper byte comparison confirms all five migration/helper files unchanged from the live `aa06a7e` release. No new DDL is required.

Screenshots: `/tmp/kilas-real-project-qa/desktop.png`, `/tmp/kilas-real-project-qa/mobile.png`; CI includes the new tests and uploads screenshots. The prior report documents the earlier deployed prototype phase.

## Scope

Trading main `690bf1d` is retained as the release parent, with no Trading edits. Finance, auth/session/CSRF, billing/pricing, credentials and provider configuration remain unchanged. No paid inference, capture, external send, STT or broker call was performed. Live STT remains unimplemented/unbudgeted and is not needed for this minimum real project workflow.
