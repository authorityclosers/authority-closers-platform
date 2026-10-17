# Keep Sales Xray uploads until deleted (owner decision, 18 Oct 2026)

## Why
- Production's sealed approval gives every upload seven-day retention (`ref:retention/sales-xray-seven-days-v1`). The permission's `retention_until` is upload time + 7 days.
- After that deadline the call drops out of its owner's Calls list and its owner checks refuse it. The retention step then erases it.
- Production audit shows 39 calls erased this way between 21 Sep and 15 Oct.
- A restored copy of the 17 Oct 19:02Z snapshot had 62 live calls already past the deadline, 59 of them with reports. They were hidden and waiting to be erased.

## Owner decision
"keep until deleted, delete on request, fix the 7-day text next release" (18 Oct 2026, relayed by Orchestrator 2).

## What the script does
- **Selects** every unrevoked permission of a recording that is not `deleting` or `deleted`, and sets its `retention_until` to upload time + 3650 days (the keep-until-deleted bound, ref `sales-xray-until-deleted-v1`).
- **Leaves alone:**
  - recordings already being erased or deleted;
  - permissions whose deadline is already that far out.
- **Idempotent:** a second run plans nothing.
- **One transaction.** It locks the permission rows it changes.
- **Audit:** `conversation.retention_extended` events (system actor) per tenant, in chunks of 50. Each names the approver, the issue, the snapshot digest, and every permission's old and new deadline, so the original seven-day deadlines stay on record.
- **Dry run by default:** reads only and prints counts per tenant, including how many hidden calls it makes visible again.
- **No customer data in the output:** counts and tenant ids only.

## Rehearsal (17 Oct 2026, restored production copy, scratch DB on acdev-test-postgres)
| Step | Result |
|---|---|
| Dry run | 446 to extend (3 tenants: 1, 360, 85), 62 hidden now, 41 skipped (deleting or deleted) |
| Apply | 446 extended, 62 restored, 11 audit events covering 446 permissions |
| Read back | 0 to extend, 446 kept, 0 live recordings past their deadline |

## Run
1. Approval: the owner writes "approve data change: extend Sales Xray upload retention to until-deleted (10 years) for all non-deleted production uploads, production".
2. **Dry run,** inside the production worker container (it reads the worker's own URL file; no credentials are printed):
   `sudo docker exec -i ac-application-production-sales-xray-worker-1 python - --database-url-file /run/ac-sales-xray/database-url --environment production --approver "<owner words, where, when>" --issue "<ref>" < scripts/data-changes/extend-sales-xray-retention.py`
3. Show the owner the dry run.
4. **Snapshot:** `sudo /usr/local/sbin/ac-db-snapshot production before-retention-until-deleted`. Then run the same command with `--apply --production-snapshot-sha256 <snapshot sha256>`.
5. **Read back** with the dry run again: it must plan 0. Post before/after, run time and approver on the issue.
6. Never during a release. One operator at a time.

## What still has to follow
- **New uploads** still get seven days until the code release with a keep-until-deleted retention mode ships and Root reseals the production approval with `ref:retention/sales-xray-until-deleted-v1`. Re-run this script until then; it only touches uploads that still have short deadlines.
- **Upload terms:** fix the "up to 7 days" wording in the same release that changes new uploads.
- **Lost calls:** the 39 calls erased before this change can't be brought back from database snapshots alone, because their audio was deleted from storage.
