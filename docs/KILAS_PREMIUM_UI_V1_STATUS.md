# Kilas Works white customer UI release

Updated 2026-10-03. Implementation and verification in progress; not yet deployed.

- Starting remote/main: `0771f2c1959987bb070814d4c6c5975626301206`.
- Known-good Client Hub deployment / rollback reference: `dep-davu1f142hec73e60nng`.
- Authorized target: `srv-da7ti2psrm7s73dh9i2g`, workspace `tea-da34t2gu01pc73ft7uf0`.
- No Cron, AI Admin, migration, environment or production-data change authorized.
- Prior uncommitted checkpoint docs preserved in named stash
  `preserve-release-checkpoints-before-light-redesign`; restore before final stop.
- Production before screenshots: temporary `kilas-light-before-login-1440.png`
  and `kilas-light-before-login-390.png`. Existing verification browser is at login.
- Scope: templates, scoped customer CSS, navigation-only JS, bundled font/license,
  focused presentation tests, and read-only Connections presentation context.
- OAuth scopes, AI execution/routing, payment approval, pricing, quotas and Finance
  business behavior remain unchanged. Known natural scheduling bug excluded.

## Completed local gates

- 356 focused AI/capability unit checks across 21 modules, plus 5 foundation tests passed.
- Eleven browser journeys passed: autonomous work, chat experience, results/Markdown,
  agent, shared shell, legacy chat, Work, Work V2, unified chat and attachments,
  capability-based composer focus, and the new premium acceptance journey.
- New customer browser checks cover login/signup/forgot/reset, Home, Connections,
  preferences, account/profile dialog, subscription, Finance entry/setup, chat,
  Finance Home/transactions/accounts/invoices/reports at 320/360/390/768/820/1024/1440.
  Actual visible text contrast, white canvas, page overflow and JavaScript errors
  are asserted; synthetic long IDR opening balance is local test data only.
- Screenshot evidence: temporary `kilas-premium-ui-qa` directory and existing
  `kilas-unified-*`, `kilas-work-*`, `kilas-work-v2-*` and result screenshots.
  The CI workflow uploads the new responsive images alongside existing evidence.
- Windows-only SQLite open-file teardown errors affected the unchanged Finance
  baseline and Assist connection test fixtures. Linux CI must verify those tests.
- Rendered Impeccable detector suggestions were distinguished from visible facts:
  unused legacy dark/glow declarations are not rendered; intentional live activity
  feedback preserves reduced-motion support. Actual low-contrast Account and report
  colors were corrected; alpha/sRGB parsing in the contrast check is explicit.
- Finish review initially requested four fixes: remove empty-state eyebrow, page-size
  Connections heading, readable account actions, consistent drawn/removal of optional
  glyph icons. All four applied; same-path recaptures verified: disposition `ship`, all four scored fixes resolved.
  This verdict covers the scored fixes, not a full application audit.
- DESIGN.md and schema-2 design.json extracted and validated; 21 exact palette mappings.
- Diff review: no schema/migration, Finance app/template/form/logic, AI execution,
  routing/model/prompt, OAuth scope, pricing/quota, WhatsApp/Meta, Assist or production
  data change. The sole Python app change reads only Google status/display identity
  for the existing Connections presentation route; execution/approval routes untouched.

## CI baseline limitation

The existing Kilas AI Focused QA PostgreSQL foundation bootstrap fails with missing
`kilas_ai_agent_messages` on starting main 0771f2c (run 37036023072, job 110934324981)
and preceding main 43ea (run 37031294486). Its migration list omits the earlier agent
foundation migration but includes later foreign-key consumers. This is unrelated to
UI changes and must not be repaired by changing application schema/migrations in
this release. Relevant comprehensive Autonomous PostgreSQL sandbox checks remain
mandatory. Preserve the failing check and report its actual outcome transparently.

Final release SHA, CI run results, reviewer verdict and Render deployment evidence
will be recorded after those gates; no production claim is made at this checkpoint.

## First pushed release CI checkpoint

- UI commit `85572ff507eefe1b72e032722e468d4b908832bd`, message
  `Redesign Kilas Works customer UI`, pushed directly to current main.
- Run 37051599884: focused Finance/Assist/AI boundaries and Autonomous PostgreSQL
  /code sandbox passed; responsive browser still running at this checkpoint.
- Run 37051599829: Chat Quality V2 unit/browser passed.
- Run 37051599683: foundation/browser passed; unchanged PostgreSQL bootstrap failure
  reproduced precisely (`kilas_ai_agent_messages` missing).
- Run 37051599646: Automation unit/boundaries/PostgreSQL passed; browser used the
  obsolete exact heading `Work`. Assertion updated to `Pengingat & jadwal`, with
  all creation, preview approval, schedule editing, pause and results checks retained.
- No production deploy yet. Final corrected main must complete relevant CI first.

## Final CI synchronization correction

Automation browser passed on `723f63e` (run 37051955588). Chat Quality browser
occasionally read composer focus after the first response text, before SSE DONE
(run 37051955697, 820px); the identical application code passed the prior run and
local journeys. The focused browser now waits for the real input re-enabled state
before asserting desktop/mobile focus. No delay and no application JS change.
All original focus expectations are preserved. Rerun final main CI after this fix.

The final comprehensive browser run exposed the existing planning-card hydration
race (37052400229): a generic accepted card was visible before its PLANNING label
arrived. The same original `Menyiapkan rencana` assertion now uses Playwright's
retrying text assertion. No backend, polling, timing delay or status change.

## Supporting schedule UI regression check

Run 37052790893 reported a 320px schedule-form overflow immediately after navigation.
Added actual fully-loaded form captures/geometry diagnostics without removing the
assertion. Local inspection also found a leftover secondary dark header and pale
subtitle. Scoped auto-* CSS now provides white/header/border/text colors, readable
state colors, 20px phone gutters and min-width bounds on form children; native date
and time controls use light color-scheme. Task creation/preview/explicit activation,
editing, pause and results remain unchanged. Secondary labels now say schedule/task
rather than suggesting a second Work mode. Schedule list and form join the actual
seven-width contrast/no-overflow acceptance matrix. Supplemental finish review is
limited to these new captures. No production deployment at this checkpoint.

The corrected schedule creation/edit/approval/pause browser and the expanded
seven-width premium contrast/overflow journey both completed exit 0 on the final
presentation. Supplemental review's single optional-plus finding was removed;
final same-path captures show the text-only CTA and human schedule labels.

Supplemental verdict: `ship`; the sole scored fix is resolved and remaining is clear.
