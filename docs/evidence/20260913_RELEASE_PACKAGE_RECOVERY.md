# Release package recovery registration

This default-branch registration exposes the reviewed package-only recovery workflow so GitHub can dispatch it. The workflow bytes are copied exactly from recovery commit `9a21c3a2ea601b33b0709fd43f28c246b656574c` (`9a21c3a2ea601b33b0709fd43f28c246b656574c`). It accepts only the exact release SHA, a completed successful validation/capacity run for that SHA, and the four recorded immutable OCI registry digests; it does not build or retag images.

The deployment controller accepts the resulting artifact only with `-RecoveryWorkflowSha 9a21c3a2ea601b33b0709fd43f28c246b656574c`, after verifying the recovery run path, exact workflow commit, artifact release ID, and normal archive/image checks.

Validation evidence on the recovery source: 21 focused infra/controller tests passed; Ruff, YAML parsing, and PowerShell parsing passed.
