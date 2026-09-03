# Decision log

| ID | Decision | Status | Basis | Follow-up |
| --- | --- | --- | --- | --- |
| `DEC-LL-001` | Keep the module roadmap and current activity in one learning loop | accepted for this package | controlled JRN-03/IA and learner-core behavior | implementation must consume canonical projection, not stage labels |
| `DEC-LL-002` | Use provider-neutral media capability gates | accepted boundary | AC-IMP controls, `ACT-01`, and media gap `GAP-MEDIA-001` | promote playback/session/provenance contract before activation |
| `DEC-LL-003` | Treat captions and transcript as separate conditional content facts | accepted boundary | HTML track behavior plus controlled media gap | verify approved source, locale, timing, privacy, and retention |
| `DEC-LL-004` | Keep speed/fullscreen/PiP presentation-only and feature-detected | accepted boundary | Apple/MDN platform evidence | test desktop Chrome, iOS Safari/Home Screen, and Android PWA |
| `DEC-LL-005` | Use authored deterministic knowledge checks and quiz/test | accepted for a bounded design | existing interaction-schema proposal; no AI scoring authority | promote schema and exact submission/feedback contract |
| `DEC-LL-006` | Do not render autonomous AI scoring, mastery, rank, reward, or competency certification | locked guardrail | AGENTS.md and AC-SVAL boundary | AC-SVAL is required before any official scoring/evaluation work |
| `DEC-LL-007` | Human review is gated by explicit assignment and append-only provenance | accepted boundary | `SF-EVIDENCE-001`, security/authz controls | prove reviewer role, visibility, correction, and privacy behavior |
| `DEC-LL-008` | Offline can recover approved local text/read cache but cannot write canonical learning state | locked guardrail | local draft recovery contract and JRN-05 | verify purge, expiry, reconnect reconciliation, and no hidden submit |
| `DEC-LL-009` | Select Direction B — Momentum Workshop | selected reference | independent artifact selection and strongest cross-breakpoint task continuity | use as visual grammar only; do not treat PNG copy as seed content |
| `DEC-LL-010` | Retain Directions A and C as bounded references; do not blend a fourth direction | accepted | exactly-three-direction requirement and traceability | any change requires a new comparison and supersession record |
| `DEC-LL-011` | PWA standalone/install is a browser presentation, not a native app | locked guardrail | Mobile/PWA controlled source and platform guidance | real-device install/update/background evidence remains open |
| `DEC-LL-012` | No external provider, real call, Drive/Notion/Figma/Canva/Lucid artifact, or production mutation is performed | locked for this docs-only task | explicit user scope and AGENTS.md | use local docs/PlantUML fallback and report connector gap |

## Supersession notes

- Direction C's generated duration, transcript excerpt, notification utility,
  and completion wording are reference artifacts only; the behavioral contract
  supersedes them until each source is approved.
- Direction A's transcript/Watch-complete fixture is conditional and cannot
  override `blocked_media` or `captions_unavailable` states.
- This package does not alter the neighboring `learner-product-v1` or
  `06-screen-family-v0.1-alpha` files. Any future merge should preserve these
  IDs and avoid silently replacing audit-critical history.
