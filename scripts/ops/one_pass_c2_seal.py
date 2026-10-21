"""Seal Gemini 3.1 Flash-Lite as an approved C2 route, keeping every classic route.

Root runs this on the host with the environment's two current files (``--flex`` for the
Flex configuration, a second profile beside the standard one; ``--one-pass`` for the
configuration whose facts route is the one-pass C4 request) (owner, 21 Oct 2026:
"So at least get this on prod now!!!"; docs/ops/ONE-PASS-PRODUCTION.md):

    python scripts/ops/one_pass_c2_seal.py \\
        --bundle /path/to/the/current/hosted-approval.json \\
        --configuration gemini-c2-configuration.json \\
        --classic classic-configuration.json \\
        --out /root/one-pass-c2-seal

- ``--classic``: the active provider configuration (the ``configuration`` column of the
  active ``conversation_provider_configurations`` row; Admin → One pass shows its revision);
- ``--configuration``: the Gemini C2 configuration Admin → One pass → Prepare saved (the
  same row's column for that revision). It must equal what this script derives from
  ``--classic``, so nothing else can be slipped into the seal.

Writes ``hosted-approval.json`` (canonical bytes) and ``hosted-approval.sha256`` to
``--out`` and prints a content-free summary: the old and new digests, the profile added
per acquisition policy, and that every classic stage is byte-identical. Nothing is
installed: putting the file and its digest into the release metadata stays Root's step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ac_platform.conversation_intelligence.activation_contract import load_hosted_approval_bundle
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
from ac_platform.one_pass import c2_route


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="one_pass_c2_seal")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--classic", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--flex",
        action="store_true",
        help="seal the Flex configuration (C2, C4 and C5 on Gemini Flex) instead",
    )
    parser.add_argument(
        "--one-pass",
        action="store_true",
        help="seal the one-pass configuration (C4 as one request over the whole call)",
    )
    arguments = parser.parse_args(argv)
    bundle = load_hosted_approval_bundle(arguments.bundle.read_bytes())
    classic = parse_registry_config(json.loads(arguments.classic.read_text()))
    saved = parse_registry_config(json.loads(arguments.configuration.read_text()))
    derived = c2_route.derive_configuration(
        classic, flex=arguments.flex, one_pass=arguments.one_pass
    )
    if saved.digest != derived.digest:
        print(
            json.dumps({"refused": "configuration_is_not_the_derived_one", "saved": saved.digest}),
            file=sys.stderr,
        )
        return 2
    sealed = c2_route.seal(
        bundle, classic, derived, flex=arguments.flex, one_pass=arguments.one_pass
    )
    arguments.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (arguments.out / "hosted-approval.json").write_bytes(sealed.to_json())
    (arguments.out / "hosted-approval.sha256").write_text(sealed.digest + "\n")
    policies = (
        *(() if sealed.acquisition_policy is None else (sealed.acquisition_policy,)),
        *sealed.organisation_acquisition_policies,
    )
    print(
        json.dumps(
            {
                "environment": sealed.environment,
                "bundle_before": bundle.digest,
                "bundle_after": sealed.digest,
                "classic_configuration": classic.digest,
                "gemini_c2_configuration": derived.digest,
                "profile": (
                    (
                        c2_route.ONE_PASS_FLEX_PROFILE_ID
                        if arguments.flex
                        else c2_route.ONE_PASS_PROFILE_ID
                    )
                    if arguments.one_pass
                    else c2_route.FLEX_PROFILE_ID
                    if arguments.flex
                    else c2_route.PROFILE_ID
                ),
                "policies": [str(item.tenant_id) for item in policies],
                "classic_stages_unchanged": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
