# Receipt photo preview and pending-photo removal — 2026-10-18

Baseline main/LIVE7e19677a8b7f0c1ea9a8750f9d1ae66d6b2e2345. Receipt work was paused with its edits intact, then explicitly resumed. Permanent category deletion remains canceled. No production financial save/delete, paid OCR/API/model/VM call, migration, credential or infrastructure change is part of this release.

## Delivered behavior

The shared Personal/Business Add/Edit Expense form now displays the actual selected photo inside the existing left receipt tile. Its position, category/split placement, field order and dimensions are retained. A separate type=button × removes only the pending file, filename and local preview; it neither opens the file picker nor submits/resets other fields. The same file can be selected again. On Edit, removal of a pending replacement leaves the original saved receipt association and existing private View receipt link intact; it is not a receipt-delete feature.

The previous handler only showed a filename. This update uses a blob/object URL, not a full-file base64 copy. It checks a bounded12-byte header for the existing JPG/PNG/WebP extension contract, then requires real browser image decoding. Existing limits and authoritative server validation remain unchanged; PDF/SVG are not newly accepted. The preview has a20MiB input guard and the server's80-million-pixel ceiling; the pre-existing generic page upload validation still applies, so this release does not increase upload capacity.

Each selection has a generation token. Removed/replaced files and late header/image callbacks cannot restore their image. Replacement, ×, modal close/cancel, form reset and pagehide revoke the object URL and detach pending handlers. Clear also resets stale file validity. During a submitted form the × is disabled; it does not pretend to cancel an already-sent financial request. Save/idempotency/CSRF/ownership and receipt persistence are unchanged.

Manual selection/preview makes no HTTP/scanner/provider request. Paid Business receipt scanning is a separate existing form and adapter, untouched here. New clear labels/error copy follow the existing four UI languages. Asset versions are updated in the three Expense template entry points so refreshed pages load the matching markup/JS/CSS.

## Verified evidence

- **16 focused Python contracts PASS:**3 new receipt-preview/preservation contracts,9 existing expense/receipt/split contracts and4 hide-only legacy-choice contracts. They cover four-language Add/Edit markup, original receipt bytes/hash/private ownership after saving with no replacement, PDF rejection, existing accounting/idempotency and canceled-deletion/historical category compatibility.
- **12 actual local Chromium combinations PASS:**Personal/Business Add at320/390/768/1440 and Edit at390/1440. Native JPEG/PNG/WebP previews decoded at their expected dimensions. Select/replace/×/same-file reselect/cancel/reopen preserve all other fields; touch, Enter and Space × open no chooser and submit nothing. Existing receipts remain byte-identical in both scopes.
- Delayed real12-byte reads and deferred image callback delivery simulate adverse timing: removed/old completions cannot revive a preview. All created URLs are revoked on tested cleanup paths. An actual synthetic local Save after clearing a selected file stores no receipt. No paid OCR request was made.
- Mobile screenshot review found a generic button minimum stretching ×; a scoped override fixes its circular dimensions. **6 overlapping browser combinations** passed after this CSS correction; these are a subset rerun, not18 distinct combinations.
- JS syntax, locale JSON parsing and git diff whitespace checks passed. The resumed workspace matched the saved9 modified files+2 tests and unchanged remote main; completed tests were reused without unnecessary broad reruns.
- Local logs: `/tmp/kilas-finance-receipt-preview-core.log`, `/tmp/kilas-finance-receipt-preview-browser.log`, `/tmp/kilas-finance-receipt-preview-style.log`. Harness: `client-hub/tests/finance_receipt_preview_browser.py`. Screenshots: `/tmp/kilas-finance-receipt-preview/add-business-320.png`, `edit-personal-1440.png` and the other scoped combinations.
- No authenticated production browser, physical Android/iOS camera, live scanner extraction or production financial write was tested. Screenshots inspected are synthetic local browser captures; the optional owner Library reference was not independently viewed for this receipt task.

Changed runtime scope is the shared Expense partial/JS/CSS, its three asset entry points and scoped locale keys. No Finance backend/accounting, Translator/Voice, sandbox configuration/proof/budget or cleanup script was changed. Follow-on Finance alignment work starts only after this receipt release is LIVE and reported separately. Exact release/startup/read-only preservation evidence: `/tmp/kilas-finance-receipt-preview-live.json`.
