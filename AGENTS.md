# Kilas project design tooling

## Impeccable
Project-local Codex skill: `.agents/skills/impeccable/SKILL.md`.
Read `PRODUCT.md` and the newest entries in `docs/KILAS_MASTER_COMPLETION_STATUS.md` before UI work. Use existing implementation as visual authority.

Current scope is **Kilas Assist installation, context initialization and audit only**. Do not implement audit recommendations until the user requests changes. Do not deploy this tooling change.

Kilas Finance is protected: do not modify its UI, business logic, ledger, database, routes, styles or existing integration. Shared templates/CSS must not be rewritten globally to address Assist findings. Do not run whole-repository automatic design fixes. Do not reset production data or mutate WhatsApp/payment configuration.

Use `$impeccable audit Kilas Assist` to review; inspect the scoped targets and report verified findings separately from detector suggestions. Details and exact commands are in `docs/KILAS_IMPECCABLE_SETUP.md`.
