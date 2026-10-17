# Chat headers, sidebar actions and meaningful history — 2026-10-17

Removed the redundant main-pane New chat/title/ellipsis row and Kilas AI heading above the model selectors. Site Kilas Works branding, the sidebar’s functional New chat creation control, saved conversation titles, centered model controls, provider icons and selection persistence remain. Removed the collapsed image cost estimate widget from the normal composer/page; internal model rates, metering, routing and caps were not changed.

## Sidebar actions

Owned conversation rows expose exactly Rename and Delete through touch/pen long press (550ms), desktop right click, Shift+F10 or the keyboard context-menu key. Moving more than 10px, scrolling or pointer cancellation cancels the hold. Suppressed synthetic clicks cannot navigate after a hold; ordinary taps remain native links. Menus use the top layer, keep keyboard focus/escape behavior, and work for recent and paginated rows. Labels, validation errors and confirmation text follow the app’s Indonesian/English/Spanish/Chinese locale without translating saved customer titles.

Rename and legacy Delete reuse their existing authenticated, owner-scoped, CSRF-protected POST routes, with JSON responses for in-place actions. Renaming and deleting another chat retain the current draft and model selection. Both Delete actions require a separate explicit confirmation. Legacy deletion retains its existing permanent-delete behavior and warning. Modern conversations previously had no Delete route; the new owner-scoped route sets the existing archived_at field, retaining messages, jobs and artifacts and clearing the active chat session only when that conversation is removed. No schema migration, job cancellation or production conversation deletion was performed.

## Meaningful history

New and existing empty placeholder records are hidden rather than deleted. A conversation appears after a submitted message, a submitted attachment with a persisted message association, or a real work job/artifact. Internal attachment-backing threads remain hidden. Recent and paginated sidebar lists share one owner-scoped projection ordered across legacy/modern chats by latest meaningful activity descending, with stable kind/ID tie breaks and signed owner-bound keyset cursors. Work creation, recorded work events/results and artifact creation count; opening, renaming, changing a model and lease heartbeats do not. Message acceptance and existing work refreshes update the sidebar. Existing History views use the same meaningful records.

## Empty viewport

The empty modern welcome panel retained 63px top and 24px bottom margins in the measured mobile case, extending beyond its flexible message container. The scoped empty-state layout now resets those margins/padding and permits the welcome image to shrink within the available height. Empty welcomes have no scroll range; populated timelines retain independent scrolling. Existing visualViewport/keyboard/safe-area handling remains, and no global touch or zoom suppression was added. Sidebar and model dialogs retain independent scroll ownership.

## Validation

- 46 targeted Python tests passed: new history/action lifecycle and owner/CSRF tests, signed pagination, Home/localization, model preferences and selected artifact regressions. Empty creation/draft/model changes stay hidden; first send, submitted attachment and work-only history appear; lease/rename/open do not bump order; latest submitted activity does. Synthetic modern archive retains messages/jobs; synthetic legacy deletion exercises its existing behavior; foreign and missing-CSRF actions fail.
- Five existing viewport-controller tests passed, including visual viewport offset, Android-style layout resize, fallback sizing and retained transcript reading position.
- Twelve real Chromium cases passed at 320/820/1440 pixels: Home, empty modern/legacy chats and sidebar interaction on each width. Verified no empty vertical or document/horizontal scroll, composer/Call launch visibility, 360px-height keyboard geometry simulation on mobile, populated transcript scrolling, real touch holds and movement cancellation, right click, keyboard/escape/focus, Rename preserving drafts, explicit Delete confirmation/cancel and synthetic deletion, normal touch navigation, and paginated-row menus. Desktop/mobile screenshots were reviewed once after the final pass.
- Native history SQL ran successfully in production PostgreSQL through a read-only query scoped to synthetic owner -1 and returned no rows. No user records were read or mutated by that validation.
- JavaScript syntax and diff checks passed. No paid inference, microphone/media access, credentials, billing, subscription/quota changes, Finance, Group, Translator, Voice Over or Creative Services implementation changes.

Limit: mobile touch/keyboard geometry was verified in Chromium fixtures, not a physical Android IME session. Older pre-release pagination cursors use a different history order and are invalidated; refreshing the page starts the current signed pagination.

## Production parameter-binding correction

Authenticated browser checks after deployment found `/products/start` and saved chat pages returning 500. Production tracebacks identify `sidebar_history.recent` calling `db.query_all`, then psycopg2 `cursor.execute`, raising `IndexError: tuple index out of range`. The new history SQL embedded the literal wildcard `LIKE 'agent-attachments:%'` alongside bound parameters. PostgreSQL's driver treats that unescaped percent as parameter syntax. Both wildcard patterns now travel as bound values; shared database adaptation is unchanged.

The earlier read-only PostgreSQL check interpolated values before execution and therefore did not exercise the production binding boundary. SQLite and browser fixtures also missed this driver-specific failure. A regression now executes all six history filter combinations through the PostgreSQL branch of the actual database adapter with a cursor enforcing percent-placeholder binding, including pagination parameters. All 15 focused history/action tests pass. This is an adapter-contract regression with a synthetic cursor, not a live psycopg2 or authenticated production browser check; browser acceptance remains required after deployment.
