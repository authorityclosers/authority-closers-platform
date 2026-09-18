# v0.2 worktree disposition

Status: integration and review in progress; no worktree cleanup performed.

The read-only 2026-09-13 snapshot resolved 63 worktrees and 62 branch refs. Fifteen
were dirty and 1,198 untracked entries included generated files, private receipts
and media artifacts. The detailed path/commit/status inventory remains external:

- `D:/AC-authority-closers-release-audit/worktree-inventory-20260913.json`
  SHA-256 `e6dac4afefea8e043cdc461bd0cf0625acfc1d2bd26b67150c3f0befee847ceb`.
- `D:/AC-authority-closers-release-audit/worktree-inventory-20260913.md`
  SHA-256 `e2123a586828ae56fb9751041533b0d03bfbd7a64030401781d74c683802e5bf`.

New active integration worktrees are additional to that snapshot and must also be
preserved. No difference is considered missing solely from Git ancestry or a
patch-ID comparison; content and subsequent fixes determine integration status.

| Older lane | Content disposition in the v0.2 candidate |
| --- | --- |
| Coach staging `783da98` | Workspace and newer auth/video/session behavior present via `4a975bf` and `7dca8f4`; old tip superseded. |
| Local media `3eb24da` / `c25186a` | Superseded by filesystem activation, release wiring, disk quota and scanner isolation fixes `be702e2`, `8d47747`, `c0a2792`, `4fbbac8`, `aa2bfae`. |
| Community / Arcade `74631e0` / `4e8d413` | Identity and Arcade present via the integrated UI, followed by opt-in connections and recovery parity; older tips superseded. |
| Sales 0032 `33353bc` | Migration/recovery/backup content present via `8204cfe` and `6204dc4`; older evidence retained separately. |
| Sales child / Xray `63fcb31` / `8c180fb` | Child hardening and report behavior present via `ad0714d`, `ffc5a34`, `93df378` and the newer fixture isolation fixes. |
| Coach UUID `f1b901f` | Canonical UUID route handling already present. |
| Deterministic next action | Server-owned next activity and supporting evidence already present; dirty checkout retained. |
| Security next | Dirty Next/eslint 16.3.3, sharp 0.35.4 and lockfile changes already present in final content; preserve local trees until cleanup. |
| Detached `25ac` community | Superseded by current community/Alpha/connection implementation; retain dirty files and evidence. |
| Course source preparation `c8805a0` | Source superseded; supplemental operator documentation/helpers retained on their branch and in external packets. |
| Auth recovery, large media, filesystem activation, native import and CI follow-ons | Patch-equivalent or already applied in the core candidate; exact refs recorded in the full audit. |

Sales hosted/reviewer work, avatar correction and final release evidence are active
lanes. They require final reviewed commits and tests before the accepted source is
merged to `main`. The final tag and release notes must identify the actual accepted
commit, not a partially integrated snapshot.

After acceptance, remove only redundant worktrees whose source is integrated and
whose local artifacts are preserved. Unmerged unique work, runtime environments,
private media and receipts must not be deleted to make the workspace appear clean.
