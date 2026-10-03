# Kilas Intelligence / Premium Capacity ? production release evidence

Updated 2026-10-04 Asia/Bangkok. Implementation released and authenticated synthetic production QA passed. Earlier failed scenarios and their fixes remain in the history below.

## Final production code and deployments

- Production code SHA: `5f7e8bd860060544dc6aa494a6c579494bb2d8e9` on main. Commit: `Count distinct attachment occurrences across mirrored context`.
- Client Hub: `kilas-works-client-hub`, `srv-da7ti2psrm7s73dh9i2g`, deploy `dep-db0ks8m0tbcc7389ocsg`, LIVE, finished 2026-10-03 18:50:11 UTC.
- Existing Automation Cron: `kilas-ai-automation-runner`, `crn-dau073vlk1mc73d6ilc0`, deploy `dep-db0ksv3ncjis739ve3e0`, LIVE, finished 18:51:11 UTC, same code SHA.
- This final evidence update is a documentation-only follow-up; it does not require another deployment. No new resources, plan upgrade, AI Admin deployment, new migration, schema change or data reset.

## Automated release gates

All five workflows on the production code SHA passed: Focused QA `37145214939`, Chat Quality `37145214941`, Automation `37145214950`, Autonomous Agent `37145214920`, Global UI `37145214965`.

Coverage includes native disposable PostgreSQL concurrency/settlement/order reuse/retained expired credits, unit/security/account isolation/approval gates, code sandbox, streaming/tools/Work/keyboard capability browser checks, Finance/localization and 544 page/language/width browser combinations. Final targeted local reruns: 34 intelligence/capacity, 24 unified Chat and 35 cost/quality tests passed. Earlier 27-module focused matrix and the unchanged Video gate also passed. Impeccable scoped finish review: ship; detector Jinja/CSS limitations were distinguished from rendered evidence. No full design audit or automatic global rewrite.

## Real authenticated production QA

Controlled account: `irvankarnavi@gmail.com`, role CLIENT_OWNER, zero AI subscription rows. Only synthetic QA conversations, uploads, plans and a pending test capacity order were created; no proof submitted, payment approved, customer data reset or external message sent.

| Scenario | Evidence |
| --- | --- |
| Home/navigation/Settings/Services | Actual customer pages loaded; Services targets https://kilasworks.id; no Assist in normal navigation. |
| Short/normal/difficult Chat | Conversations18/19/20: 16/133/805 words. Usage records show Luna for ordinary requests and Sol for difficult analysis. Laundry correction and refresh persistence passed. |
| Search | Exact previously failing date-of-check prompt passed after fix, conversation26, official python.org source and no Work job. |
| Multi-file / PDF reading on FINAL SHA | Conversations31/32: verified difference30, PDF code KILAS-QA-527 and quantity42. Rows342/343 COMPLETE: multi-file Sol, single factual PDF Luna, no PDF repair. Zero JS errors. |
| Image understanding | Conversation29 correctly identified synthetic orange shape. |
| Image creation / reference edit | Conversation25: artifacts15/16 downloaded, distinct files, edit persisted after refresh. Visual inspection confirmed white mug becomes blue while shape/composition remains consistent. |
| Work documents / revisions | Conversation30: jobs21/22 COMPLETE, artifacts17/18 downloaded and persisted. Downloaded PDFs each one page; revised title and fourth packaging-check step correct, original two-row synthetic table retained. Text and rendered PDF visually inspected. |
| Video single / connected multi-part | Synthetic project18 mobil?baju?food?premium/no-voice-over PATCH, exact clip handoffs, no retired subject content, English prompt checks, seven clipboard actions, history/reopen/refresh. Single UGC mug project19 passed. Eight widths verified. |
| Subscription / capacity / topup on FINAL SHA | Public Cukup, no private model/token/cost terminology. All three pack radios, native dialog Escape/close, pending Rp50k order4 reused. No activation before verified payment. |
| Exhausted state on FINAL SHA | Safe browser interception of public capacity GET only; Habis notice rendered and real normal Chat33 succeeded. This was a UI fixture, not mutation of production quota. Actual backend exhaustion covered by SQLite/native PostgreSQL tests. |
| Free Finance on FINAL SHA | Non-Pro CLIENT_OWNER opened owned business10/branch16: Home, accounts/balances, transactions, receivables/invoices, reports, operations/bills and budget. Retired assistant/analyst/operator/receipt/bank-import routes404. Finance provider ledger remained16 rows/maxid130 before and after QA. No finance entries or calculations changed. |
| Responsive UI on FINAL SHA | 12 pages ?320/360/390/430/768/1024/1440 =84 combinations, plus pack dialog checks. No horizontal overflow or JS errors. Video also checked820px. Width simulations, not physical-device keyboard testing; capability/focus behavior covered by browser automation. |

Final healthz returned200 with PostgreSQL backend. Reviewed22 unfiltered Hub/Cron application logs since final release: no ERROR/CRITICAL/Traceback/worker-timeout signature, no additional log page. Final closing error-level log query is recorded in the release report.

## Behavior and remaining limitations

- Private deterministic EASY/NORMAL use Luna low/medium; HARD/EXPERT use Sol low/medium. Output depth is independent; no model selector, classifier call or cost-dependent quality downgrade. Actual sources are counted without duplicating mirrored context; verification codes are not coding requests.
- Shared expensive-operation capacity uses the configured conversion of the internal35k/30-day allowance. Public states Cukup/Menipis/Habis; normal paid Chat and free Finance remain available when premium capacity is exhausted. Atomic forecasts, actual returned usage, billed failures and separately metered repairs are retained.
- Fixed capacity packs25k/50k/100k, verified90-day credits, renewal99k/30days kept separate. Legacy orders/credits remain intact; retained credits require active Pro for consumption.
- Server email QA allowlist bypasses commercial limits without bypassing authentication, isolation, approvals, technical bounds or rate/concurrency protections. Real non-Pro QA used premium operations successfully.
- Finance is free, with paid provider paths disabled and historical finance records unchanged. Deterministic ledger/business behavior is preserved.
- Manual bank transfer and authorized proof review remain the active payment adapter. Automatic payment gateway remains configuration/approval-dependent; no fake gateway or successful payment was claimed.
- Video had two initial503 attempts: draft validation rejected followed by bounded20-second repair timeout. The same project subsequently passed the complete multi-part/revision chain and single flow. These transient provider/repair limits remain possible; no Video Director/model/continuity redesign was introduced.
- Production billing approval, actual fund transfer and physical-device virtual keyboard were not exercised. Their applicable safeguards have focused automated coverage.

## Implementation and release history

# Kilas Intelligence, Premium Capacity and Free Finance

## Current checkpoint ? 2026-10-04

Implementation and release verification in progress on main, starting at `85b115b9e420584d129b33b34eb8bad92a67ffbb`. No task commit/push/deploy yet. Existing unrelated dirty documentation and no-content-change files are preserved and excluded from this release.

Implemented: deterministic private difficulty/depth router and compact playbooks; one targeted metered quality escalation; shared cost capacity using existing usage/topup tables and account locks; generous normal paid Chat without usage-dependent quality decay; server email QA allowlist without expiry; fixed 25k/50k/100k verified packs with 90-day new credits and historical credits/orders preserved; manual-transfer gateway adapter; subscription/native responsive capacity dialog and contextual notice; truly free deterministic Finance with every paid provider gate disabled and retired AI routes returning404. No schema/migration/new resource/production data reset.

Focused evidence so far: 23 existing AI/Video/connector unit modules plus routing/capacity tests passed in isolated subprocesses. Seven-width capacity browser passed at320/360/390/430/768/1024/1440, including native dialog Escape/focus return, 50k checkout without activation, exhausted premium while normal Chat works, refresh persistence and mobile blur. Composer focus regression passed Chat/Work streaming/DONE, manual touch, desktop focus and Stop at320/360/390/820/1440. New PostgreSQL concurrency/settlement CI coverage added; not run yet.

Remaining checks: focused matrix reruns after updating obsolete paid-quotas/beta/retired-AI expectations, Finance accounting/security regression, global four-language responsive and Video browser gates, new native PostgreSQL capacity gate, final diff review/CI, commit/push, deploy existing Hub and shared Automation Cron, authenticated real production QA and error logs. Windows fixture wrapper closes cached SQLite handles before reset, and PYTHONUTF8 avoids Windows-only source decoding issues; production code is not changed for these harness issues.

Impeccable scoped finish review: disposition `ship`; all14 subscription/dialog captures valid, no material fixes. Contextual notice/Finance wording reviewed in source only, rendered production verification still pending. Detector cannot resolve Jinja stylesheet URLs; its unstyled black-body/flat-type suggestions are contradicted by loaded browser captures. Pre-existing design sidecar/buildpath drift is reported, not repaired.

Production baseline remains Client Hub SHA `e020abe349e36a0439246a0003d6c15af4ffff44`, deploy `dep-db0g6jlg1s2s73dujhn0` previously LIVE. Controlled verification browser is authenticated; source /account confirmed after user's Ready. No new real provider quality/production capacity/Finance success claim until release QA actually executes.

## Final local release gate ? 2026-10-04

All27 focused AI/Video modules PASS:526 test executions including inherited repeats. Final expanded intelligence/capacity module has32 contracts (including disabled direct legacy Finance provider entrypoints, QA approval and billed failed planner/Search/image paths); final32-test run PASS. Separate Finance/localization modules PASS:45 Home,25 receivables/atomic ledger,16 UI/security,18 invoice editor,12 workspace corrections,10 integration,3 style loading,8 localization,4 AI/Finance baseline and9 Assist connections. Home needed a standalone repeat after the parallel runner's240s wall timeout; standalone45 tests PASS117.6s. No Finance calculation changes.

Browser gates:544 global page/language/width combinations PASS across id/en/es/zh and320/360/390/430/768/820/1024/1440; no overflow or JS errors. Connected Video eight widths/copy/revision/history/reload PASS. Windows PowerShell redirects Werkzeug stderr as NativeCommandError despite Python reaching its final PASS output; no product assertion failure. Seven-width capacity and Chat/Work capability focus gates passed separately.

Diff reviewed across70 intended release paths;0 credential-pattern matches, no migrations/schema files, no accounting/calculation/WhatsApp/Assist application changes. Existing dirty docs excluded. Both existing affected services have autoDeploy=no: Hub and shared Automation Cron must be explicitly deployed after CI. No new resources/config credentials/payment activation.

Impeccable documenter confirmed ordinary extension fits incumbent system; PRODUCT.md, DESIGN.md and design.json unchanged. Expired Pro wording subsequently made explicit via existing presentation: renewal99k/30 days is distinct from fixed capacity packs. Current active-state captures unchanged.

CI on7ca437a: unit/security/schema/Video/global UI gates passed. Browser checkout expected retired custom-amount field; corrected to choose fixed25k pack through dialog. New PostgreSQL normal-Chat fixture used Work identity; corrected to real agent-chat operation prefix. Local desktop/tablet/mobile legacy Chat/checkout browser rerun PASS. No application changes needed for these two test-contract corrections; all CI gates will rerun before deploy.

Native PostgreSQL gate then uncovered real psycopg2 placeholder handling in topup invoice-prefix LIKE. Fixed both current and preserved legacy checkout with bound pattern parameters; added native-PG pending-order reuse assertions. Focused32 intelligence/capacity and5 topup contracts rerun PASS. Release remains undeployed pending all required green CI.

Release8cb8ff192cc20c67ceb2c63f9be65a66f233d2df pushedmain. All5 triggered CI workflows PASS: Focused37142407492, Agent37142407479(includes nativePGcapacity/browser/sandbox), ChatQuality37142407460, Automation37142407481, GlobalUI37142407453(Finance/localization+544browsercombinations). Video code unchanged since Video37141461080 PASS. Authorized existing deployments started18:04UTC: Hubdep-db0k7e5g1s2s73eeucog; Crondep-db0k7fhsrm7s73fvcov0. WaitingLIVE and real authenticated synthetic QA; not yet claimed PASS. Pre-QA Finance provider ledger16rows/maxid130; controlled account has0AI subscription rows.

Both services LIVE on8cb8ff1: Hubfinished18:09:25UTC; Cron18:05:15UTC. Authenticated real production QA: Home/navigation/Services PASS; shortChat16words Luna, normal133words Luna, difficult805words Sol, correction378words/reload persistence PASS. Search prompt asking for tanggal pemeriksaan incorrectly entered Work schedule because future_requested matched bare tanggal. Root fixed to require concrete numeric date; focused unified22+WorkV2 22 PASS with regression Search/nojob and actual future schedule retained. Independent subscription/freeFinance QA progressing; account(noAI subscription) opened business10/branch16 successfully. No blanket production QA success claimed yet.

Production UI PASS:84page/width combinations(12pages×320/360/390/430/768/1024/1440), dialog/radios/Escape, pending50k topup#4(no proof/payment), FinanceAIroutes404, safe intercepted Habis UI plus real normalChat#23,0JSerrors. Finance provider ledger remains16/max130. Multi-file QA#24 found negated artifact clause misrouted to background document. Fixed only attachment reading dispatch: negated creation verbs no longer authorize artifact, reading/analysis stays Chat; positive document creation retains Work. Regression asserts real uploaded2file route/nojob, PDF/image reading, positive creation; unified23PASS.

Independent production image#25 PASS: generatedartifact15/job19(790232bytes), blue-referenceedit artifact16/job20(1034199bytes), distinctdownloads/reloadpersistence/0JSerrors. Video multi QA project18 initialattempt503: safe logs show invalid_video_part atdraftstage0 then bounded20srepair timeout stage1. Existing Video director unchanged; same preserved project18 now retried through normal UI. Do not label firstattemptPASS or claim blanket clean warning logs.

All5 required CI on finalcodec09526dea9ce7120f2908835b6d0c0429568ce6f PASS: Focused37143759534,ChatQuality37143759609,Automation37143759547,Agent37143759615,GlobalUI37143759591. Same synthetic Video18 retry now PASS mobilversion1(40.1s)→bajuversion2(35.4s), remaining food/PATCH/single checks running before instance replacement. Existing retry behavior succeeds; initial2boundedrepair failures remain recorded.

Production Video18 retry PASS: mobilv1,bajuv2,makananv3,premium/noVOv4; no stale retiredsubjects, exacthandoffs maintained, Englishpromptchecks,7clipboardactions,history/reopen/refresh,eightwidths320/360/390/430/768/820/1024/1440. SinglesyntheticUGCmug project19v1 PASS39.8s.0JSerrors. Finalcodec09526d deployed existingHubdep-db0kj7jncjis739u8pl0 andCrondep-db0kj8hsrm7s7380ptpg; waitingLIVE before Search/filefailedscenario rerun.

OnLIVEc09526d exactSearchrerun#26 PASSofficialpython.org/noWorkjob/0JSerrors; multifile#27 PASSverified30difference. PDF#28 failed quality guard: classifier counted same filename twice(persistent source plus current extracted block), and kode verifikasi looked like coding. Fixed intelligence only: unique source filenames, factual-code vocabulary excluded from coding domain. Added actual uploaded synthetic PDF shortfacts/nojob/norepair regression. Unified24 and intelligence/capacity33 PASS; depth/safety guard unchanged. Failed billed rows remain metered, no data cleanup.

Independent production#29 imageunderstanding PASSorange shape. Work#30 PDFcreate(job21/artifact17,42990bytes)→revision(job22/artifact18,43138bytes) PASScompleted/differentdownloads/reloadpersistence/0JSerrors. Downloadedbytes inspected withPdfReader: both1page; originalRencana QA Sintetis→Rencana QA Revisi, fourthcek kemasan stepadded, previoussynthetic2rowtable retained. No productionFinance data mutated.

Source accounting refined before release: take maximum per-filename occurrence count across mirrored context blocks, so2real files sharing a basename still count as2. Regression34intelligence/capacity+24unified PASS; no guards disabled. Awaiting final CI and final single-PDF production rerun.

Finalcode5f7e8bd860060544dc6aa494a6c579494bb2d8e9 pushedmain. All5requiredCI PASS: Focused37145214939,ChatQuality37145214941,Automation37145214950,Agent37145214920(nativePG/browser/sandbox),GlobalUI37145214965. Finaldeploys existingHubdep-db0ks8m0tbcc7389ocsg andCrondep-db0ksv3ncjis739ve3e0 started. ControlledQAconfirmedCLIENT_OWNER,0AI subscriptionrows. WaitingLIVE then exact file/PDF rerun and finalUI/logchecks.
