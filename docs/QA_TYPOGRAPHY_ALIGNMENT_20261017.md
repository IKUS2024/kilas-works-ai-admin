# Shared app typography and composer alignment

Follow-up to `75c10a32dca0b3758ffabacbf0165a9e597d1b57`. The execution environment responded to a direct check after the disconnect callback; unsaved work remained intact and the original task continued in the same workspace.

## Font and scope

Kept the existing bundled **Manrope** variable font, licensed under [SIL Open Font License 1.1](../client-hub/static/fonts/Manrope-OFL.txt). The shared stack adds system UI, Apple/Segoe UI/Noto Sans and generic sans fallbacks for platform and multilingual coverage. This is an existing licensed app font, not a claim of using ChatGPT's proprietary typeface. Code uses a separate system monospace stack.

A small `kilas_typography.css` layer supplies coherent rem-based body/control/metadata tokens across the existing white app shell and modules. Body and editable controls use a 16px baseline; chat prose uses 16px/1.65 with natural word spacing, readable paragraph/list spacing and an assistant text measure capped at 72ch. Code uses 14px monospace and retains its own horizontal scrolling. Headings and secondary controls retain a smaller, consistent hierarchy. No justified prose or stretched word spacing.

The existing premium-style partial loads this layer in the head. Finance blueprint pages, Finance-named entry endpoints and Finance-enabled shells explicitly exclude it. Finance's existing stylesheet remains. No Finance styling, ledger/data, admin redesign or public Creative website change is included.

## Measured alignment correction

Baseline computed styles showed the send SVG about 3px above its button center, the legacy plus about 2px below the textarea's first-line center, and the modern plus about 2.6px above its own center. Call used a separate system-only font stack. Voice Over editable fields/selects were 15px.

The existing plus / Message / send+Call grid and control order are retained. Composer icon controls now use matching 44px normal-size boxes, centered 20px SVGs, consistent circular containers, balanced padding and the shared font stack. A single-line textarea aligns with the icon centers; multiline drafts keep the controls at the textarea bottom. An empty legacy pending-attachment element no longer creates an extra grid gap; actual attachments keep their existing placement. Existing keyboard resizing, safe-area padding and textarea auto-growth remain.

| Viewport width | Before: maximum icon/text center difference | After | Voice Over input before / after |
|---:|---:|---:|---:|
| 320 | 3px | 0px | 15px / 16px |
| 360 | 3px | 0px | 15px / 16px |
| 390 | 3px | 0px | 15px / 16px |
| 768 | 3px | 0px | 15px / 16px |
| 1024 | 3px | 0px | 15px / 16px |
| 1440 | 3px | 0px | 15px / 16px |

Model selectors remain centered. Existing page gutters and feature positions, logo assets, tabs, plus-left/send-and-Call-right ordering, controls, flows, providers and model/history behavior are preserved. Typography naturally affects text wrapping; no new controls or descriptions are added.

## Verification

- Baseline and changed computed-style measurements cover 24 viewport/module combinations: Home, modern Chat, Translator and Voice Over at all six requested widths. Internal records: `/tmp/kilas-type-before.json`, `/tmp/kilas-type-after.json`.
- **Six full Chromium viewport scenarios pass** at 320/360/390/768/1024/1440px. Each checks both empty Chat composers, exact single-line icon/placeholder centering, matching hit targets, balanced composer gutters, centered long model names, four-line textarea growth/bottom alignment, an actual synthetic local attachment selection/removal, a 360px-height keyboard geometry mock, and preserved empty no-scroll behavior.
- Each viewport also checks populated discussion with Indonesian/English/Chinese/Arabic text, paragraphs/lists/inline code and a long code line, independent transcript and code scrolling, no document horizontal overflow, and retained transcript reading position while typing. A 125% root text-size zoom verifies scaled text/input alignment and no horizontal overflow.
- Translator and Voice Over smoke checks pass at every width: editable fields at least 16px, no overflow, simple unchecked required Translator consent and stable Start with no inline policy link, and removed Voice Over sample controls/player remain absent.
- **59 focused Python tests pass**: 58 existing Home/sidebar/model-initial-render/consent/personal-voice regressions plus the new shared-style Finance exclusion check. **Five existing viewport-controller Node tests pass**. Syntax/diff checks pass. No whole-repository or Finance ledger suite was needed for this scoped style layer.
- One focused visual review covered mobile empty Chat, tablet populated prose/code, desktop Chat and mobile Translator. Internal synthetic screenshots and browser metrics: `/tmp/kilas-typography-browser/`; logs `/tmp/kilas-typography-browser.log`, `/tmp/kilas-typography-python.log`, `/tmp/kilas-typography-scope.log`, `/tmp/kilas-typography-node.log`.

No microphone, paid API/inference, production customer content, database migration, model routing, audio pipeline, quota/pricing or credential change was used. Browser coverage is Chromium with viewport/keyboard/text-size simulation; physical Android Chrome, iPad/iPhone Safari, OS keyboard, real pinch/browser zoom and screen-reader behavior were not established. Authenticated production visual acceptance remains required after deployment.
