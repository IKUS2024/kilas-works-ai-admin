# Global navigation, Finance presentation and four-language UI

## In progress — 2026-10-03

- User's latest brief explicitly authorizes Finance presentation and global localization. Accounting, auth, billing, product data and AI/Video planning behavior remain protected.
- Baseline: remote main `95de017868c12d2ef4b962c5e194c52c8fbd2d92`. Branch: `feature/kilas-global-language-finance-polish-20261003`.
- Existing unrelated dirty checkpoint documents are preserved and excluded from this release.
- Explicit UI translation calls and a local reviewed catalog cover Indonesian (default), English, Spanish and Simplified Chinese. A CSRF-protected preference form stores an allowlisted language cookie. User text and generated AI/Video content do not pass through localization.
- Finance brands and return links lead to `/products/start`; legacy workspace return destinations are removed from the touched navigation. Existing financial routes and submitted enum values remain authoritative.
- Finance white presentation is refined through the existing opt-in CSS. Finance AI Assistant promotional navigation is hidden; its architecture and existing data remain intact. Billing gates are not changed or bypassed.
- Optional inventory is skipped to keep this release focused and avoid accounting/schema scope.
- A proposed external translation draft export was rejected by automatic approval review. No export occurred; translations were prepared locally instead.
- Initial checks: all template syntax parsed; Video focused suite 37 PASS; localization and unified AI suite 26 PASS after bounding browser catalog payload. Windows Finance fixtures require closing test-only SQLite handles before resetting temporary databases; no production reset is involved.
- Remaining: finish dynamic copy, run focused Finance and multi-language browser QA, bounded Impeccable review, review full diff, release checks, deploy Client Hub only, authenticated production verification and final checkpoint.
- Production remains on the prior Video V2 release; this patch has not been deployed.

## Release candidate ? 2026-10-03

- Reviewed catalog: 1,517 static UI messages in en/es/zh; Indonesian source is the default. Browser payload contains only 61 explicitly referenced client messages. No runtime translation service.
- Local browser matrix: 544 page checks PASS across 4 languages and widths 320/360/390/430/768/820/1024/1440, no document overflow or JS exceptions. After the independent review, 288 scoped auth/Finance confirmation checks PASS at the same languages/widths.
- Independent Impeccable reviewer: initial FIX (account header wrapping, month/count localization, duplicated brand eyebrows, design documentation). One correction batch; verdict SHIP covers all four scored fixes. DESIGN.md and design.json synchronized by the required documenter. No new raster assets.
- 65 localization/unified AI/Video unit checks PASS. Unified Chat browser journeys PASS at 320/360/390/820/1440, including attachments/removal, persisted files/reopen, generated documents, history and composer focus.
- Focused Finance suites PASS: invoice editor18, phase2a25, phase1a18, phase1b16, UI integrity10, workspace corrections12, baseline4. Dashboard/style48 checks initially exposed two obsolete navigation assertions and a calendar-dependent September report fixture; targeted correction11 checks PASS. Existing financial totals, invoice payments, tenant restrictions and migration replay behaviors remain intact. Linux CI will rerun the complete focused dashboard/style suites.
- Full source diff and whitespace checks reviewed. No financial/backend inference changes, schema migration, account/pricing/billing changes or production data reset. New backend code is limited to the UI language preference/helper plus its app registration.
- Scoped detector advisories checked against actual rendered UI; Jinja/context and legacy design-resolution suggestions were not treated as verified defects. No full audit or automatic fixes.
- Next: push candidate, required CI, merge current main, deploy only Client Hub, authenticated production language/navigation/Finance verification and post-QA logs.
