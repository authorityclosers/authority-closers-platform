#!/usr/bin/env python3
# ruff: noqa: S603 -- operator-reviewed endpoint command arrays; diagnostics suppressed
"""Require populated + reverse restore proof with exact current PG settings/schema.

This does not manufacture a proof from a fresh-database restore or perform writes.
The operator supplies the reviewed receipt from the actual bootstrap configuration.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def query(argv):
    r = subprocess.run(argv, capture_output=True, check=False, timeout=120)
    if r.returncode:
        raise RuntimeError("restore admission read failed")
    return json.loads(r.stdout)


def schema_digest(counts):
    # Sequence values and row counts change while source is live; schema does not.
    catalog = [row for row in counts["catalog"] if row[0] != "sequence"]
    return hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()


def admit(config, proof):
    if not proof.get("owner_record") or proof.get("environment") != "production":
        raise ValueError("reviewed production restore proof required")
    if not proof.get("populated_restore_passed") or not proof.get("reverse_restore_passed"):
        raise ValueError("both populated and reverse restore proofs required")
    observed_capacities = {}
    for side in ["source", "target"]:
        observed = query(config[side]["database"] + ["capacity"])
        observed_capacities[side] = observed
        if observed != proof[side + "_capacity"]:
            raise ValueError("PG version/lock/connection settings differ from restore proof")
    majors = {int(value["server_version_num"]) // 10000 for value in observed_capacities.values()}
    if len(majors) != 1:
        raise ValueError("source and target PostgreSQL majors must match")
    counts = query(config["source"]["database"] + ["counts"])
    if schema_digest(counts) != proof["source_schema_sha256"]:
        raise ValueError("schema differs from populated restore proof")
    print("restore admission matches reviewed populated/reverse proof")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--proof", required=True)
    args = p.parse_args()
    admit(json.loads(Path(args.config).read_text()), json.loads(Path(args.proof).read_text()))


if __name__ == "__main__":
    main()
