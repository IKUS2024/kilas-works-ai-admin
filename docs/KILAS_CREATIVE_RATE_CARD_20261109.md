# Creative Production 2026 refresh

Source: https://app.notion.com/p/Creative-Production-Rate-Card-2026-413aa064bd9881eb8898f58aa3920659
Read and re-read in the public Notion UI on 2026-11-09. The user first requested only Basic, then explicitly approved all four newly added Video Editing levels after the refreshed page was checked. Latest instruction: “tampilkan ke empat itu”.

Editing now has Basic Rp250k/video, Advanced Rp350k–500k/video, Premium / Creative Rp600k–900k/video (all maximum one minute), and Professional / Commercial from Rp1.5m/project with duration/output defined by brief. The old duration-based table is retired. Advanced Color Grading is no longer a separate add-on; the remaining four add-ons match the latest source.

## Scope and result

- Four services: Event Documentation, Monthly Content Production, Commercial Production and Video Editing. Existing brand, artwork, portfolio permalinks and customer data retained.
- Event prices: Essential Rp2m / Professional Rp4.5m / Corporate Rp7.5m. Monthly: Basic Rp3.5m / Growth Rp6m / Professional Rp9m. Commercial: Promotional Video Rp4.5m / Product Commercial Rp7.5m / Brand Campaign and Company Profile from Rp12m.
- All are reference prices, confirmed through a written quotation after agreeing scope. New automatic invoices are blocked at route and order-service levels. Existing invoice snapshots, amounts, private proofs, payment routes and nonce replays remain supported. Monthly upfront and other projects' 50% deposit / 50% before delivery terms are disclosed; no payment configuration or stored financial records changed.
- Old influencer add-ons retired from new offers. Editing add-ons follow the source. No legacy longer-duration tier is published.
- Header Portfolio now targets the on-page gallery. Instagram remains separately linked inside the gallery. Services targets the actual four-service list; consultation targets the form instead of the preceding company address. Mobile menu overlays rather than enlarging the sticky header. Repeated links, direct hashes, detail tabs, focus and Back/Forward are handled consistently.
- Maintained source remains `creative-services-site/`; `scripts/package_creative_services.py` produces the Client Hub bundle. All 62 files match byte for byte.

## Verification

Passed locally:
- 31 tests: Creative Services source/routing/Finance read-isolation, historical checkout security/payment snapshots, current quotation-only gates.
- Unique IDs and every local anchor resolution, extracted JavaScript syntax, Python compile and git diff whitespace checks.
- Deterministic generated bundle check.

Not completed locally:
- Chromium responsive/browser regression could not launch: Linux `socket() failed: Operation not permitted`, including approved escalation. Cloud browser could inspect the existing live app and Notion but could not reach this executor's localhost. No visual pass is claimed for the new build.
- Existing Creative QA workflow retains historical browser/payment/native-PostgreSQL protections with explicit historical fixtures, updates current studio assertions, and adds a new 64-detail-view / 16-home-state regression across four languages and 320/393/820/1440px. CI and subsequent live verification must pass before the release is called complete.

No production write or deployment has occurred at this checkpoint. User later explicitly approved pushing to IKUS2024/kilas-works-ai-admin and deployment. Parent coordinates the combined AI Chat / Translator / Creative release; this isolated commit must not overwrite concurrent work.
