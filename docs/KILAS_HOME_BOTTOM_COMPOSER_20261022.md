# Home bottom composer correction - 2026-10-22

Supersedes the centered composer grouping in `bed5aabae449e655efea481cd71cab042d03ae80`. The user explicitly requested that the chat bar remain at the viewport bottom.

Only Home polish CSS, its cache key, and focused browser acceptance were changed. The empty welcome area flexes to fill available space; the task tabs and composer retain their normal flow at the bottom. Existing visualViewport height/offset handling and safe-area padding remain authoritative. No fixed overlay is introduced. Populated transcripts retain their independent scroll area. Three equal starters, compact brand/model controls, the real VO tab, and stale-warning/draft protection remain intact. No Finance, backend, provider, model or generation change.

Acceptance covers empty and synthetic populated Home at 320/390/412/820/1440px, tall/460px short viewports, and focused keyboard resize down to 380px. The composer must fit within the viewport and remain within 60px of its bottom (hint and safe-area space included), with no horizontal overflow or transcript overlap. Synthetic long messages scroll independently; older reading position remains accessible on resize. Existing Node viewport tests cover visualViewport offset, Android layout resize, exact older reading-position preservation and following the latest message. Existing Experience browser suite covers chat-to-VO exact text/back-forward, Library, credits preview and Creative brief without paid provider calls.

Local captures are in the task `home-polish-qa/` folder. They use synthetic accounts and models; native Android/iOS hardware is not claimed. Exact CI/commit/Render/live evidence is recorded separately after verification.
