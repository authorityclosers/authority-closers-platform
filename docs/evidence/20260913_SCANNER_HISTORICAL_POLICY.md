# Historical scanner policy compatibility

The pre-media scanner uses the exact `100M` / `100M` / `200M` stream, file and
scan limits. The first large-media change replaced those expected values in the
controller with the 2 GB policy. Because the transition controller validates
both its existing source and its rollback target, that replacement prevented
an upgrade from the healthy pre-media release and prevented rollback to it.

The validator now admits only the two complete known tuples:

| Policy                                           | Stream/file bytes |    Scan bytes |
| ------------------------------------------------ | ----------------: | ------------: |
| Historical `100M` / `100M` / `200M`              |       104,857,600 |   209,715,200 |
| Large `2000000000` / `2000000000` / `4000000000` |     2,000,000,000 | 4,000,000,000 |

Mixed tuples and other values fail before source replacement. The immutable
archive/controller checks, signature validation, named source/target identity,
Docker static bounds, and healthy/live upgrade preconditions remain in force.
Explicit rollback still admits an identified degraded source. The sole named
legacy healthcheck release still receives functional continuity only, not a new
readiness claim.

Readiness now uses the validated target's byte limits. Rolling back to a
healthy 100 MiB release cannot report 2 GB readiness. Large readiness additionally
requires the fixed-disk policy and its live mount proof, so an intermediate
large-policy artifact without that storage boundary cannot claim 2 GB capacity.

Focused fixtures exercise both transition directions through the real policy
validator and readiness builder, reject each mixed source limit, and refuse
large readiness without fixed disk. Docker, Linux loop mounts, real ClamAV and
production transitions were not executed by these fixtures. The focused scanner
controller suite passed **97 tests**; Ruff lint and formatting passed for both
changed Python files. Exact artifact and deployment proofs remain required.
