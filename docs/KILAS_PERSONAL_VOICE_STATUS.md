# Suara Saya — Voice Over release

## Scope

Personal Voice Over only. Existing ElevenLabs Multilingual v2 TTS, audio accounting,
private result playback/download and owner authentication remain in use. Translate
defaults and pipeline, other products, billing and external configuration are unchanged.

## Implementation

- Browser microphone/MediaRecorder, playback, re-record, consent and retryable recording.
- Server-only per-user clone association; no raw microphone recording stored in the DB.
- Additive `0084_kilas_personal_voice` creates only `kilas_audio_personal_voices`.
- One identity for Indonesian and English; original text is submitted without translation.
- Shared voice choices exclude personal clones; provider identifiers stay out of the UI.
- Owner locks/claims prevent duplicate clone creation and replacement/generation races.
- Failed replacement keeps the old voice; old provider clone is removed after successful replacement.
- Provider-required verification fails closed instead of marking an unusable clone ready.

## Local verification — 2026-10-05

- 9 focused consent/CSRF/persistence/idempotency/isolation/replacement/provider tests PASS.
- Chromium fake microphone with real MediaRecorder: record, playback, consent, create,
  refresh persistence, same private identity for ID/EN, playback/download, failed
  replacement/retry: PASS at 320/360/390/430/768/1024/1440 px. No JS errors or overflow.
- Desktop/mobile screenshots inspected; scoped Impeccable polish/detector completed.
  Static Jinja detector cannot resolve dynamic stylesheet links; advisory defaults are
  checked against actual rendered styles. Existing visual identity is retained.
- Existing Audio suite: 35/36 PASS locally. Padded large WAV upload hits a Windows
  FFmpeg timeout on BOTH unchanged main and this patch. No Translate workaround added.
- Native PostgreSQL additive/idempotent and personal voice rehearsal added to Audio CI.

## Release checkpoint

Commit/push, required CI, Client Hub deployment and real provider QA are pending.
Real personal voice identity/quality must be checked using the user's own recording
and explicit checkbox consent. Simulated microphone/provider tests do not establish
production provider permissions, clone availability or actual voice resemblance.
User agreed to record; dedicated production QA session requires renewed sign-in.
