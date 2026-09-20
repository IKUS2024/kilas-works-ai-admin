# Finance conversation contract

The Assistant is an interface to the existing Finance services, not a second ledger.
Document recognition and extraction are unchanged by this release.

## Understanding and context

`finance_semantics` supplies shared vocabulary, calendar periods, scoped name matching,
and a constrained semantic interpreter. Natural-language turns use the semantic brain;
only exact confirmation/cancellation, quick replies, and safe scalar values bypass it.
Finance instructions use an allowlisted intent and literal user-supplied
slots; IDs, synthesized values, arbitrary actions, and arithmetic are rejected.

`finance_query_plan` stores resource, period, currency, entity filters, metric, grouping,
pagination, and any pending entity question as structured signed context. Follow-ups
replace slots. Complete new questions reset the prior filters. Queries never concatenate
historical user instructions. Resolved entity IDs (never data snapshots) retain identity across renames. Every relevant
turn resolves these IDs in the live tenant/branch scope. Deleted or inactive references
are rejected rather than rebound to a similarly named replacement. No report totals,
customer notes, or previous balances are authoritative conversation memory.

`finance_draft_interpreter` edits the active signed draft. It knows the editable field
contract and the server's next question. Required slots are requested one at a time;
optional fields do not prevent confirmation. Ambiguous names require clarification.
Bare account names are resolved as accounts, not assumed to be currency codes.

Pending drafts are arbitrated before permissive slot filling, using the same query
signals, command classifier, and constrained semantic interpreter as new messages.
A read-only interruption returns `keep_pending` and its separate signed query context;
the browser retains the original draft and confirmation token, without renewing its
expiry. Draft edits clear the read context. Confirmation/cancellation remain explicit
server decisions. A new write asks the user to cancel the old draft before submitting
the new command, so no review is silently replaced. Unknown or unavailable semantic
results leave the draft unchanged. Each ambiguous turn uses at most one model request.


Successful writes return a signed record reference. A request such as “ubah transaksi
yang tadi” creates another review; it never modifies the earlier record implicitly.

## Writes

Existing customer, transaction, recurring, invoice, and payment adapters remain in use.
`finance_conversation_actions` adds reviewed adapters for accounts, categories, branches,
rename/deactivation, due recurring occurrences, transaction correction/void, invoice
void, and FX recording/void. Every adapter calls the same manual service.

The existing Finance business transaction can be re-entered only by the same business
and actor through `finance_service._write`. A command checks its nonce and digest in
the existing audit log, revalidates references and any target snapshot, calls the domain
service, and records the result in the same transaction. Conflicting revisions of a
confirmed nonce fail; concurrent identical confirmations return the same record.
FX confirmation also binds the reviewed native account currencies.

Invoice creation defaults to a draft. Explicit create-and-issue or create-and-already-paid
requests show one review of the ordered canonical operations: create draft, issue, then
record full payment. All run under the existing Finance business lock and roll back
together on failure. Invoice status is never assigned by a chat adapter. Stable service
keys make repeated confirmations idempotent.

`finance_assistant_payment` resolves a named customer's current open invoices. One is
selected; multiple require a useful invoice choice; none produces a clear no-active-debt
answer. Full settlement derives the outstanding amount from invoice items/payments,
never customer notes. Partial payments retain their specified amount. An unspecified
paid date is requested, along with the receiving account and required income category.
Invoice content and outstanding are re-read under the write lock before confirmation;
a change produces a fresh review requiring another “oke”. Replays use the same payment
key, including after a completed payment. Old signed operator confirmations preserve
their original idempotency protocol during the release transition.

A newly confirmed customer supplies implicit context for the next invoice, and read
queries remember their resolved customer for “dia / sisanya”. Description and price in
one answer update the same invoice line. Only an explicit additional-item intent appends
a line. Scheduled recurring costs affect cashflow only when one reviewed due occurrence
is posted through the existing occurrence service.

Bulk branch reset, real money transfers, and sending external messages are not chat
actions. Collection reminders are generated text, never claimed as sent messages.

## Numeric truth

`get_cash_totals` is a shared scoped SQL projection used by manual summaries and chat.
All-time totals are independent of export row/date limits. POSTED transactions are
grouped by native currency and their actual `occurred_on` date. Opening balances, FX,
draft invoices, and unposted recurring schedules do not enter operating cashflow.

Balances aggregate all actual ledger movements without loading a bounded export.
SQLite uses an exact integer aggregate because SUM(int64) can overflow and floating
TOTAL loses precision; PostgreSQL retains SUM(bigint)'s exact numeric behavior.

Historical invoice payment status is derived from payments through `as_of`. A later
payment cannot remove an earlier outstanding receivable. DRAFT and VOID invoices are
excluded from receivables.

## Verification

`test_finance_semantic_agent.py` exercises messy conversations, context replacement,
entity ambiguity, branch/token safety, manual-service parity, atomic rollback/retry,
concurrent confirmation, stale snapshots, historical AR, FX, recurring cashflow, and
integer precision. Browser tests verify opaque contexts, server-selected questions,
and clearing completed drafts. Run the isolated Finance regression runner and Node
Finance tests; no production finance records are needed for verification.

`test_finance_live_conversation.py` covers real multi-turn create/issue/settle journeys,
combined invoice fields, live void/deactivation/deletion/rename changes, current balances,
partial/full settlement, changed-outstanding re-review, compound ordering/rollback,
concurrent idempotency, and scoped reference/confirmation boundaries. Language-provider
responses are mocked; all accounting and database operations use the actual services.
