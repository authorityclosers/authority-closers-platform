# Sales Xray AI approval: owner limits (28 Sep 2026)

## Owner decision (recorded in the working session)
- No automatic deletion of recordings; keep them to train and improve AC's coaching AI.
- Staging volume of about 10 calls a day, sometimes more; production volumes later.
- Spend cap derived from real cost. The staging cap is INR 10,000 for now, raised later from
  Admin.
- Testers: suyash@, dipak@ and admin@, plus a simple way to add more by any email (Admin, follow-up).
- Providers swappable, with cost calculated per model (Admin, follow-up).

## What changed in code
| Limit | Before | After |
|---|---|---|
| Approval `retention_days` | 1–7 | 1–3650; **above 7 only with a `ref:retention/sales-xray-keep-for-training…` policy** |
| Intake retention | 1–7 | 1–3650, same keep-for-training rule |
| Allowance and acquisition `max_recordings` | 64 | 10,000 |
| Allowance and acquisition stored bytes | 8 GiB | 32 GiB (the bundle-level cap) |
| Admin budget ceiling | INR 10,000 | INR 1,00,000. The approved cap still decides spend |

## Consent and disclosure
- Standard policies are unchanged: same text and same privacy revision
  (`local-private-audio-v1`), so existing consents and hashes stay valid.
- Keep-for-training policies show different text ("kept privately to improve AC's coaching AI
  until you delete them") and record their own privacy revision
  (`local-private-audio-keep-for-training-v1`) with every consent.
- Users can still delete their own recordings in every mode. Only **automatic** deletion
  stops.
- **Production is not approved by this change.** Keeping real customers' recordings (which
  include prospects' voices and details) for training needs an explicit opt-in at upload, an
  updated privacy policy and a withdrawal path. The owner (ideally with legal advice) must
  approve that wording before any production keep-for-training policy is issued
  (AC-GOV-AUD-001).

## Checks
- New tests:
  - keep-for-training rule, 3650-day bound, recording ceiling, standard wording and revision
    unchanged, keep-for-training wording and revision;
  - web parses retention up to 3650 days and rejects 3651.
- Related unit suites (budget, activation, intake, acquisition policy): 195 passed locally.
- The full suite runs in CI.
