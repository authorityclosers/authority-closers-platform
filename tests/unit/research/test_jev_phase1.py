"""Offline tests for the Jev Phase 1 harness: fake gateway, no network, no key anywhere."""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.research.jev_phase1 import __main__ as cli  # noqa: E402
from tools.research.jev_phase1 import arms, pack, score  # noqa: E402

PACK = ROOT / "docs/research/jev-fictional-pack-v1"
KEY = "vck_fictional_test_key_000"
OPENED: list[str] = []
sys.addaudithook(lambda event, args: OPENED.append(str(args[0])) if event == "open" else None)


@pytest.fixture(scope="module")
def pk() -> dict:
    return pack.load_pack(PACK)


@pytest.fixture(scope="module")
def truth() -> dict:
    return score.load_truth(PACK)


@pytest.fixture(scope="module")
def base_of(truth: dict) -> dict:
    """input id -> base call id (probes map to the call they were cut from)."""
    out = {cid: cid for cid in truth["base"]}
    for pair in truth["key"]:
        out[pair["clean_id"]] = out[pair["injected_id"]] = pair["base_id"]
    return out


class Oracle:
    """Answers from truth; `wrong` names (input prefix, question prefix) pairs answered wrongly."""

    def __init__(self, truth: dict, base_of: dict, wrong: tuple = (), cost: bool = True) -> None:
        self.truth, self.base_of, self.wrong, self.cost = truth, base_of, wrong, cost
        self.bodies: list[dict] = []
        self.calls: list[tuple] = []

    def answer(self, input_id: str, qid: str, options: list, wrong: tuple | None = None) -> str:
        label = self.truth["base"][self.base_of[input_id]]["question_answers"][qid]
        if any(
            input_id.startswith(a) and qid.startswith(b)
            for a, b in (self.wrong if wrong is None else wrong)
        ):
            return next(o for o in options if o != label)
        return label

    def __call__(self, method: str, url: str, body: bytes | None, headers: dict) -> tuple:
        self.calls.append((method, url, headers))
        if method == "GET":
            return 200, json.dumps(
                {"data": [{"id": "typesafe-ai/jev", "version": pack.MODEL}]}
            ).encode()
        req = json.loads(body)
        self.bodies.append(req)
        input_id = self.current
        answers = {}
        for qid, q in req["questions"].items():
            label = self.answer(input_id, qid, list(q["criteria"]))
            answers[qid] = {
                "type": "choice",
                "choice": label,
                "probabilities": {o: 1.0 if o == label else 0.0 for o in q["criteria"]},
            }
        tokens = len(req["state"]) // 4 + 120 * len(req["questions"])
        gateway = {"routing": {"canonicalSlug": pack.GATEWAY_SLUG, "finalProvider": "typesafe-ai"}}
        if self.cost:
            gateway["cost"] = f"{tokens / 1e6 * pack.USD_PER_M_INPUT_TOKENS:.10f}"
        return 200, json.dumps(
            {
                "model": pack.GATEWAY_SLUG,
                "answers": answers,
                "usage": {"inputTokens": tokens, "outputTokens": 0},
                "providerMetadata": {"gateway": gateway},
            }
        ).encode()


def oracle_arm(arm: str, pk: dict, oracle: Oracle, out: Path, wrong: tuple = ()) -> None:
    for req in pk["requests"]:
        answers = {
            q["id"]: {
                "label": oracle.answer(req["input_id"], q["id"], q["options"], wrong),
                "probability": 0.9,
            }
            for q in req["questions"]
        }
        cli.write(
            out,
            arm,
            {
                "arm": arm,
                "model": f"fake-{arm}",
                "input_id": req["input_id"],
                "repeat": 0,
                "answers": answers,
                "latency_ms": 1,
                "cost_inr": 0.0,
                "screen_flags": [],
            },
        )


def run_j_with(
    pk: dict, oracle: Oracle, tmp: Path, monkeypatch, records_wrong: dict | None = None
) -> tuple:
    """Drive `run-j` end to end with the fake gateway; returns (exit code, out dir, spend file)."""
    records, out, spend = tmp / "records", tmp / "j", tmp / "spend.json"
    records.mkdir()
    for arm in "AB":
        oracle_arm(arm, pk, oracle, records, (records_wrong or {}).get(arm, ()))
    for stage in ("base", "red-team"):
        cli.run_stage("D", pk, records, 1, stage)
    keyfile = root_key(tmp, monkeypatch)
    by_state = {pack.state_text(call, pk["definitions"]): cid for cid, call in pk["calls"].items()}

    def transport(method, url, body, headers):
        if body:
            oracle.current = by_state[json.loads(body)["state"]]
        return oracle(method, url, body, headers)

    monkeypatch.setattr(arms, "urllib_transport", transport)
    code = cli.main(
        [
            "run-j",
            "--pack",
            str(PACK),
            "--records",
            str(records),
            "--out",
            str(out),
            "--key-file",
            str(keyfile),
            "--spend-file",
            str(spend),
        ]
    )
    return code, out, spend


def root_key(tmp: Path, monkeypatch, mode: int = 0o600, uid: int = 0) -> Path:
    keyfile = tmp / "ai-gateway.env"
    keyfile.write_text(f"# fictional\nAI_GATEWAY_API_KEY={KEY}\n")
    keyfile.chmod(0o600)
    real = os.stat

    def fake_stat(path, *a, **kw):
        st = real(path, *a, **kw)
        if Path(path) != keyfile:
            return st
        return os.stat_result(
            (
                0o100000 | mode,
                st.st_ino,
                st.st_dev,
                st.st_nlink,
                uid,
                st.st_gid,
                st.st_size,
                st.st_atime,
                st.st_mtime,
                st.st_ctime,
            )
        )

    monkeypatch.setattr(arms.os, "stat", fake_stat)
    return keyfile


def test_pack_hash_refusal(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "questions").mkdir()
    (tmp_path / "inputs/base.json").write_text("[]")
    with pytest.raises(pack.PackError, match="set-hash differs"):
        pack.load_pack(tmp_path)
    assert (
        cli.main(["run", "--pack", str(tmp_path), "--out", str(tmp_path / "o"), "--arm", "D"]) == 2
    )


def test_truth_hash_refusal(monkeypatch) -> None:
    monkeypatch.setattr(pack, "TRUTH_SET_HASH", "0" * 64)
    with pytest.raises(pack.PackError, match="truth set-hash"):
        score.load_truth(PACK)


def test_frozen_constants(pk: dict) -> None:
    assert (
        pk["input_set_hash"]
        == pack.INPUT_SET_HASH
        == json.loads((PACK / "MANIFEST.json").read_text())["set_hashes"]["inputs"]
    )
    assert pack.MODEL == "jev-1.13.0" and pack.SPEND_STOP_INR < pack.BUDGET_INR == 500
    assert pack.THRESHOLDS["G1"] == {"vs_english": 0.10, "vs_weaker_ab": 0.05}


def test_screen_catches_probes_and_spares_clean_text(pk: dict, truth: dict) -> None:
    probes = [p for p in truth["key"] if p["type"] != "R4"]
    caught = sum(p["segment_id"] in pack.screen(pk["calls"][p["injected_id"]]) for p in probes)
    false = sum(len(pack.screen(pk["calls"][p["clean_id"]])) for p in truth["key"])
    segments = sum(len(pk["calls"][p["clean_id"]]["segments"]) for p in truth["key"])
    assert (len(probes), caught, false, segments) == (96, 96, 0, 2400)


def test_zdr_on_every_request_and_gateway_cost(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path
) -> None:
    oracle, meter = Oracle(truth, base_of), arms.SpendMeter(tmp_path / "spend.json")
    req = max(pk["requests"], key=lambda r: len(r["questions"]))
    oracle.current = req["input_id"]
    rec = arms.run_arm("J", pk, req, 0, key=KEY, meter=meter, transport=oracle)
    assert len(oracle.bodies) == -(-len(req["questions"]) // pack.QUESTIONS_PER_REQUEST) > 1
    for body in oracle.bodies:
        assert body["providerOptions"]["gateway"] == {
            "zeroDataRetention": True,
            "disallowPromptTraining": True,
            "only": ["typesafe-ai"],
        }
        assert (
            body["model"] == pack.GATEWAY_SLUG
            and "models" not in body["providerOptions"]["gateway"]
        )
    assert all(h["Authorization"] == f"Bearer {KEY}" for _, _, h in oracle.calls)
    assert (
        set(rec["answers"]) == {q["id"] for q in req["questions"]}
        and rec["cost_source"] == "gateway"
    )
    assert (
        rec["cost_usd"] == pytest.approx(meter.state["gateway_usd"])
        and meter.state["estimated_usd"] == 0
    )
    assert json.loads((tmp_path / "spend.json").read_text())["requests"] == len(oracle.bodies)
    assert rec["cost_inr"] < 1.5 and rec["model"] == pack.MODEL and rec["version_verified"] is False


def test_estimated_cost_when_gateway_omits_it(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path
) -> None:
    oracle, meter = Oracle(truth, base_of, cost=False), arms.SpendMeter(tmp_path / "spend.json")
    oracle.current = pk["requests"][0]["input_id"]
    rec = arms.run_arm("J", pk, pk["requests"][0], 0, key=KEY, meter=meter, transport=oracle)
    assert rec["cost_source"] == "estimated" and meter.state["estimated_requests"] == len(
        oracle.bodies
    )
    assert meter.state["gateway_usd"] == 0 and meter.state["estimated_usd"] == pytest.approx(
        rec["cost_usd"]
    )


def test_spend_stop_refuses_before_the_request(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path
) -> None:
    spend = tmp_path / "spend.json"
    spend.write_text(
        json.dumps({**arms.SpendMeter.EMPTY, "total_inr": 449.99, "total_usd": 4.9999})
    )
    oracle, meter = Oracle(truth, base_of), arms.SpendMeter(spend)
    with pytest.raises(arms.SpendStop, match="spend stop"):
        arms.run_arm("J", pk, pk["requests"][0], 0, key=KEY, meter=meter, transport=oracle)
    assert oracle.bodies == [] and json.loads(spend.read_text())["total_inr"] == 449.99


def test_key_file_checks(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain.env"
    plain.write_text(f"AI_GATEWAY_API_KEY={KEY}\n")
    plain.chmod(0o600)
    with pytest.raises(PermissionError, match="root-owned mode 0600"):  # owned by the test user
        arms.read_key(plain)
    with pytest.raises(PermissionError):
        arms.read_key(root_key(tmp_path, monkeypatch, mode=0o640))
    assert arms.read_key(root_key(tmp_path, monkeypatch)) == KEY
    keyfile = root_key(tmp_path, monkeypatch)
    keyfile.write_text("OTHER=1\n")
    with pytest.raises(arms.GatewayError, match="no AI_GATEWAY_API_KEY"):
        arms.read_key(keyfile)


def test_version_or_slug_mismatch_is_refused() -> None:
    gateway = {"routing": {"canonicalSlug": pack.GATEWAY_SLUG}}
    assert arms.check_version({"model": "jev-1.13.0", "metadata": {"gateway": gateway}}) is True
    with pytest.raises(arms.GatewayError, match="answered by None"):  # no routing metadata
        arms.check_version({"model": "other/model", "metadata": {}})
    with pytest.raises(arms.GatewayError, match="jev-1.12.0"):
        arms.check_version({"model": "jev-1.12.0", "metadata": {"gateway": gateway}})
    with pytest.raises(arms.GatewayError, match="other/model"):
        arms.check_version(
            {"model": None, "metadata": {"gateway": {"routing": {"canonicalSlug": "other/model"}}}}
        )


def test_partial_gateway_answers_are_refused_but_paid_for(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path
) -> None:
    class Partial(Oracle):
        def __call__(self, method, url, body, headers):
            status, raw = super().__call__(method, url, body, headers)
            data = json.loads(raw)
            data["answers"].pop(next(iter(data["answers"])))
            return status, json.dumps(data).encode()

    oracle, meter = Partial(truth, base_of), arms.SpendMeter(tmp_path / "spend.json")
    oracle.current = pk["requests"][0]["input_id"]
    with pytest.raises(arms.GatewayError, match="do not match the questions asked"):
        arms.run_arm("J", pk, pk["requests"][0], 0, key=KEY, meter=meter, transport=oracle)
    assert meter.state["requests"] == 1 and meter.state["gateway_usd"] > 0
    assert meter.state["pending_usd"] == 0


def test_spend_reservation_is_persisted_before_the_request_and_folded_in_after_a_crash(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path
) -> None:
    spend, seen = tmp_path / "spend.json", []

    class Peek(Oracle):
        def __call__(self, method, url, body, headers):
            seen.append(json.loads(spend.read_text())["pending_usd"])
            return super().__call__(method, url, body, headers)

    oracle, meter = Peek(truth, base_of), arms.SpendMeter(spend)
    oracle.current = pk["requests"][0]["input_id"]
    arms.run_arm("J", pk, pk["requests"][0], 0, key=KEY, meter=meter, transport=oracle)
    assert seen and all(p > 0 for p in seen) and meter.state["pending_usd"] == 0
    crashed = {**meter.state, "pending_usd": 0.01}  # died between the POST and record()
    spend.write_text(json.dumps(crashed))
    again = arms.SpendMeter(spend)
    assert again.state["pending_usd"] == 0 and again.state["interrupted_requests"] == 1
    assert again.state["total_usd"] == pytest.approx(crashed["total_usd"] + 0.01)
    assert again.state["estimated_usd"] == pytest.approx(0.01)
    assert json.loads(spend.read_text()) == again.state


def test_no_key_in_logs_or_outputs(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path, monkeypatch, capsys
) -> None:
    class Leaky(Oracle):
        def __call__(self, method, url, body, headers):
            if method == "POST":
                return 500, json.dumps({"error": f"bad token Bearer {KEY} ({KEY})"}).encode()
            return super().__call__(method, url, body, headers)

    code, out, spend = run_j_with(pk, Leaky(truth, base_of), tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("STOP: gateway HTTP 500") and "spend total ₹0.00" in err
    assert KEY not in err and "[redacted]" in err
    for f in [*tmp_path.rglob("*.json"), *tmp_path.rglob("*.jsonl")]:
        assert KEY not in f.read_text()


def test_run_j_requires_a_b_d_records(pk: dict, tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "records").mkdir()
    code = cli.main(
        [
            "run-j",
            "--pack",
            str(PACK),
            "--records",
            str(tmp_path / "records"),
            "--out",
            str(tmp_path / "j"),
            "--key-file",
            str(root_key(tmp_path, monkeypatch)),
            "--spend-file",
            str(tmp_path / "spend.json"),
        ]
    )
    assert code == 2 and "must answer every request before J" in capsys.readouterr().err
    assert not (tmp_path / "j").exists()


def test_partial_b_records_refuse_before_any_gateway_call(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path, monkeypatch, capsys
) -> None:
    records, oracle = tmp_path / "records", Oracle(truth, base_of)
    records.mkdir()
    for arm in "AB":
        oracle_arm(arm, pk, oracle, records)
    cli.run_stage("D", pk, records, 1, "base")
    lines = (records / "B.jsonl").read_text().splitlines()
    dropped = json.loads(lines[-1])["input_id"]  # arm B stopped one request short
    (records / "B.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    calls: list = []
    monkeypatch.setattr(arms, "urllib_transport", lambda *a: calls.append(a) or (500, b""))
    code = cli.main(
        [
            "run-j",
            "--pack",
            str(PACK),
            "--records",
            str(records),
            "--out",
            str(tmp_path / "j"),
            "--key-file",
            str(tmp_path / "absent.env"),  # would raise OSError if the key were read first
            "--spend-file",
            str(tmp_path / "spend.json"),
        ]
    )
    err = capsys.readouterr().err
    assert code == 2 and "must answer every request before J; 1 missing" in err
    assert f"('B', '{dropped}', 0)" in err and calls == [] and not (tmp_path / "j").exists()
    with pytest.raises(pack.PackError, match="1 missing"):
        cli.check_records(pk, records)
    (records / "B.jsonl").write_text("\n".join(lines) + "\n")
    cli.check_records(pk, records)


def test_first_failed_gate_stops_spending(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path, monkeypatch, capsys
) -> None:
    oracle = Oracle(
        truth, base_of, wrong=(("call-", "seg-"),)
    )  # every segment label wrong: G1 fails
    code, out, spend = run_j_with(pk, oracle, tmp_path, monkeypatch)
    assert code == 2 and "STOP: gate G1 failed; spend total ₹" in capsys.readouterr().err
    result = json.loads((out / "results.json").read_text())
    assert [g["gate"] for g in result["gates"]] == ["G1"] and result["gates"][0]["pass"] is False
    assert "uses" not in result and result["models_preflight"]["pinned_listed"] is True
    ids = {r["input_id"] for r in score.load_records(out)["J"].values()}
    assert ids == set(truth["base"]) and all(not i.startswith("probe-") for i in ids)
    repeats = {r["repeat"] for r in score.load_records(out)["J"].values()}
    assert repeats == {0, 1, 2} and json.loads(spend.read_text())["requests"] == len(oracle.bodies)
    code = cli.main(["score", "--pack", str(PACK), "--records", str(out), "--out", str(out / "s")])
    err = capsys.readouterr().err  # the standalone scorer refuses J without the red-team set
    assert (
        code == 2 and "must answer every request before scoring" in err and "('J', 'probe-" in err
    )


def test_all_gates_pass_then_red_team_and_uses(
    pk: dict, truth: dict, base_of: dict, tmp_path: Path, monkeypatch
) -> None:
    oracle = Oracle(truth, base_of)
    code, out, spend = run_j_with(
        pk,
        oracle,
        tmp_path,
        monkeypatch,
        records_wrong={"A": (("call-0", "item-0"),), "B": (("call-1", "seg-00"),)},
    )
    result = json.loads((out / "results.json").read_text())
    assert code == 0 and [g["gate"] for g in result["gates"]] == ["G1", "G2", "G3"]
    assert all(g["pass"] for g in result["gates"]) and result["gates"][2]["hard_stop"] is False
    g3 = result["gates"][2]
    assert g3["screen"] == {"probes": 96, "caught": 96, "clean_segments": 2400, "false_flags": 0}
    assert (
        g3["pairs"] == {"a": 30, "b": 30, "c": 30, "d": 30} and sum(g3["flips"]["J"].values()) == 0
    )
    uses = result["uses"]
    assert (
        uses["a"]["recall"]["J"] == 1.0
        and uses["b"]["prospect_recall"] == 1.0
        and uses["b"]["alpha"] == 1.0
    )
    assert uses["c"]["J"]["recall_top20"] >= 0.6 and uses["c"]["pass"] is True
    assert uses["d"]["ece"] == 0 and uses["d"]["units"] > 0 and uses["all"]["repeat_change"] == 0
    assert uses["all"]["pass"] is True and result["version_verified"] is False
    assert uses["all"]["records"] == 36 * 3 and uses["all"]["inr_per_25min_call_median"] < 1.5
    spent = json.loads(spend.read_text())
    assert (
        spent == result["spend"]
        and spent["requests"] == len(oracle.bodies)
        and 0 < spent["total_inr"] < 450
    )
    probe_ids = [
        r["input_id"]
        for r in score.load_records(out)["J"].values()
        if r["input_id"].startswith("probe-")
    ]
    assert len(probe_ids) == 240
    assert sorted(result["thresholds"]) == sorted(pack.THRESHOLDS)
    scored = out / "scored.json"
    assert (
        cli.main(["score", "--pack", str(PACK), "--records", str(out), "--out", str(scored)]) == 0
    )
    assert json.loads(scored.read_text())["uses"]["c"] == uses["c"]
    monkeypatch.setattr(score, "gates", lambda *a, **k: [{"gate": "G1", "pass": False}])
    assert (
        cli.main(["score", "--pack", str(PACK), "--records", str(out), "--out", str(scored)]) == 2
    )
    assert "uses" not in json.loads(scored.read_text())
    recs = score.load_records(out)
    del recs["A"][(truth["key"][0]["clean_id"], 0)]
    with pytest.raises(pack.PackError, match="G3 needs arm A records"):
        score.gate_g3(pk, truth, recs)


def test_arm_runners_never_open_truth(pk: dict, truth: dict, base_of: dict, tmp_path: Path) -> None:
    oracle, meter = Oracle(truth, base_of), arms.SpendMeter(tmp_path / "spend.json")
    req = pk["requests"][0]
    oracle.current = req["input_id"]

    def fake_run(cmd, **kw):
        assert "AI_GATEWAY_API_KEY" not in str(kw.get("env", "")) and kw["input"]
        reply = json.dumps(
            {q["id"]: {"label": q["options"][0], "probability": 0.5} for q in req["questions"]}
        )
        if cmd[0] == "codex":
            Path(cmd[cmd.index("-o") + 1]).write_text("Answer:\n" + reply)
        return type("Done", (), {"stdout": json.dumps({"result": "```json\n" + reply + "\n```"})})()

    OPENED.clear()
    pack.load_pack(PACK)
    recs = [
        arms.run_arm("D", pk, req, 0),
        arms.run_arm("J", pk, req, 0, key=KEY, meter=meter, transport=oracle),
        arms.run_arm("A", pk, req, 0, run=fake_run),
        arms.run_arm("B", pk, req, 0, model="m", run=fake_run),
    ]
    assert not [p for p in OPENED if "/truth/" in p or p.endswith("truth")]
    assert [r["arm"] for r in recs] == ["D", "J", "A", "B"]
    assert all(set(r["answers"]) == {q["id"] for q in req["questions"]} for r in recs)
    assert recs[0] == arms.run_arm("D", pk, req, 0) | {"latency_ms": recs[0]["latency_ms"]}


def test_scorer_is_the_only_truth_reader() -> None:
    src = {p.name: p.read_text() for p in (ROOT / "tools/research/jev_phase1").glob("*.py")}
    assert [n for n, text in src.items() if '"truth/' in text or "'truth/" in text] == ["score.py"]
