# Jev Phase 1 harness (AUT-630)

Pre-registered bake-off of `jev-1.13.0` against arms A (Claude CLI), B (Codex CLI) and
D (deterministic) on the sealed fictional pack v1.1. Design: AUT-335 §4.3–4.7. Thresholds
and the pack set-hashes are constants in `pack.py`; the harness refuses any other pack.

Arm runners read only `inputs/` and `questions/`. `score.py` is the only module that opens
`truth/`. Nothing here deploys or touches product code.

## Part 2, step 1: arms A, B and D as `acdev` (subscriptions only; stop on usage limits)

```sh
cd <repo at the merged SHA>
P=docs/research/jev-fictional-pack-v1; R=$HOME/research/aut-630/records
for arm in A B D; do
  python3 -m tools.research.jev_phase1 run --pack $P --out $R --arm $arm --stage base
  python3 -m tools.research.jev_phase1 run --pack $P --out $R --arm $arm --stage red-team
done
```

Records are append-only JSONL per arm; a rerun skips `(input_id, repeat)` pairs already on disk.

## Part 2, step 2: arm J as root (the only process that reads the key)

```sh
sudo python3 -m tools.research.jev_phase1 run-j \
  --pack docs/research/jev-fictional-pack-v1 --records /home/acdev/research/aut-630/records \
  --out /var/lib/authority-closers/research/aut-630/j --spend-file /var/lib/authority-closers/research/aut-630/spend.json \
  --key-file /etc/authority-closers/research/ai-gateway.env
```

Order: key-file check (root-owned 0600, never printed, never in a child environment), free
model-list preflight, base calls × 3 repeats, G1 then G2, and only when both pass the red-team
probes and G3, then the four uses. Every request sets `zeroDataRetention`, `disallowPromptTraining`
and `only: ["typesafe-ai"]`. The spend meter refuses a request when the persisted total plus its
worst case would exceed ₹450; the gateway budget of ₹500 is the soft-cap backstop. Exit code 0 only
when every gate passed; otherwise 2 with the spend total on stderr.

Done checks for the Root child: exit code, `spend.json` totals (script total and gateway-reported
`gateway_usd`), `sha256sum` of `J.jsonl` and `results.json`, and the directory copied read-only to
the results path.

## Scoring records without the gateway

```sh
python3 -m tools.research.jev_phase1 score --pack docs/research/jev-fictional-pack-v1 \
  --records <dir with A,B,D,J jsonl> --out results.json
```
