# Production Admin metrics release (AUT-2122)

This change adds the numbers-only metrics store to the production API through
the normal application release. Staging, dev, workers, migrators and web
containers receive no production metrics mount or environment variable.

## Source and approval

- Observed baseline from AUT-2121: core/web
  `7efd9c7439ca5e6fea05b43d075071fa73c506a2` (v0.64.0); installed engine
  `bc49a3dddaabede246b008c151f6779a2f6a377c`.
- The workbench commit and its file hashes are recorded in AUT-2122's evidence.
  This is an implementation candidate until the CTO reviews that SHA and the
  release orderer records the selected, CI-green main release SHA.
- `metrics_release` below is that approved **release** SHA, not an arbitrary
  workbench HEAD. The release orderer must include the new compose file and
  installer selection together. Unrelated workbench changes need their own
  release authorization.
- Record the previous core/web pair, migration head, engine SHA and collector
  file hashes before rollout. A core rollback requires the same migration head;
  these metrics changes add no migration. A combined release with a migration
  needs its own approved recovery plan before production.

## Application rollout and rollback

Commands below are for the authorized release operator. Builders do not run
them. A release is required: the v0.64.0 archive has no metrics override input.
There is no supported metrics-only container reconfiguration in that engine.

```bash
# Set only from the CTO/release-orderer receipt for this change.
metrics_release=<approved-40-character-main-release-sha>
# Root's existing operator checkout must be clean at that exact approved pin.
reviewed_checkout=<existing-operator-checkout-at-that-sha>
test "$(git -C "$reviewed_checkout" rev-parse HEAD)" = "$metrics_release"
test -z "$(git -C "$reviewed_checkout" status --porcelain -- infra/release infra/application)"
# Supported engine installer: pins its rollback controller to the reviewed SHA.
bash "$reviewed_checkout/infra/release/install-release-engine.sh"
ac-release deploy staging "$metrics_release" --component core --dry-run
ac-release deploy staging "$metrics_release" --component core
ac-release deploy production "$metrics_release" --component core --dry-run
ac-release deploy production "$metrics_release" --component core
```

These are existing engine commands, with staging-before-production admission,
verified archives/images, health checks and automatic failure rollback. The
orderer can instead include this core in the normal `ac-ship` release pair.
Record the resulting version and actual core/web pins on AUT-2122 before its
release handoff is complete; the dry run alone is not deployment evidence.

Before an application-only rollback, verify that the production release
history's previous core is the recorded rollback target and both migration
heads match. The supported inverse is:

```bash
ac-release rollback production --component core
```

For a normal paired ship, use its paired inverse after its plan is checked:

```bash
ac-release rollback production --dry-run
ac-release rollback production
```

`compose_for()` resolves the **target** archive on every call. A target without
`compose.production-metrics.yaml` receives no mount/env, even when the failed
current release has one; a target that carries it retains it. No immutable
deployed files need edits. Explicit core rollback uses the installed engine's
controller, so the release orderer must verify that its reviewed engine pin
also contains this installer change before using that inverse. Normal forward
failure rollback already uses the new release's installer. Do not assume that
the old installed engine learns the new selection without the supported engine
install above. Auto-update compares only the `infra/release` tree, so an
application-only installer change does not by itself trigger an engine update.
The engine source delta must be included in the release-orderer's review; the
baseline installed engine is older than the current workbench engine source.

## Durable collector selection, separate from installing metrics code

The existing host has a five-minute timer, a budget-alert `ExecStartPost` hook
and newer collector SQL. Its old `SOURCE_SHA` is not an exact source receipt:
`infra/metrics/install.sh` writes checkout HEAD even if installed files were
uncommitted. Do **not** rerun the v0.64.0 installer: it would overwrite those
newer files. Do not run a workbench installer to import unrelated alert code.

The new application archive includes `scripts/configure-metrics-collection.sh`.
It only writes this persistent systemd drop-in and reloads systemd:

```ini
# /etc/systemd/system/ac-metrics-collect.service.d/80-collection-policy.conf
[Service]
Environment="AC_METRICS_ENVIRONMENTS=development staging production"
ExecStartPost=
```

The empty `ExecStartPost` explicitly **holds post-export alerts** while keeping
their installed script and base service bytes intact. Production collection
does not authorize activating Pulse/Telegram alerts. Timer cadence, SQL,
collector, alert script and source receipt are not changed. Alert source,
review and activation belong to a separate release decision; removing this
reset requires that decision, not another collector install.

After the reviewed application release, Root uses its immutable source:

```bash
policy=/srv/authority-closers/application/releases/$metrics_release/scripts/configure-metrics-collection.sh
bash "$policy" --environments 'development staging production'
bash "$policy" --apply --environments 'development staging production'
systemctl show ac-metrics-collect.service -p Environment -p ExecStartPost
systemctl show ac-metrics-collect.timer -p TimersCalendar -p NextElapseUSecRealtime
# Only after the effective policy shows all three environments and NO post hook:
systemctl start ac-metrics-collect.service
```

The script does not start/restart a unit or enable a timer. The existing active
five-minute timer takes the new selection on its next run. Root first retains
the existing drop-ins/effective settings and installed file hashes, and confirms
the installed read-only SQL works with the released schema. If its source is
not approved or compatible, stop collection activation and use the exact
released SQL/collector path already proved in AUT-2121 until its own source
release is approved. Do not overwrite the newer installed files to solve that.

Collector rollback (retains the alert hold and all installed files):

```bash
bash "$policy" --apply --environments 'development staging'
```

This stops future production collection. It does not delete existing exports
or reinstate unreviewed alerts. Restore a prior drop-in only from the operator's
recorded backup and only if its alert behavior is approved. A later normal
metrics install replaces base unit files but leaves this drop-in, its production
selection and its alert hold intact; the fictional installer regression checks
that behavior.

## Operator acceptance

1. Production API has exactly the metrics bind mount, `RW=false`, and
   `AC_METRICS_STORE_ROOT=/srv/authority-closers/metrics`. The bind cannot create
   a missing host directory; AUT-2121 has already created and validated it.
2. Staging/dev APIs, workers, migrators and web containers have no production
   mount or metrics variable from this release. Dev's existing systemd binding
   remains limited to development/staging under its masked host root.
3. Collector/service/timer/alert/SQL file hashes match the pre-change receipts;
   effective collection covers all three environments, timer remains five
   minutes, effective `ExecStartPost` is empty.
4. All three exports are fresh and parse in the production API. Admin → Usage &
   cost lists their environment labels/timestamps for an authorized operator.
   Do not print usage rows or customer content into the receipt.
5. Retain rollout/rollback plans, source/release/engine pins, source hashes and
   content-free readbacks on AUT-2121/AUT-2122. Local compose rendering and
   fictional policy tests are implementation evidence, not live UI acceptance.

## Focused verification

```bash
uv run pytest -q tests/infra/test_production_metrics_release.py tests/infra/test_metrics_collection_policy.py
```

These tests render actual Compose configuration with fictional values, prove
production API-only read-only access and target-policy rollback in both
directions, reject a symlink policy, apply collection changes on a fictional
host without touching installed files or running hooks, and rerun the real
metrics installer against fictional files to prove policy persistence.
