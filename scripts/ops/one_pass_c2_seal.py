"""Seal Gemini 3.1 Flash-Lite as an approved C2 route, keeping every classic route.

Root runs this on the host with the environment's two current files (``--flex`` for the
Flex configuration, a second profile beside the standard one; ``--one-pass`` for the
configuration whose facts route is the one-pass C4 request; ``--one-pass --luna
--openai-governance FILE`` for that request and C5 on GPT-6 Luna, where FILE is Root's JSON
of the OpenAI stages' privacy_revision, privacy_notice, retention_ref and
professional_gate_ref, after the owner confirmed the OpenAI DPA) (owner, 21 Oct 2026:
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
  ``--classic``, so nothing else can be slipped into the seal. For ``--luna`` when the
  classic configuration has no OpenAI GPT-6 Luna entry, the derivation uses the one in
  ``--configuration`` (scripts/data-changes/one-pass-flex-production.py builds it from
  existing records); the summary prints its references for Root to check before installing.
- ``--luna-c4`` (with ``--luna``): the hybrid, only the one-pass C4 request on Luna and C5
  kept on Gemini 3.8 Flash (profiles ``luna-c4-one-pass`` and ``luna-c4-one-pass-flex``).

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
    parser.add_argument(
        "--luna",
        action="store_true",
        help="with --one-pass: the one-pass request and C5 on OpenAI GPT-6 Luna",
    )
    parser.add_argument(
        "--openai-governance",
        type=Path,
        help="with --luna: Root's JSON of the OpenAI stages' privacy and retention references",
    )
    parser.add_argument(
        "--luna-c4",
        action="store_true",
        help="with --luna: only the one-pass C4 request on Luna, C5 kept on Gemini 3.8 Flash",
    )
    arguments = parser.parse_args(argv)
    governance = None
    if arguments.luna_c4 and not arguments.luna:
        print(json.dumps({"refused": "luna_c4_needs_luna"}), file=sys.stderr)
        return 2
    if arguments.luna:
        if not arguments.one_pass or arguments.openai_governance is None:
            print(
                json.dumps({"refused": "luna_needs_one_pass_and_openai_governance"}),
                file=sys.stderr,
            )
            return 2
        governance = json.loads(arguments.openai_governance.read_text())
    bundle = load_hosted_approval_bundle(arguments.bundle.read_bytes())
    classic = parse_registry_config(json.loads(arguments.classic.read_text()))
    saved = parse_registry_config(json.loads(arguments.configuration.read_text()))
    luna_key = ("openai", c2_route.LUNA_MODEL)
    openai = None
    if arguments.luna and not any(
        (item.provider_id, item.model_id) == luna_key for item in classic.providers
    ):
        # The entry the data change built from existing records; Root checks its references.
        openai = next(
            (item for item in saved.providers if (item.provider_id, item.model_id) == luna_key),
            None,
        )
    derived = c2_route.derive_configuration(
        classic,
        flex=arguments.flex,
        one_pass=arguments.one_pass,
        luna=arguments.luna,
        openai=openai,
        luna_report=not arguments.luna_c4,
    )
    if saved.digest != derived.digest:
        print(
            json.dumps({"refused": "configuration_is_not_the_derived_one", "saved": saved.digest}),
            file=sys.stderr,
        )
        return 2
    sealed = c2_route.seal(
        bundle,
        classic,
        derived,
        flex=arguments.flex,
        one_pass=arguments.one_pass,
        luna=governance,
        luna_report=not arguments.luna_c4,
    )
    arguments.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    (arguments.out / "hosted-approval.json").write_bytes(sealed.to_json())
    (arguments.out / "hosted-approval.sha256").write_text(sealed.digest + "\n")
    policies = (
        *(() if sealed.acquisition_policy is None else (sealed.acquisition_policy,)),
        *sealed.organisation_acquisition_policies,
    )
    openai_summary: dict[str, object] = {}
    if arguments.luna:
        entry = next(
            item for item in derived.providers if (item.provider_id, item.model_id) == luna_key
        )
        openai_summary["openai_entry"] = {
            "from": "configuration" if openai is not None else "classic",
            **{
                field: getattr(entry, field)
                for field in (
                    "credential_ref",
                    "provider_terms_ref",
                    "privacy_ref",
                    "permission_ref",
                    "endpoint_approval_ref",
                )
            },
        }
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
                        c2_route.LUNA_C4_FLEX_PROFILE_ID
                        if arguments.flex
                        else c2_route.LUNA_C4_PROFILE_ID
                    )
                    if arguments.luna_c4
                    else (
                        c2_route.LUNA_FLEX_PROFILE_ID
                        if arguments.flex
                        else c2_route.LUNA_PROFILE_ID
                    )
                    if arguments.luna
                    else (
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
                **openai_summary,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
