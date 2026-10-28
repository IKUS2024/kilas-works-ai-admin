# Copilot human answer templates — 2026-10-28

The latest owner correction supersedes PR174's no-slot preference. Scope is reply/translation policy and regression fixtures only. No UI, capture, provider, model, credential, access, billing, entitlement, schema or other-product change.

## Reproduced policy conflict

The live prompt explicitly prohibited fill-in slots and normally constrained replies to one sentence (2–3 for explanations). That conflicted with the owner's intended personal-answer examples. The reported school response was an assistant-meta refusal asking the app user for school/background details rather than suggesting a human answer. No live provider call was made to reproduce that exact wording; the owner supplied the observed failure text.

The new policy makes the human speaker perspective explicit. Ordinary questions about school, work, name or availability are addressed to the human, not to the app. Missing personal facts receive clearly localized inline `… (isi sendiri)` / `… (fill in yourself)` slots. Known heard facts fill the correct details. Unknown experience, tasks and results each require their own slot rather than invented achievements around an otherwise empty school name. General questions do not get irrelevant personal slots. Kilas Works identity remains reserved for explicit app-identity questions; truthful provider answers and legitimate ChatGPT mentions remain intact.

Depth follows the question. A school-name question can be one sentence; a multi-part school/experience/tasks/results question gets a coherent fuller answer covering every part. No rigid one/two/three-sentence limit or padding requirement remains.

## Reviewed illustrative samples — synthetic, not model outputs

- **Sekolah di mana?** → Saya bersekolah di … (isi sendiri).
- **Where did you study, and what did you major in?** → I studied at … (fill in yourself), where I majored in … (fill in yourself).
- **Known heard background: SMA Nusantara, jurusan IPA. Asked school/major.** → Saya bersekolah di SMA Nusantara, jurusan IPA.
- **School, major, work, tasks and results, all unknown.** → Saya bersekolah di … (isi sendiri), dengan jurusan … (isi sendiri). Pengalaman kerja saya yang relevan adalah … (isi sendiri). Dalam pekerjaan itu, tugas utama saya mencakup … (isi sendiri). Contoh pekerjaan yang bisa saya ceritakan adalah … (isi sendiri), dengan hasil … (isi sendiri).
- **Known heard background: two years as a shop administrator handling stock records and customer questions; results unknown.** → Saya punya pengalaman dua tahun sebagai admin toko, dengan tugas mencatat stok dan membalas pertanyaan pelanggan. Contoh hasil pekerjaan saya adalah … (isi sendiri).

School names and experience above are explicitly synthetic context fixtures, not real user facts. The JSON corpus also covers mixed Indonesian/English, general knowledge, app versus human identity and no invented facts. Good/bad fixtures and mock pipeline assertions test the prompt contract, first-person fixture perspective, complete transport/persistence, known-context payload, and slot-preserving translation instruction. They do not prove Luna adherence, real translation quality or factual interpretation in a paid model run.

## Cap and postprocessing audit

- Existing reply model `gpt-6-luna`, low effort, maximum completion 1,024 tokens; unchanged existing per-turn reservation/budget.
- Reply transport rejects over 4,000 characters or unfinished output. It does not truncate to a sentence/word count. Only outer whitespace is stripped.
- There is no slot scrubber, persona-name replacement or assistant-refusal string rewrite. Browser textContent safely renders the model's original text, including localized slots.
- Translation has its existing separate maximum 1,024 tokens, JSON validation, 16,000-character stream bound and 5,000-character field bound. Prompt now explicitly preserves every slot in the ellipsis-plus-parenthesized-instruction form, localizes the fill-yourself instruction, keeps first person/detail, and forbids filling unknown factual values.
- Translation also rejects a changed count of explicit template slots, including ASCII/fullwidth punctuation variants, rather than silently filling/removing slots or rewriting content. A mismatch follows the existing incomplete-translation path, without automatic paid retry. This validates structural preservation, not the real model's translation semantics.
- These technical ceilings remain to preserve the authorized cost envelope. They are finite; arbitrary essay-length answers are not promised. Multi-part regression replies contain more than three sentences and complete within the existing envelope.

## Verification / release procedure

Run Copilot backend and responsive browser contracts with provider mocks, including Indonesian school, English education, known/unknown experience, multi-part and mixed-language questions, direct general answers, translation slots and >3-sentence persistence. Preserve existing cancellation, auth/CSRF, metering, hidden legacy Chat and tool-navigation regressions. Capture the changed example result text through the existing screenshot artifact flow; no layout redesign.

Backend-only changes now trigger the existing public read-only release smoke. It also waits for a nonsecret policy SHA256 marker matching the new SYSTEM prompt, because unchanged UI assets alone could match before this backend release. A contract test guards marker freshness. The marker adds no UI or capture behavior. Render must separately confirm the exact merge commit LIVE and startup logs must confirm that SHA; asset matching alone is not backend-version evidence. No paid model/audio acceptance is run; no production-authenticated writes or microphone requests are needed for this smoke.

CI initial browser run exposed an existing synchronization race in the repeated-tap fixture: its provider-call snapshot could precede entry of the already-admitted STT call, because the status event is published first. The fixture now waits for that existing provider-entry event before counting; the duplicate-call assertion remains. No production capture or request handler changes are involved.

A second CI fixture timing issue inspected Arabic direction as soon as the last text delta matched, before the final saved result was rendered. The RTL assertion now waits for completed idle state and automatic direction resolution, with a bounded five-second wait; it still requires `dir=auto` and computed RTL. Production rendering/capture remain unchanged.
