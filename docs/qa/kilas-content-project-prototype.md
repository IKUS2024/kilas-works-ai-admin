# Local content project prototype — 2026-10-10

Base main: `810c8419740ec4c2d8de45f145e2d14137078142`.
Status: local prototype complete, default-off, not deployed.

## Scope and behavior

- `/kilas-ai/content-projects` creates an owner-scoped content project with brief.
- One active script with immutable revisions; manual text or an explicit snapshot of an owner-owned Video Plan voice-over. Snapshot stores source plan ID/version. Later edits/deletion of the plan do not overwrite saved scripts.
- Explicit links to owner-owned conversation, legacy thread, ready Video Plan or completed audio job. Multiple language results can be linked to each script version. Association is user-declared, not proof audio matches the script.
- Project/immutable script IDs prefill the existing AI, Video Plan and Translator/VoiceOver forms. Script text is not placed in URL parameters. No handoff starts generation. Completed results are manually linked from the project.
- Link UI lists up to 50 recent eligible items per kind; project listing up to 50; linked results up to 100. Existing module history remains unchanged.
- Honest labels distinguish storyboard/prompt packages, MP3 audio and MP4 dubbing. Visual production/assembly remains external. No new video rendering/export engine.
- Fixed literal script markup inside the Translator title; retained the existing script include in the content block. Voice-provider labels and historical zero charged seconds remain unchanged.

## Disabled-by-default and schema boundary

`KILAS_CONTENT_PROJECTS_ENABLED` is absent/false by default. It is additional to the existing Kilas AI flag; agent chat uses the existing Automation flag, with a legacy chat handoff fallback when that flag is disabled.

`content_schema_sqlite.sql` is additive and is NOT included in db.MIGRATIONS or application startup. `content_schema.apply_disposable_sqlite(disposable_root)` refuses non-SQLite and any DB path outside an explicitly supplied disposable directory under `/tmp`. Only disposable test databases were initialized. No Postgres release/migration is prepared or applied. Enabling this prototype without explicitly initializing its local schema is not supported.

## Verification

Command used:

```sh
PYTHONDONTWRITEBYTECODE=1 KILAS_CONTENT_BROWSER_QA_DIR=/tmp/kilas-content-qa /tmp/kilas-content-venv/bin/pytest -q -p no:cacheprovider client-hub/tests/test_content_projects_prototype.py
```

Result: **18 passed in 4.17s**.

Coverage: feature default-off, unchanged-app CSRF hook, ownership of projects and every link kind, admin/anonymous gates, create/script/link retries, changed-payload conflicts, optimistic script version conflicts, Video Plan provenance snapshots, old-version handoffs after editing, missing/deleted sources, multiple language outputs, honest labels, HTML escaping, actual Video/Translator form prefill, actual Agent/legacy view handoff (mocked rendering for chat), synthetic result downloads, relogin persistence, flag rollback, incomplete-output rejection and disposable schema guard.

All `requests.Session.request` transport and paid provider submit/generate functions are replaced with fail-on-call mocks. Input fixtures, users and media bytes are synthetic. Existing content schema definitions and fixture media are checked unchanged after each test.

Chromium browser flow: create project, save script, manually link MP3 output, open VoiceOver draft, verify correct script/mode, return to project. Desktop 1440px and mobile 390px had no horizontal overflow. Screenshots: `/workspace/kilas-content-project-qa/desktop.png` and `/workspace/kilas-content-project-qa/mobile.png`.

Browser harness uses the real content/Video/Translator templates/routes with a simplified base shell and mocked balance/voice availability. It verifies functional local flow; it does not certify the full production shell or media quality. MP3/MP4 fixtures are format markers, not playback samples.

Python AST parse and `git diff --check`: PASS. Full application startup, full repository regression suite and Postgres were deliberately not run; production behavior and provider output are not tested.

## Preserved boundaries and rollback

No Finance or Trading files, data or behavior changed. No auth/session/CSRF policy, pricing/billing or provider configuration changes. The only shared app edits register the content route module and a content flag template helper; shared base templates/styles remain unchanged. No push, deployment, production migration, paid job, external send or broker call.

Rollback: leave/remove the content feature flag (default off). Existing product routes continue working and added project metadata is retained. Reverting the local patch removes the additional UI and routes; no destructive schema rollback is required.

Before any production release: separate authorization and review are required for Postgres migration, full-shell integration verification and deployment. Authentication lifetime changes remain excluded.
