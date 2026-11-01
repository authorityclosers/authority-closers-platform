#!/usr/bin/env python3
"""Engine (b)'s part of the matrix: claim only the workflows it can script, hand back what it cannot run, and note
sweep runs (axe, visual, monkey, crawl) that belong to no single workflow. It imports persona-qa's qa_matrix.py and
uses its file lock and CSV readers, so both engines can write at once. Commands print JSON lines.

  matrix.py claim --journeys J001,J002 --devices "390 px,360 px,1440,1920" --states normal,offline --n 10
  matrix.py release --workflow W00001 [--note "why"]     # back to "not run"
  matrix.py sweep --persona P01 --device "390 px" --result pass|fail --screenshot PATH --bugs a,b --notes "..."
  matrix.py scope --journeys J001,J002 --devices ... --states ...   # how many "not run" rows qualify
  matrix.py personas                                      # id, name, tags from qa_matrix's persona table
"""
import argparse
import importlib.util
import json
import os
import sys
import time

BASE = os.environ.get("QA_MATRIX_DIR", "/home/acdev/qa-matrix")
spec = importlib.util.spec_from_file_location("qa_matrix", os.path.join(BASE, "qa_matrix.py"))
qm = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]] + sys.argv[1:]
spec.loader.exec_module(qm)


def split(value):
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def qualifies(row, journeys, devices, states, areas):
    return (
        row["status"] == "not run"
        and (not journeys or row["journey_id"] in journeys)
        and (not devices or row["device"] in devices)
        and (not states or row["state"] in states)
        and (not areas or row["area"] in areas)
    )


def cmd_claim(a):
    journeys, devices, states, areas = split(a.journeys), split(a.devices), split(a.states), split(a.areas)
    out = []
    with qm.lock():
        W = qm.rd("workflows.csv")
        J = {j["id"]: j for j in qm.rd("journeys.csv")}
        P = {p["id"]: p for p in qm.rd("personas.csv")}
        now = time.time()
        order = sorted(range(len(W)), key=lambda i: (J[W[i]["journey_id"]]["priority"], i))
        for i in order:
            r = W[i]
            if r["status"] == "claimed" and qm.parse_iso(r["claimed_until"]) < now:
                r["status"], r["claimed_until"] = "not run", ""
            if len(out) >= a.n or not qualifies(r, journeys, devices, states, areas):
                continue
            if a.persona and r["persona"] not in split(a.persona):
                continue
            r["status"], r["claimed_until"] = "claimed", qm.iso(now + a.hold * 60)
            out.append(r)
        qm.wr("workflows.csv", qm.WC, W)
    for r in out:
        j, p = J[r["journey_id"]], P.get(r["persona"], {})
        print(json.dumps({**{k: r[k] for k in ("workflow_id", "journey_id", "area", "persona", "device", "theme", "state")},
                          "journey": j["journey"], "spec_ref": j["spec_ref"], "priority": j["priority"],
                          "persona_name": p.get("name", "")}, ensure_ascii=False))


def cmd_scope(a):
    journeys, devices, states, areas = split(a.journeys), split(a.devices), split(a.states), split(a.areas)
    W = qm.rd("workflows.csv")
    rows = [r for r in W if qualifies(r, journeys, devices, states, areas)]
    by = {}
    for r in rows:
        by[r["device"]] = by.get(r["device"], 0) + 1
    print(json.dumps({"qualifying": len(rows), "by_device": by}))


def cmd_release(a):
    with qm.lock():
        W = qm.rd("workflows.csv")
        for r in W:
            if r["workflow_id"] == a.workflow and r["status"] in ("claimed", "blocked"):
                r["status"], r["claimed_until"] = "not run", ""
        qm.wr("workflows.csv", qm.WC, W)
    print(json.dumps({"released": a.workflow}))


def cmd_sweep(a):
    with qm.lock():
        R = qm.rd("runs.csv")
        rid = "R%05d" % (max([int(r["run_id"][1:]) for r in R] + [0]) + 1)
        R.append(dict(run_id=rid, time=qm.iso(), engine="script", persona=a.persona or "", device=a.device or "", workflow_id="",
                      result=a.result, screenshot=a.screenshot or "", bug_ids=",".join(split(a.bugs)), notes=a.notes or ""))
        qm.wr("runs.csv", qm.RC, R)
    print(json.dumps({"run_id": rid, "result": a.result}))


def cmd_annotate(a):
    with qm.lock():
        B = qm.rd("bugs.csv")
        hit = 0
        for b in B:
            if b["bug_id"] == a.id:
                if a.prefix and not b["description"].startswith(a.prefix.split(":")[0]):
                    b["description"] = a.prefix + ": " + b["description"]
                if a.builder:
                    b["builder"] = a.builder
                if a.status:
                    b["status"] = a.status
                hit += 1
        qm.wr("bugs.csv", qm.BC, B)
    print(json.dumps({"annotated": a.id, "rows": hit}))


def cmd_reopen(a):
    """A new report on a fingerprint that has a row: the row takes the new ids; a closed row (fixed or verified) is reopened as new."""
    with qm.lock():
        B = qm.rd("bugs.csv")
        row = next((b for b in B if b["fingerprint"] == a.fingerprint), None)
        if not row:
            print(json.dumps({"reopened": 0, "why": "no row for this fingerprint"}))
            return
        was, old = row["status"], row["bug_id"]
        if was in ("fixed", "verified"):
            row["status"] = "new"
            row["description"] = f"REOPENED (seen again after it was marked {was}; earlier report {old}): " + row["description"]
        if a.id:
            row["bug_id"] = a.id
        if a.full:
            row["full_id"] = a.full
        qm.wr("bugs.csv", qm.BC, B)
    print(json.dumps({"reopened": 1 if was in ("fixed", "verified") else 0, "was": was, "old_id": old, "bug_id": row["bug_id"]}))


def cmd_personas(a):
    rows = []
    for line in qm.PERSONAS.strip().splitlines():
        parts = line.split("|")
        rows.append({"name": parts[0], "role": parts[1], "device": parts[5], "tags": parts[8] if len(parts) > 8 else ""})
    csv_rows = qm.rd("personas.csv")
    for pid, row in zip([p["id"] for p in csv_rows], rows):
        row["id"] = pid
    for row, full in zip(rows, csv_rows):
        row["language"], row["tech_level"], row["patience"] = full.get("language", ""), full.get("tech_level", ""), full.get("patience", "")
    print(json.dumps(rows, ensure_ascii=False))


def cmd_list(a):
    """Every workflow in a status (default "not run") on the given devices, as one JSON array (read only, no claim)."""
    devices = split(a.devices)
    J = {j["id"]: j for j in qm.rd("journeys.csv")}
    out = []
    for r in qm.rd("workflows.csv"):
        if r["status"] != a.status or (devices and r["device"] not in devices):
            continue
        j = J.get(r["journey_id"], {})
        out.append({**{k: r[k] for k in ("workflow_id", "journey_id", "area", "persona", "device", "theme", "state")},
                    "priority": j.get("priority", "P2"), "journey": j.get("journey", "")})
    print(json.dumps(out, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("claim", cmd_claim), ("scope", cmd_scope)):
        s = sp.add_parser(name)
        s.add_argument("--journeys", default="")
        s.add_argument("--devices", default="")
        s.add_argument("--states", default="")
        s.add_argument("--areas", default="")
        s.add_argument("--persona", default="")
        s.add_argument("--n", type=int, default=10)
        s.add_argument("--hold", type=int, default=10, help="minutes a claim is held")
        s.set_defaults(f=fn)
    s = sp.add_parser("release")
    s.add_argument("--workflow", required=True)
    s.set_defaults(f=cmd_release)
    s = sp.add_parser("sweep")
    for k in ("persona", "device", "result", "screenshot", "bugs", "notes"):
        s.add_argument("--" + k)
    s.set_defaults(f=cmd_sweep)
    s = sp.add_parser("personas")
    s.set_defaults(f=cmd_personas)
    s = sp.add_parser("annotate")
    s.add_argument("--id", required=True)
    s.add_argument("--prefix", default="")
    s.add_argument("--builder", default="")
    s.add_argument("--status", default="")
    s.set_defaults(f=cmd_annotate)
    s = sp.add_parser("reopen")
    s.add_argument("--fingerprint", required=True)
    s.add_argument("--id", default="")
    s.add_argument("--full", default="")
    s.set_defaults(f=cmd_reopen)
    s = sp.add_parser("list")
    s.add_argument("--status", default="not run")
    s.add_argument("--devices", default="")
    s.set_defaults(f=cmd_list)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
