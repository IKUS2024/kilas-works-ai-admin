# Sent AI Chat attachments — 2026-10-20

Based on main b5fe6107454f882af348c964fe169c799842afd5. Preserve initial-render,
selector localization, AI Call and Finance fixes. Scope: user-upload presentation
on ordinary Chat and agent Chat, pending selection and existing private history.

Verified causes:
- Ordinary Chat persisted uploads, but its optimistic Send renderer appended only
  user text. Success then cleared the composer previews without adding attachments
  to the user message. Reload used a separate attachment presentation.
- Agent optimistic/history images shared document cards, exposing numeric/image
  filenames beside thumbnails. Ordinary history also used a different image block.
- Ordinary failed/uncertain upload retries generated a new operation key, allowing
  the same accepted upload to become a new user turn on explicit retry.

Fix:
- Shared image-only galleries and compact document cards for optimistic messages
  and server-rendered history. Image filenames remain absent from visible image
  cards; user-written text is preserved verbatim. Documents retain filename/type,
  existing download links and sandboxed PDF Open links.
- Ordinary Chat displays local previews immediately and reconciles that exact
  operation's gallery with the existing authenticated thread HTML after acceptance.
  This is one read-only GET, never a second upload or inference request. Failure
  to load the projection leaves local previews; reopening reads durable history.
- Retain the operation key for an unchanged uncertain upload retry. Accepted files
  leave the composer, stay in their user message even if the model reply fails,
  and are not queued for accidental resubmission. Rejected sends keep selection
  and caption. Agent attachment inputs/removal lock during an in-flight send.
- Blob ownership is per gallery/selection, with release on replacement/removal.
  Missing images have a generic fallback. Filename rendering uses textContent
  or Jinja escaping. No public file URL, route authorization, model/billing,
  provider, schema or storage-flow changes.
- New CSS/scripts load in head for current Chat pages; standalone fallbacks and
  explicit script cache versions retained. Added existing image/fallback strings
  to the client translation allowlist.

Validation (synthetic files/providers only, zero paid inference):
- test_kilas_sent_attachments.py: 6 PASS. Durable gallery/file history, PDF
  Open/download and CSP, accepted provider failure, owner/foreign-account URLs,
  filename escaping, repeated operation stores once and dispatches zero times
  on repeat; existing agent upload projection also checked.
- test_kilas_chat_attachments.mjs: 4 PASS. Image-only text, hostile filename,
  generic image failure, pending controls and exact Blob cleanup ownership.
- kilas_sent_attachments_browser.py: 6 PASS combinations, ordinary/agent Chat at
  320/820/1440 px. Multiple images plus file, remove-before-send, rejected send,
  uncertain retry uses identical key, Send -> private durable URLs -> reload,
  fresh Home thread creation, exact caption and no overflow/page errors.
  Accepted-upload/provider-error flow additionally checked on desktop ordinary
  Chat. No duplicate durable rows. Read-only foreign account fetch returns404.
- Initial render contracts 3 PASS; model initial render 14 PASS. Existing legacy
  attachment suite 4/6 PASS, with the same two303 onboarding-fixture failures
  reproduced using unchanged baseline templates; no new failure introduced.

Screenshots/report: /tmp/kilas-sent-attachments-browser/. Production browser is
verified by parent because this execution proxy previously blocked production
HTTP. Actual paid model/image semantics are outside these fixture checks.
