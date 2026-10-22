# Home keyboard visual consistency correction - 2026-10-22

Baseline a3575b99951dbd28818dd36174bceaa39919bf18. User reported that typing changes the Home design.

Verified causes: Home polish CSS had explicit home-keyboard-open selectors hiding the logo and starters and setting heading20px, plus max-height540px rules hiding logo and reducing heading22px/starter sizes. Existing kilas_chat.css keyboard selectors had greater specificity than the Home tab rules: display:flex, width:auto and left alignment replaced the equal grid. Existing typography resolves the normal Home title to clamp(1.5rem,2.6vw,2rem); the correction uses that same identity during keyboard state.

Correction is Home-only CSS and cache key. Remove the short-height/keyboard visual replacement; retain logo, heading, starters and equal tab geometry. The welcome area uses automatic vertical margins for centering when room exists; those margins collapse naturally when constrained and the upper area scrolls. Keep normal-flow bottom composer, visualViewport offsets/heights, safe-area padding and separate transcript scrolling. No transport, draft, model, provider, Finance or generation code change.

Focused acceptance extends the existing five-width Home browser suite. Compare heading font, logo display/size, starter display and exact tab width/font/padding across two focus/open/blur/close cycles. Simulate Android-like visualViewport-only shrink to380px with48px offset while layout viewport remains unchanged. Assert same appearance, preserved synthetic draft, scrollable upper content and composer inside visual viewport. Also retain layout-viewport resize, short/tall empty/populated transcript, navigation, draft and attachment regressions. The tests block external browser traffic and make no chat POST/provider generation.

Actual Android/iOS hardware was not controlled. Parent inspected the user's real screenshots; the textual observation and code establish the causes. New visualViewport tests are explicit simulations, not claims of hardware verification. Exact CI/commit/Render/live evidence is recorded after verification.
