# Restore the retained AI Chat

The owner reversed the Copilot primary experience on 31 October 2026. AI Chat is the default again. Its existing composer, model selectors, attachments, streaming, saved chats and agent routing are reused without redesign. `_home_workspace.html`, `home.html`, `kilas_ai.js` and `kilas_home.js` are unchanged from the pre-Copilot implementation (`66683656^`).

`KILAS_COPILOT_VISIBLE` now defaults to false. Normal navigation and owned history expose Chat. Marked Copilot sessions are filtered from this presentation only; their messages, preferences, usage and attachments are not deleted or migrated. Owned Copilot bookmarks redirect to Chat while hidden; another owner's bookmark still returns 404. Explicitly setting the flag true restores the retained Copilot UI and its own history. Copilot processing handlers remain intact.

Release to the existing Hub uses a merge of the single nonsecret flag `KILAS_COPILOT_VISIBLE=false`, preserving every other environment variable. Observe whether that save starts a deploy before triggering another one. Verify the exact merged commit and the nonsecret startup line `KILAS_PRIMARY_UI primary=chat history_retained=true`. Rollback of presentation is the existing opt-in flag, without data restoration.

No schema migration, user-data cleanup, provider/model budget change, Finance code change, Translator/VO engine change or Creative Services rollback is included. The Finance history test seeds the now-primary ordinary Chat instead of a Copilot-only session, keeping its original ownership, read-only and business-context assertions.

Validation uses disposable SQLite, real HTTP routes/CSRF/session handling and mocked providers. The focused browser matrix covers English, Indonesian, Spanish and Chinese at 360, 393 and 1440 pixels; home, saved Chat, attachment send, result reload, error recovery, hidden Copilot and no horizontal overflow. Screenshots are synthetic account renders, not authenticated production acceptance. Production smoke is read-only: health, exact public assets and anonymous authentication boundaries. No paid model generation, real microphone or production-account conversation is tested.
