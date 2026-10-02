"""CLI and gate runner: `run` for arms A, B, D (acdev), `run-j` for the root Jev job, `score`."""

import argparse
import json
import sys
from pathlib import Path

from . import arms, pack, score

ARMS_BEFORE_J = ("A", "B", "D")


def write(out: Path, arm: str, rec: dict) -> None:
    with (out / f"{arm}.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_stage(arm: str, pk: dict, out: Path, repeats: int, stage: str, **kw) -> None:
    """Run one arm over the base calls or the red-team probes, skipping records already on disk."""
    done = {
        (r["input_id"], r["repeat"]) for r in score.load_records(out, arm).get(arm, {}).values()
    }
    for req in pk["requests"]:
        if req["input_id"].startswith("probe-") == (stage == "base"):
            continue
        for repeat in range(repeats):
            if (req["input_id"], repeat) not in done:
                write(out, arm, arms.run_arm(arm, pk, req, repeat, **kw))


def check_records(pk: dict, records: Path) -> None:
    """Refuse unless A and B answered every request and D every base call (repeat 0).

    A partial file (an arm stopped at a usage limit) would otherwise score as "no match":
    G2 would pass with overlap 0 and G1 would fall back to the English-only bar.
    """
    recs = score.load_records(records)
    missing = [
        (arm, req["input_id"])
        for arm in ARMS_BEFORE_J
        for req in pk["requests"]
        if (arm != "D" or not req["input_id"].startswith("probe-"))
        and not {q["id"] for q in req["questions"]}
        <= set(recs.get(arm, {}).get((req["input_id"], 0), {}).get("answers", {}))
    ]
    if missing:
        raise pack.PackError(
            f"arms A, B, D must answer every request before J; {len(missing)} missing "
            f"(arm, input_id) in {records}: {missing[:12]}{' ...' if len(missing) > 12 else ''}"
        )


def stop(message: str, meter: arms.SpendMeter | None = None) -> int:
    s = meter.state if meter else {}
    total = f"; spend total ₹{s['total_inr']:.2f} (${s['total_usd']:.4f})" if meter else ""
    print(f"STOP: {message}{total}", file=sys.stderr)
    return 2


def run_j(a: argparse.Namespace, pk: dict) -> int:
    """Root-run Jev job: preflight, base calls with repeats, G1–G2, then the red-team set and G3."""
    meter, transport = arms.SpendMeter(a.spend_file), arms.urllib_transport
    try:
        check_records(pk, a.records)  # before the key is read: no spend on a partial baseline
        key = arms.read_key(a.key_file)
        a.out.mkdir(parents=True, exist_ok=True)
        for arm in ARMS_BEFORE_J:
            (a.out / f"{arm}.jsonl").write_bytes((a.records / f"{arm}.jsonl").read_bytes())
        models = arms.list_models(key, transport)
        truth, kw = score.load_truth(a.pack), {"key": key, "meter": meter, "transport": transport}
        run_stage("J", pk, a.out, max(a.repeats, pack.REPEATS), "base", **kw)
        verdicts = score.gates(pk, truth, score.load_records(a.out), upto="G2")
        if all(v["pass"] for v in verdicts):
            run_stage("J", pk, a.out, 1, "red-team", **kw)
            verdicts = score.gates(pk, truth, score.load_records(a.out))
        result = {
            "model": pack.MODEL,
            "models_preflight": models,
            "gates": verdicts,
            "spend": meter.state,
            "thresholds": pack.THRESHOLDS,
            "input_set_hash": pack.INPUT_SET_HASH,
        }
        if all(v["pass"] for v in verdicts):
            result["uses"] = score.uses(pk, truth, score.load_records(a.out))
        (a.out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (arms.SpendStop, arms.GatewayError, PermissionError, pack.PackError, OSError) as err:
        return stop(arms.redact(str(err)), meter)
    failed = [v["gate"] for v in verdicts if not v["pass"]]
    return stop(f"gate {failed[0]} failed", meter) if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jev_phase1", description=__doc__)
    p.add_argument("command", choices=["run", "run-j", "score"])
    p.add_argument("--pack", type=Path, required=True)
    p.add_argument(
        "--out", type=Path, required=True, help="records directory (score: results file)"
    )
    p.add_argument("--arm", choices=list(ARMS_BEFORE_J))
    p.add_argument("--model")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--stage", choices=["base", "red-team"], default="base")
    p.add_argument("--records", type=Path, help="directory holding A, B and D records")
    p.add_argument("--key-file", type=Path, help="root-owned 0600 file with AI_GATEWAY_API_KEY=")
    p.add_argument("--spend-file", type=Path, help="persisted cumulative spend (JSON)")
    a = p.parse_args(argv)
    try:
        pk = pack.load_pack(a.pack)
    except (pack.PackError, OSError) as err:
        return stop(str(err))
    if a.command == "run":
        if not a.arm:
            p.error("--arm is required for run")
        a.out.mkdir(parents=True, exist_ok=True)
        run_stage(a.arm, pk, a.out, a.repeats, a.stage, model=a.model)
        return 0
    if not (a.records and (a.command == "score" or (a.key_file and a.spend_file))):
        p.error("run-j needs --records, --key-file and --spend-file; score needs --records")
    if a.command == "score":
        recs, truth = score.load_records(a.records), score.load_truth(a.pack)
        verdicts = score.gates(pk, truth, recs)
        result = {
            "gates": verdicts,
            "thresholds": pack.THRESHOLDS,
            "input_set_hash": pack.INPUT_SET_HASH,
        }
        if all(v["pass"] for v in verdicts):
            result["uses"] = score.uses(pk, truth, recs)
        a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        return 0
    return run_j(a, pk)


if __name__ == "__main__":
    sys.exit(main())
