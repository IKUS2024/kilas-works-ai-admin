# Remember last selection and center Chat controls — 2026-10-17

Home had no conversation ID, so its picker skipped the save endpoint and only updated JavaScript memory. Reopening fetched the catalog default again; reload also restored Sol. Existing per-conversation storage did not cover an unsent new chat.

Explicit Chat and image selections now save an authenticated account default in the existing owner-scoped selection tables. The reserved (surface=thread, conversation_id=0) row is isolated by user_id; real conversations require strictly positive owned IDs. No schema migration or browser storage is added. The server snapshots both defaults when creating a new legacy thread or modern conversation, within the creation transaction. Existing conversations retain their own choices. Reading or submitting an existing conversation does not rewrite the account default; an explicit picker selection does.

Saved unavailable choices remain selected and show a visible warning; Chat submission is blocked until the user chooses an available model. Unavailable saved image names remain identifiable while unavailable image options stay out of the generation catalog. No silent provider/model substitution is added. All responses use private, no-store cache headers; account switches in the same browser were tested.

The Chat and image controls remain together, centered in the top Chat header independently of the title and optional action. Narrow headers place the group on its own centered row. Long model names wrap rather than clip, provider icons remain local, and the image cost preview remains below the controls. Styling is scoped to headers with the model selector.

Validation:

- 52 targeted Python tests passed: five new preference cases plus selected models, selected artifacts and Home regressions. New coverage includes unsent choice persistence across authenticated sessions/reopening, new-chat inheritance on both surfaces, existing-chat retention, CSRF, account isolation, invalid/foreign IDs and unavailable choices without substitution.
- 15 real Chromium responsive cases passed: Home, modern Chat and legacy Chat at 320/390/768/1024/1440 pixels. Verified centered header position, no horizontal overflow, keyboard focus, drafts, independent selections, Home reload/reopen, new-chat inheritance, old-chat retention and same-browser account switching.
- Three additional Chromium cases at 320/768/1440 passed with long selected names and provider availability revoked. Verified unclipped names, clear warnings, retained saved choices, hidden unavailable image option and explicit replacement clearing the warnings.
- Representative screenshots and machine-readable evidence: evidence/model-preference-center-20261017/.
- No paid inference, credentials, plan/quota changes or protected-product implementation changes. The preceding selected-artifact release bac2cf8 was LIVE at 12:42:07 UTC, deployment dep-db9mppjrjlhs73fdjg10, with all six image Models API access checks verified. This follow-up preserves that release.
