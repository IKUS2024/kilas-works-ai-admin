# Creative images and direct checkout follow-up

The user's latest screenshot showed narrow side images on phone-sized service cards and icons instead of pictures on two categories. This follow-up preserves existing artwork and all published prices while changing the service cards to wide, proportional landscape images. All four service choices and all fourteen package cards have images. Image dimensions preserve source proportions and CSS uses object-fit rather than stretching.

The user requested the normal direct-payment checkout again. After clarification, range and starting-price packages still require discussion before payment. Nine exact-price offers return to the existing authenticated checkout, invoice and payment route. Five offers remain quote-only: Advanced, Premium and Professional Editing, Brand Campaign and Company Profile. Quote-required editing add-ons cannot be submitted as priced extras. No minimum estimate, new deposit rule or price change is introduced.

Existing payment configuration, Finance code, stored invoices and snapshots are unchanged. Disposable tests cover current prices, ownership, CSRF, nonce replay and old invoices. The browser suite retains its historical journeys and adds current catalog login-to-payment paths. No production invoice, transfer, proof upload or outgoing message is created during verification.

Local validation: 35 unit tests pass; source/bundle check and syntax checks pass. Chromium cannot launch in the executor because socket creation is restricted, so browser acceptance and screenshot review run in GitHub CI before deployment. Live verification follows both Hub and standalone deployments.
