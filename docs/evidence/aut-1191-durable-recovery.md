# AUT-1191 stopped-run recovery evidence

Owning source: `authorityclosers/paperclip`.

Saved implementation: `2701aed7ccc8dff9a54a79ae96da16fabfa87e8c`
(`aut-1191-durable-recovery`), based on
`25df4b1a6001774a3866092bfef4e698585f628a`.
Root's verified deployed server baseline is
`d554c4789ed3930f8a53ac9fdf6503b3187097da` (AUT-1217).

On 2026-10-05 the latest gate admitted `task/devenv/1191-durable-recovery`.
The source checkout is clean on AUT-862's branch. This run verifies the saved
commit in a run-owned source export, with workspace dependencies mapped to the
export, without switching or editing that concurrent checkout.

The saved change targets exact-identity replacement holds and supersession of
older automatic dispatch holds by a later verified reconciliation receipt.
Fictional regression coverage includes mixed stopped-run outcomes, a released
lease, preserved original owner/checkpoint, one continuation, repeat reads and
requests, and negative identity/provider/lease/successor cases.

Final verification is in progress. No passing final suite, reviewed PR, merge
or deployed repair is claimed here yet. No real recovery request, lease cleanup,
host operation or production data change is authorized by this evidence.

Delivery remains CTO review, CEO approval at the exact source head, approved
merge, then Root's pinned install/rollback and deployed read-back. Root retains
AUT-1269 verification of the reported AUT-1266 and AUT-982 replacement cases.
