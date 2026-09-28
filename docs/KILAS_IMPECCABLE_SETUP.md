# Impeccable in Kilas

Installed project-locally for Codex at `.agents/skills/impeccable` from the official `pbakaus/impeccable` compiled distribution, pinned to commit `9d715cc4f5564a990ca8345abfdd5df6dc9b41c8`. Skill frontmatter version 4.4.0; engine pin 0.1.6. License and upstream notice retained. File SHA-256 values are recorded in `.impeccable/install-manifest.json`.

The official `npx impeccable@4.1.0 install --providers=codex --scope=project` attempt failed resolving the bundle host and installed nothing. Manual copying from the successfully fetched official GitHub source completed the skill installation. The matching engine was obtained from the official npm platform package `@impeccable/cli-linux-x64@0.1.6` with install scripts disabled and cached outside this repo; `engine-probe` verified 0.1.6. An initial npm-shim engine was 0.1.5; final detector evidence was rerun with 0.1.6. No app package/dependency/build file was changed.

## Configuration
- `PRODUCT.md`: existing Kilas purpose, users, journeys, current constraints and source precedence. Explicitly keeps Finance protected and records latest checkout / continuous-training / CRM behavior.
- `AGENTS.md`: scoped audit-only workflow, current checkpoint reference and Finance/shared-style boundaries.
- `.impeccable/config.json`: automatic hook disabled for the audit-only phase; Finance-named files excluded by the user's scope. No Assist defect is suppressed.
- `.codex/hooks.json`: official native hook definition adjusted only to point to the actual `.agents/skills/impeccable` launcher. It is configured but NOT active/trusted in this session. Future enabling must use the harness's normal hook approval; never bypass it.
- No global/personal skill installation, live-edit browser integration, CSP change, visual replacement, buildPath preference, DESIGN.md or design-token sidecar was created. Existing CSS remains authority.

## Use
From a checkout containing this branch, ask Codex:

```text
$impeccable audit Kilas Assist only. Read PRODUCT.md and AGENTS.md.
Do not fix findings or touch Kilas Finance.
```

The launcher runs the pinned engine from its cache or downloads it on first use. A fresh machine needs ordinary access to the official engine distribution. No runtime library is loaded by the Kilas application.

```sh
.agents/skills/impeccable/scripts/impeccable engine-probe
.agents/skills/impeccable/scripts/impeccable hooks status
.agents/skills/impeccable/scripts/impeccable detect --json \
  client-hub/templates/assist_training.html \
  client-hub/templates/customers.html \
  client-hub/templates/customer_detail.html \
  client-hub/templates/jobs.html \
  client-hub/templates/inbox.html \
  client-hub/templates/_client_compact_style.html \
  client-hub/templates/_contact_context.html
```

Detector exit 2 means findings, not execution failure. Initial findings are deliberately left unfixed. Do not scan/fix the whole repo. Read shared styles only for Assist context; automatic ignores cannot isolate individual Finance selectors inside a shared file.

## Evidence
- `docs/KILAS_ASSIST_UI_AUDIT.md`: prioritized source/live findings and explicit verification limitations.
- `docs/qa/kilas-impeccable-detector.json`: seven raw detector warnings, with portable repo-relative file paths.
- Final checks: pinned engine probe, disabled hook status, JSON parsing, vendor checksums, command references, first-party diff whitespace and zero existing application/Finance changes. Upstream vendored references retain six whitespace warnings unchanged so vendor checksums remain exact.
- No application tests needed for this tooling/documentation-only diff; no claim that the full regression suite was rerun.
- Work remains on `chore/impeccable-assist-audit-20260928`; no merge or deployment is part of this task.

## Updating later
Review upstream changes and preserve project context/constraints. Use the official installer or repeat a pinned manual copy; update this manifest and licensing alongside it. Never enable automatic hooks, invoke design fixes or change production as a side effect of an update.
