# Finance conversation contract

The Assistant is an interface to the existing Finance services, not a second ledger.
Document recognition and extraction are unchanged by this release.

## Understanding and context

`finance_semantics` supplies shared vocabulary, calendar periods, scoped name matching,
and a constrained semantic interpreter. Clear instructions use deterministic parsing.
Unfamiliar Finance instructions use an allowlisted intent and literal user-supplied
slots; IDs, synthesized values, arbitrary actions, and arithmetic are rejected.

`finance_query_plan` stores resource, period, currency, entity filters, metric, grouping,
pagination, and any pending entity question as structured signed context. Follow-ups
replace slots. Complete new questions reset the prior filters. Queries never concatenate
historical user instructions. Entity names are resolved again within the current scope.

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

Invoice creation remains separate from issue. Additional invoice items share the manual
item contract and totals. “Lunasi” resolves the actual remaining invoice balance on the
server and still requires review. Scheduled recurring costs affect cashflow only when
one reviewed due occurrence is posted through the existing occurrence service.

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
