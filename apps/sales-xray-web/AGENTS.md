# UI studio work preservation

These rules apply to every agent and lane script operating in the UI checkout
(`/home/acdev/src/lanes/ui/authority-closers-platform`), including operations
started from the repository root.

- Never run `git stash` (including `pop`, `drop` or `clear`), `git reset --hard`,
  `git checkout -- .`, `git restore` to discard work, or `git clean` in the UI
  checkout. Uncommitted studio files may belong to another active task.
- Before any branch switch, creation, deletion or integration operation, the
  Lead Engineer must coordinate file ownership, checkpoint the current studio
  work in a commit on its existing task branch, and push that checkpoint. If
  the checkpoint cannot be made safely, stop and report the blocker; do not
  clear the working tree to satisfy the lane gate.
- Run the repository lane gate before continuing. A checkpoint is preservation,
  not approval to ship or permission to bypass a busy gate.
- UI Maker edits only the assigned screen files. Lead Engineer owns checkpoints
  and coordinates concurrent edits; never stage another task's later edits
  without an explicit handoff.
- If work disappears, stop mutations and report the branch, time and affected
  paths. Preserve recovery refs and audit history. Do not drop a rescue branch
  or stash after restoring it.

Recovery reference: AUT-189; restored studio checkpoint `32b32dd` on
`task/ui/66-shell`. Validation belongs to the delivery task before shipping.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
