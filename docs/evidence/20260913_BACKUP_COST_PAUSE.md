# Backup cost admission and temporary remote pause

The user accepted a temporary pause in remote backup and remote restore verification
to preserve the existing R2 cost ceiling while the current application ships. This
pause and the associated remote recovery-point objective gap are visible operational
conditions; they do not block the application launch under that acceptance.

The existing `R2_MAX_CLASS_A_MONTH=700000` and `R2_MAX_CLASS_B_MONTH=7000000`
policy values are unchanged. Operation admission now closes when observed usage
equals either cutoff, as well as when it exceeds the cutoff. Existing headroom
below the provider free allowance is retained. Foundation restore
verification now calls the installed `/usr/local/libexec/authority-closers/r2-usage-guard`
after acquiring the canonical Restic repository lock on descriptor 9 and before its
first `restic snapshots` call. If admission fails, it performs no Restic calls, exits
nonzero and emits only `AC_BACKUP_FAILURE=r2_quota_paused`. Guard stdout and stderr
are suppressed. The service failure remains visible; a paused check is not a
successful backup, restore verification or remote RPO proof.

This is an admission cutoff based on usage observed through the existing guard.
It is not a provider-enforced billing guarantee: reported usage can lag and other
consumers can use the account. No cost cap, cache or retention policy is changed.
Local backup evidence does not establish independent remote backup success.

Validation uses a copied source block with synthetic guard and Restic functions
and a temporary lock. It checks that the guard executes under the lock, rejection
makes zero Restic calls and produces the fixed diagnostic, and admission reaches
the unchanged tagged snapshot command. A source invariant also preserves the
restore and integrity-check commands and the 7,000,000 Class B cutoff. These
fixtures do not contact R2, run Restic, access a live lock or use credentials.
Evaluator fixtures cover cutoff minus one (admitted), exact cutoff (rejected), and
cutoff plus one (rejected) for both operation classes. The storage bound is unchanged.

Local validation on 2026-09-13:

- Focused pytest: **4 passed**, covering the source invariant, shared repository
  lock invariant, and both executable admission branches through Git Bash.
- Exact evaluator decimal functions and cutoff block executed through Git Bash:
  **6 passed**, covering Class A/B at cutoff minus one, cutoff, and cutoff plus one.
- Ruff checks and formatting, Bash syntax, and scoped `git diff --check`: passed.
- The full evaluator fixture suite could not run because Git Bash has no `jq`.
  The six arithmetic checks do not claim to cover JSON parsing.
- The real POSIX lock fixture could not run because the configured Ubuntu WSL
  disk is missing. Its lock proof remains for POSIX CI; local admission execution
  proves the guard branch and first-read ordering, not kernel flock behavior.

This record documents the source change and accepted pause. It does not claim a
deployment, a successful remote restore, or provider billing enforcement.
