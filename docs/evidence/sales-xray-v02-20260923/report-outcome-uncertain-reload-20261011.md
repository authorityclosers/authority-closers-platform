# AUT-1677: reload before another unconfirmed outcome write

Source `f53a3bf`, following the bounded human-outcome client/command work.
The existing prepared editor offered Try again after any rejected callback
and continued showing the previous Unrecorded/recorded value. A rejected
acknowledgement cannot establish that a human write failed.

The editor now shows Unconfirmed, retains the person's unsaved inputs and
disables every write control after a rejected save. Its corner card offers
one explicit Reload. A scoped reload port must update canonical value,
capability and expected revisions before resolving; without that port the
explicit action reloads the page. A failed reload retains Unconfirmed and
cannot replay the write. Local validation failures still allow a retry
because no command was sent. Account/call scope changes retain the existing
draft-discard boundary. No outcome API, storage or manager grant is mounted.

Ten focused editor cases pass, including lost acknowledgement followed by a
recorded Won read without replay, failed read, duplicate reload protection,
stale-value hiding and retained date/value/scope behavior. The adjacent
client/value/editor run passed 110 cases before the final page-reload case;
incremental typecheck, cached changed-file ESLint, Prettier, browser Ruff/format
and diff checks pass before commit. The populated input browser check now
requires Unconfirmed, disabled writes and a successful explicit reload at
touch 390/1440 light/dark. Committed shared-dev screenshots and source receipt
are recorded in strike NOTES after the refresh; no production claim.
