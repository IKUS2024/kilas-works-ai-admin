# Kilas AI chat UI cleanup — 2026-10-02

User authorized a focused direct-main production release, starting from main
`43ea1b4654f8d7faa82ea1f3bf42994618b718dc`. The previous uncommitted Unified
release checkpoint is preserved in the named Git stash; it is not part of this patch.

## Implementation

- Remove Active Work and Notifications links/counts from desktop/mobile sidebar.
  Existing task, reminder, notification, runner and control infrastructure remains.
- Single-line history titles with ellipsis, consistent padding and selected/hover states.
- Compact pending image thumbnails and document cards with filename/type/size and
  individually accessible 44 px removal controls. Multiple selection remains additive.
- Render sent attachments inside the original user turn, including during streaming.
  Completion replaces temporary previews with private persisted file URLs.
- Ordinary unified chat did not previously store uploads. A small adapter now writes
  validated uploads atomically with their real Agent message into the existing private
  attachment tables. Empty internal backing messages satisfy existing foreign keys;
  their reserved operation key links the real message. Backing threads are excluded
  from visible legacy history, and never enter Agent context. No migration or fake Job.
- Previously saved image-edit inputs are projected read-only from existing artifacts
  into their original user turn. Files never stored by the former implementation
  cannot be reconstructed; no existing stored data is deleted or rewritten.
- Preserve permanent result anchors, new-chat isolation, downloads, mobile focus,
  streaming, Stop, Markdown, model/prompts, routing and all execution semantics.

## Focused verification

- Attachment persistence/security: 7 tests PASS; durable reload/reopen, later messages,
  original download bytes, cross-owner/conversation denial, hidden storage adapters,
  preserved legacy history, duplicate submission, rollback and existing stored inputs.
- Unified routing/quality: 21 tests PASS. Existing Work V2: 22 tests PASS.
- Existing attachment validation: 6 tests PASS. Final browser confirmation PASS.
- Unified browser acceptance A–I PASS at 320/360/390/820/1440 px: previews, individual
  removal, additive images, PDF, send/download, reload/reopen, new-chat/history,
  original result anchors, removed navigation, compact titles and no overflow.
- Existing Work and Work V2 browser journeys PASS at all five widths, preserving
  control/progress, Office/PDF output, reminders and coarse-pointer focus behavior.
- Scoped Impeccable detector: Jinja-linked stylesheet is unresolved by static detection;
  its existing flat-type warning assumes all roles are 16 px. Rendered browser evidence
  is authoritative. No full audit or unrelated typography rewrite.
- Native PostgreSQL CI additionally exercises the upload adapter and BYTEA roundtrip.

## Release checkpoint

Pending direct-main commit/push, relevant CI, Client Hub-only
deployment and actual authenticated production acceptance. Do not deploy AI Admin or
Cron, run migrations, reset data, or change credentials/configuration for this patch.
The dedicated controlled QA browser is open at login; authenticated live acceptance
must not be claimed until the user signs in and the production journey is performed.
