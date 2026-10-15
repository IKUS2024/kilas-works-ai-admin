# Live Translator output retention

Voice Over, uploaded audio/video translation, and Live Translator have separate
result lifecycles. This change does not change providers, voices, prices, quota
limits, measured-duration settlement, or cancellation/accounting rules.

## Historical results

Recent on the Voice Over tab shows only ordinary Voice Over jobs, four per page.
The upload translation tab retains its own uploaded-translation results.
Live jobs are excluded before counting or paginating, using the server-owned
`content_origin` marker or an owned Live session/turn relationship. Titles and
client-chosen operation-key prefixes alone are not classification evidence.

Old Live rows and their existing files/text are not deleted or rewritten. They
are hidden from ordinary saved-result/history/edit/download routes. This is a
reversible application filter; historical database backups are not purged.
An ordinary Voice Over titled “Live Translator” remains an ordinary Voice Over.

## New Live output

New Live jobs persist only audit/accounting metadata: ownership, session/turn
association, source marker, timestamps, status/error category, provider/voice
identifiers, language codes, idempotency fingerprint, numeric initial allowance,
measured duration and charged/reserved seconds. The numeric initial allowance
replaces deriving that same allowance from a stored script; it does not reset or
reduce the existing conservative allowance for failed/dispatched jobs.

The job's script, original script, source audio and result audio database fields
are NULL from admission onward. Input STT and translation text stay in the active
worker's RAM; output text and MP3/segment bytes use an owner/session/turn-bound RAM
cache. Publishing still waits for validated complete audio and accounting.
Owner, active-session, turn, language-pair and result-owner checks remain fresh.
The Live audio endpoint supplies temporary inline MP3 playback, not a saved-result
download/history item. Ordinary Voice Over/upload downloads are unchanged.

The cache is cleared when the server confirms End, when processing the next
utterance begins, on processing failure, or when its worker exits. Cache access
expires 600 seconds after its last write; a background sweep drops expired RAM
references within another 30 seconds. Reading does not extend retention.
There are at most four entries, with a 40 MiB per-entry bound including legacy
segmented bytes. Capacity/configuration failure rejects admission before paid
provider dispatch. The current Render service was verified to use one instance
and one Gunicorn worker. Multi-worker configuration is rejected before provider
dispatch; horizontal scaling requires an appropriate shared temporary design.

Worker restart or cache expiry fails closed: the client gets
`session_output_expired`; the paid operation is never regenerated automatically.
Billing metadata is retained, including output already received from a provider
when End raced publication. Cancellation cannot undo incurred supplier cost.

Media validation/legacy segment joining can use bounded temporary working files
inside TemporaryDirectory contexts. Normal completion and exceptions remove
them; abrupt process/system failure can leave operating-system buffers or
temporary working files until instance cleanup. Browser decoding/network buffers
can also outlive a server cache deletion. No claim of instantaneous physical
erasure, control over user-made copies, or removal from historical backups is made.

## Provider boundary

ElevenLabs and OpenAI still receive the data necessary for the selected operation.
This release changes application retention, not provider settings or contracts.
It does not claim zero provider retention. ElevenLabs stream logging defaults to
enabled; disabling it requires eligible enterprise zero-retention support.
OpenAI retention depends on the endpoint and account data controls. No new key,
subscription, permission, zero-retention setting or provider deletion was requested.

Official references:
- https://elevenlabs.io/docs/api-reference/text-to-speech/stream
- https://developers.openai.com/api/docs/guides/your-data
