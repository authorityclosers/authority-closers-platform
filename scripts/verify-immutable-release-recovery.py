"""Static guard for the package-only immutable release recovery job."""
from __future__ import annotations

import re
import sys
from pathlib import Path


RELEASE = "0847db5d3ca1ed825b68c226713d0f52d11683b1"
RUN = "34817997207"
REGISTRY_REFS = {
    "api": "ghcr.io/authorityclosers/authority-closers-api@sha256:5e9326288e109e04880cb72cfe22ee22159fc8b602d1c458c16cfa8309da2bbf",
    "learner": "ghcr.io/authorityclosers/authority-closers-learner-web@sha256:12be7777f4ce46d09e411ef14603628e08a1831974c2a61c43f5d85eb744a9af",
    "admin": "ghcr.io/authorityclosers/authority-closers-admin-web@sha256:d52c2f5fa7ada872575d8cfba94d6196b43ed998ba307b643578be5643b989fc",
    "coach": "ghcr.io/authorityclosers/authority-closers-coach-web@sha256:56fce8247ace1648975d711e92248b7bb5af7b758c7964284ea92689819cf9ef",
}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SystemExit(reason)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(".github/workflows/application.yml")
    text = path.read_text(encoding="utf-8")
    require("recover_immutable_release:" in text, "recovery_dispatch_input_missing")
    require("recover-existing-immutable-release:" in text, "recovery_job_missing")
    recovery = text.split("  recover-existing-immutable-release:", 1)[1]
    require("packages: read" in recovery, "packages_read_permission_missing")
    require("actions: write" in recovery and "contents: read" in recovery, "recovery_permissions_missing")
    require(f"RELEASE_SHA: {RELEASE}" in recovery, "release_binding_missing")
    require(f'ORIGINAL_RUN_ID: "{RUN}"' in recovery, "original_run_binding_missing")
    for key, ref in REGISTRY_REFS.items():
        require(ref in recovery, f"{key}_registry_digest_binding_missing")
        require(re.fullmatch(r"ghcr\.io/authorityclosers/[a-z0-9-]+@sha256:[0-9a-f]{64}", ref), f"{key}_registry_digest_shape_invalid")
    require("actions/runs/${ORIGINAL_RUN_ID}/attempts/1" in recovery, "original_attempt_check_missing")
    require('"Publish immutable SHA tags"' in recovery, "publication_step_check_missing")
    require('"Create transport archives and reviewed manifest"' in recovery, "transport_step_check_missing")
    require('"Admit release artifact under the pooled ceiling"' in recovery, "admission_failure_check_missing")
    require("docker pull \"$ref\"" in recovery, "digest_pull_missing")
    require("docker save --output" in recovery, "transport_save_missing")
    require("prepare-release-inputs.py verify-bundle" in recovery, "bundle_verifier_missing")
    require("verify-release-archive.py" in recovery, "source_archive_verifier_missing")
    require("actions/upload-artifact" in recovery and "retention-days: 1" in recovery, "one_day_artifact_missing")
    require("docker build" not in recovery and "docker push" not in recovery and "build-push-action" not in recovery, "recovery_must_not_build_or_push")
    require("registry_ref" not in text.split("workflow_dispatch:", 1)[1].split("jobs:", 1)[0], "registry_ref_must_not_be_dispatch_input")
    print(f"immutable recovery workflow validated: release={RELEASE} original_run={RUN}")


if __name__ == "__main__":
    main()
