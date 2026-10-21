# Creative Services: on-page portfolio players

Baseline: `ed45d17f8cba1461fa8d100c02bbc4a6f5fe6d6d` (Finance header release).
Primary route: `https://app.kilasworks.id/creative-services/`.

## Shipped behavior

All 7 Event and 6 Social cards open a native dialog on the current page. The
dialog loads one provider iframe after activation. It never downloads or plays a
poster as video, never substitutes a preview loop, and makes no provider requests
on initial page load. Cards disclose Google Drive or Instagram instead of an
outbound arrow. The original provider URLs remain in `data-video-source` as the
source of truth; all thumbnails and their category/order remain unchanged.

Closing with the button, Escape or backdrop, switching video, changing collection,
retrying, or leaving the page removes the old browsing context and its media.
Native dialog behavior supplies inert background and keyboard containment; focus
returns to the card. A provider timeout removes the stalled frame. The iframe now delegates autoplay after a user opens a card, so asynchronous
provider playback can use that interaction. No autoplay URL parameter, initial
page-load provider request, global provider script, paid service or dependency is added.
The sandbox allows provider scripts/presentation but forbids popups and top-page
navigation. Fullscreen controls are permitted. Providers may still require login,
cookies or public embed access; these dependencies are disclosed in the dialog.

Cross-origin iframe `load` is deliberately **not** reported as successful video
playback. Error pages can also emit it. Access help and retry remain available through the collapsed “Video not starting?”
disclosure. A normal iframe load hides loading text; it does not claim playback
success. Timeout/error states show a short message and open help automatically. Provider errors that do not emit a
browser error event cannot be reliably detected from the Kilas origin.

The maintained source is `creative-services-site`; regenerate the Client Hub
bundle using `python scripts/package_creative_services.py`. No application route,
security policy, hosting root, DNS, database or unrelated module was changed.

## Actual asset inventory and blockers

The repository/workspace had 13 posters and **zero full video files**. Every
original source URL was checked on 2026-10-21. Direct HTTP access to all 13 was
blocked by the executor proxy: `Tunnel connection failed: 403 Forbidden`.
No downloader, CDN-token extraction or access-control workaround was used.

| Card | Original provider identifier | Full local file | Verified provider playback |
| --- | --- | --- | --- |
| Event 01 | Drive `1_RhxZwkV-XnmrJ4ygHAtJ3rZRMqwJOA3` | No; Drive metadata identifies `compro.mov`, 145,259,433 bytes, video/quicktime | No |
| Event 02 | Instagram `CzHI2JkPo5Q` | Missing | No |
| Event 03 | Instagram `Cs5lhuyg_qB` | Missing | No |
| Event 04 | Instagram `CuY-v6tg-NV` | Missing | No |
| Event 05 | Drive `1NUKvbCyoEIfsM39rVF3M96FICKMIowtt` | No; Drive metadata identifies `Video Event 25 Sept.mov`, 214,436,965 bytes, video/mp4 | No |
| Event 06 | Instagram `Cdw6-xnJ0bI` | Missing | No |
| Event 07 | Instagram TV `CSrOzSYp9-G` | Missing | No |
| Social 01 | Instagram `CuGo_oHg2tY` | Missing | No |
| Social 02 | Instagram `Cs2pwEHAdxT` | Missing | No |
| Social 03 | Instagram `CsxdzFyg5aA` | Missing | No |
| Social 04 | Instagram `CsxiIxAAC-w` | Missing | No |
| Social 05 | Instagram `CsxhaufgmkQ` | Missing | No |
| Social 06 | Instagram `CvJQ3l_BIrN` | Missing | No |

The authorized Drive connector successfully returned metadata and prepared raw
file references for Event 01/05. Retrieving either prepared file into the executor
was also blocked by `CONNECT 403`. Outcome: no file bytes were obtained, decoded,
transcoded or rehosted. Signed temporary references were not committed. Original
Instagram files remain unavailable; those 11 cards depend on Instagram embeds.
The exact original URLs and individual check results are retained in
`docs/qa/creative-playback-20261021/source-inventory.json`.

To make playback independent of Instagram/Drive, obtain the authorized full files
for all 13 originals and place web-compatible renditions in existing approved
hosting. This release does not claim that goal or all-source playback is verified.

## Verification

- 36 actual local responsive views: 1440/1280/1024/768/390/360, ID/EN, home/Event/Social.
- 30 grouping/category/anchor states pass, with original mappings and package actions.
- Eight real Flask route/sidebar tests pass, including the existing Finance data
  snapshot/session-preservation checks and host/session guards.
- `scripts/qa/creative_services_playback.cjs` tests all 13 cards at six widths in
  both languages using explicitly synthetic provider responses and a disposable
  test-pattern/sine WebM. These are UI/media lifecycle tests, not real portfolio
  playback evidence. It also checks lazy requests, controls, playsinline, decoded
  native fixture playback, one iframe only, teardown/retry, keyboard/focus,
  outbound-navigation containment, provider denial, timeout and no-JS behavior.
- The 13 original URLs, all poster/font/image bytes, every package price and
  service/CTA payload are unchanged from baseline. The generated bundle is checked
  byte for byte. Finance, attachments and Voice Over source remains untouched.

Internal before/after gallery screenshots, synthetic player screenshots, browser
results, preservation checks and route logs live under
`/workspace/creative-playback-review/`. Synthetic player files are named
`SYNTHETIC-PROVIDER`; they must not be presented as real provider playback.

Render status/commit verification and actual production browser/media playback
are separate evidence. The parent thread is responsible for the latter when
executor network access remains blocked.

Official provider documentation: [Instagram public embeds](https://developers.facebook.com/documentation/instagram-platform/embed-button),
[Google Drive video access/playback](https://support.google.com/drive/answer/2423694).

## Follow-up: media permissions, compact help and Android fullscreen

Parent production checks confirmed that the real Drive and Instagram embeds load
inside the site, but cloud Play clicks did not confirm progression. A later user
Android screenshot contains a different Drive frame and reports missing fullscreen;
this is not evidence of universal provider failure. No real-source playback success
is inferred from either the cloud check or the synthetic tests.

A real Chromium A/B test reproduces an application restriction in `9b77d33f`:
parent-card interaction without cross-origin autoplay delegation yields
`autoplay=false`, `NotAllowedError`, paused media and time zero. The scoped fix adds
`allow=autoplay` to the existing media/fullscreen permissions. On both synthetic
provider origins the same real browser now reports `autoplay=true`, starts unmuted
fixture media and advances time without a second child-frame interaction.

The old sandbox also rejects `requestStorageAccess()` specifically for missing
`allow-storage-access-by-user-activation`. Adding that token removes our sandbox
rejection. The browser still denies the test request for lack of first-party
interaction; no consent, cookie policy or provider authorization is bypassed. Popup
and top-navigation restrictions are retained. This is compatibility preparation,
not proof that either provider actually uses this API for the original videos.

The real Flask response has `Referrer-Policy: same-origin`; the iframe explicitly
sets `strict-origin-when-cross-origin`. A browser test with that exact response
header confirms the provider receives the origin referrer. No Creative Services
CSP or Permissions-Policy blocks frame/media access. Unrelated module CSP, auth and
security headers are unchanged. The official Instagram `embed.js` reader returned
429; no undocumented internal provider requirement is asserted.

The player now has an accessible fullscreen control for every video. It requests
native fullscreen on an ordinary wrapper *inside* the dialog, because the standard
forbids fullscreen requests on a `dialog` itself. Fullscreen retains the existing
iframe and audio context, shows close/exit controls, flexes to the current dynamic
viewport and rotates without reloading. If native fullscreen is unsupported or
rejected, the wrapper fills the available viewport and visibly says “Expanded view”
(“Tampilan diperbesar”). It never labels that fallback native fullscreen. Escape
restores the fallback; explicit exit and close also clean up native fullscreen.

Normal loaded view shows only title/provider, playback and a collapsed help summary;
status paragraphs and retry are hidden until requested or a load failure occurs.
There is no “playing” assertion based solely on iframe load. Portfolio layout,
original source URLs, prices, thumbnails and other modules remain unchanged.

Checks: `creative_services_player_permissions.cjs` covers the four real Chromium
A/B policy cases; `creative_services_fullscreen.cjs` covers 48 native/fullscreen,
unsupported/rejected fallback, touch, portrait/landscape, orientation, exit/close
and responsive cases. They use explicitly synthetic provider media and do not
claim real Android hardware or real portfolio playback verification.

Primary references:
- [Chrome autoplay delegation](https://developer.chrome.com/blog/autoplay)
- [WebKit storage-access sandbox prerequisite](https://webkit.org/blog/8124/introducing-storage-access-api/)
- [Fullscreen standard, including the dialog restriction](https://fullscreen.spec.whatwg.org/)
