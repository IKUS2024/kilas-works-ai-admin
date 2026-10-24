# Six supplied visual references — 2026-10-24

Source: `E:\edit kilas\design-references-6-images.zip` (6,453,621 bytes). Safely extracted into the task's `references/` folder; all six original PNGs inspected before editing. Original archive preserved. Baseline main and Render Live: `5f9dac717531d985811bc61b106236bf00fe4c29`.

Archive SHA-256: `eff38aa384eb37a8f1f657e15e61b3f56cdab2a40ee9b1f4ee314ef1ded49cc5`.

| Original | Runtime surface | Visual contract |
| --- | --- | --- |
| 01_1000345565.png | Chat home | White/peach canvas, KilasWorks header/profile, paired model selectors, genuine black/orange Kilas logo, bottom tabs and composer |
| 02_1000345566.png | Navigation drawer | White drawer, peach icon tiles/new chat, Library, expandable Products, chat history, Profile |
| 03_1000345594.png | AI Call setup and connecting | Separate dark runtime states, orange Start, existing persona/language controls, centered identity and call controls |
| 04_1000345564.png | Translator setup | Feature tabs, icon/title/description, vertical language pair/swap, explicit consent, orange Start |
| 05_1000345569.png | Translator active | Ignore phone/browser chrome; identity orbit, heading/guidance, opposing direction cards, End |
| 06_1000345574.png | Voice Over | Feature tabs, voice choices/selector/sample, script editor, record/assist, translate, orange Generate |

The user's supplied images supersede the old Figma concept and historical audit-only design restrictions. Operate mode: preserve existing routes, real handlers, locale/preferences and security. Finance is outside the write boundary. Responsive adaptation retains full control labels and touch targets; compact keyboard/zoom layouts retain the established chat hierarchy.

No paid provider calls, credentials, billing or security configuration changes are part of visual QA. Browser microphone/audio evidence uses synthetic sources and is not physical-device/provider certification.

## Implementation and review evidence

- Scoped design/tokens: [Kilas AI reference design](KILAS_AI_REFERENCE_DESIGN.md). The shared Finance design tokens and all Finance implementation files are preserved.
- [PR 157](https://github.com/IKUS2024/kilas-works-ai-admin/pull/157) implements the seven runtime surfaces represented by the six originals. The two Call states remain separate. The existing 4,000-character Voice Over backend limit is displayed truthfully instead of inventing the reference's 5,000-character capacity.
- Forty captures cover 320, 390, 412, 820 and 1440px across Chat, drawer, Call setup/connecting, Translator setup/active and Voice Over. Final immutable local evidence: `.impeccable/review/verdict-v2/`; the JSON report records geometry, zero paid calls and browser checks. Keyboard captures and the established visual-viewport regression exercise reduced visible height and preserved drafts.
- Independent finish review resolved five material corrections: centered closed-drawer layouts, pinned Call header/status/controls, whole narrow labels, Voice Over grouping and complete small-screen Character guidance. Final disposition: **ship for the reviewed corrections**, not provider or deployment certification.
- Local regression: Audio 52, Call 32, Interpreter 13, latest result 5, audio history 4 and personal voice 19 tests pass. The final Node Call/PCM/player/capture/DOM/Interpreter/viewport group passes all 101 tests. Synthetic Chromium lifecycle, Translator switching/repeat taps/reload/cancellation/audio cleanup, Home keyboard/zoom, audio-history pagination, fresh results and translated-script edit/alternate-version browser checks pass.
- Windows-only test imports use a task-local adapter outside the repository. It raises if Linux-only operations are actually invoked. Native Linux CI remains authoritative for fixtures that keep SQLite files open on Windows. The dedicated reference CI includes protected Finance behavior and a same-environment baseline comparison of legacy Home/workspace/Finance-localization failures.
- Broader legacy workflows retain pre-existing authentication/schema/locale/style-loading/lint failures. They are not presented as green and their assertions were not disabled. The focused Linux reference gate passed on the first candidate; the corrected release candidate must pass its own focused gate and baseline comparison before deployment.
- Creating a verification tab in the user's Chrome was unavailable through its extension API. Production verification therefore requires actual HTTP health/static-asset checks and Render's exact live revision; authenticated browser, physical-device, real-microphone and paid-provider acceptance are distinct limits.
