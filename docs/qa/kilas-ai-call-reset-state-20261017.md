# Call reset state correction

An offline production-engine regression reproduced a valid `SPEAKING` snapshot
containing audio followed by reset, without a replacement answer. Reset cancelled
playback and reopened real microphone PCM, but the displayed state remained
Speaking. The server can retain SPEAKING until turn completion, so its snapshot
does not repair this mismatch. The new test failed before the change.

Reset now explicitly displays Listening when it reopens the microphone. A
subsequent audio frame still changes to Speaking as before. The one-line change
does not alter capture, PCM, playback, turn detection, echo handling, End, search,
or the captured-input preservation fix. Call module URLs are cache-busted.

All 43 focused frontend tests passed (304.562ms), including reset real-PCM
forwarding, captured input behind an ACK, queue drain, stale callback fencing,
next utterance and End. Zero provider calls. This fixes a displayed-state
mismatch, not the unverified cause of premature replies or choppy audio.
