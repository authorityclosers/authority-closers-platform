# Alpha foundation → Practice Arcade release sequence

Date: 2026-09-07. Status: active implementation direction; **not released or accepted**.
Extends the [Alpha acceptance contract](alpha-acceptance-contract-2026-09-07.md)
and its existing active goal. No unfinished v0.1 requirement is removed by naming
the next feature release v0.2. Source intake:
[Practice Arcade package evidence](../../../evidence/20260907_PRACTICE_ARCADE_HANDOFF_INTAKE.md).

## Current truth

Staging's last verified application is `a5eef0df4b340070ac6e58f9912d73a3bf1d2f18`.
Its settled learner captures still show unavailable video. The two licensed
technical film excerpts are installed inertly on the VPS; media policy is OFF.
Authorized publication, binding/enrollment and real playback remain incomplete.
Production has not received this Alpha overhaul. PR43 is an inactive permissions
checkpoint, not a video or Platform Console release. Localhost learner/admin
connectivity was verified on ports 3100/3101 during this intake.

## Delivery order and concrete exit conditions

| Order | Slice                                         | Required release evidence                                                                                                                                                                                                                                                                                                      |
| ----- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1     | Working video + coherent course workspace     | Normal learner authentication; canonical published technical course/binding/enrollment; actual VPS playback, seek/resume, speed, volume, captions, fullscreen, rendition/range delivery and failure recovery; expired/revoked/cross-tenant denial. Preserve Dipak instructional versions and distinguish technical footage.    |
| 2     | Academy Studio and Platform Console parity    | Named, persisted platform access for the approved administrator accounts; tenant/program content/coaching for Dipak; no learner-role replacement. Working content/version, image placement, lesson/exercise editing, preview, review/publication and useful work queues, using the same quality standard as learner UI.        |
| 3     | Practice Arcade foundation                    | Versioned authored sets, server-issued attempts, validated answers, specific authored feedback and save/retry/resume. Start with matching, word-bank gaps and next-move choices, then assembly, ordering, listening and branching. A complete authorized set works across refresh and retry; keyboard/touch alternatives pass. |
| 4     | Identity, personal progress and rhythm        | Persisted photo/handle, academy-scoped opt-in identity and privacy controls; personal practice history; declared qualifying-day/timezone and XP policies; no duplicate recognition and no telemetry-derived progress.                                                                                                          |
| 5     | Earned-only cosmetics                         | Approved reward/price policy, append-only credit journal, transactional redemption/entitlement, exact retry and compensation. PostgreSQL concurrent-spend and duplicate-reward tests pass; balance and history reconcile.                                                                                                      |
| 6     | Cooperative social pilot, then bounded league | Invitation/privacy/report/block/moderation and roster rules first; personal bests and cooperative squads before a ranked event. Ranking requires approved eligible items, equal free opportunities, explicit ties/finalization/disputes and tenant-negative tests.                                                             |

Each row may ship in smaller coherent releases. Backend prerequisites for video
can precede its UI cutover; continued UI work stays in the same implementation
worktree. Do not launch every Arcade surface merely because the prototype has a
navigation link. Checkpoints are private formative feedback; formal exams,
validated scoring/certification, purchased credits and real-money operations
retain separate existing approval gates. AI-on-VPS research remains idle.

## Reuse and improvement decisions

- Keep current company/tenant/platform branding and shared BrandMark. The ZIP's
  AC text specimen is not an approved replacement logo or a platform rename.
- Reuse suitable exercise controls, feedback patterns, symbols, static artwork
  and optional motion/audio; adapt to existing components instead of importing
  an independent shell, theme, identity, backend or local-wallet authority.
- Prefer compact static derivatives; load 3D/video assets only when useful and
  after performance/accessibility verification, never on every lesson request.
- Keep one restrained Arcade entry. Its library and richer social/economy
  structure belong inside Arcade, not eight new permanent app-navigation items.
- Preserve the prototype's focused question/feedback composition. Improve its
  very tall mobile introduction so a useful action arrives sooner, and replace
  prototype-only diagnostic labels with clear production states, not false success.
- Course progress, participation XP, event points and spendable credits are
  separate canonical concepts. Spending never completes coursework, improves an
  assessment or buys ranking advantages. The credit ledger is not ERP accounting.

## Decisions not supplied by visual approval

The handoff explicitly calls its numeric reward prices, qualifying-day/grace
rules, handle grammar/cooldowns, squad size/contribution formula and event
attempt/scoring policy **candidates**. Record controlled, versioned product
decisions before activation. Its 24 teaching items need Dipak's review; none is
currently eligible for ranked competition or formal assessment. No arbitrary
pass marks, official AI scoring, reward grants or wallet seed balances are
authorized by a ZIP's examples or code.

## Shared quality and release metrics

Apply existing A01–A16 to learner, Studio and Platform Console, not only Home:
zero open Critical/Important defects; no overflow or inaccessible primary action
at 320/390/768/1440 px plus breakpoint-specific cases; light/dark, keyboard,
reduced motion, loading/empty/error/expired-session/retry/conflict checks.
Production-build targets remain LCP ≤2.5 s, CLS ≤0.1 and INP ≤200 ms where measured;
lab evidence is not field-percentile proof. Do not claim superiority to Apple,
Netflix, YouTube or another product without a defined comparative evaluation.

Every published slice requires exact SHA/artifact, authenticated live behavior,
backup/restore and rollback compatibility, before/after desktop/mobile captures
and verified Drive filing. Prototype screenshots and package test reports are
source material, not acceptance of our deployed apps. No completion percentage
is reported until the journey/action/state denominator is established.
