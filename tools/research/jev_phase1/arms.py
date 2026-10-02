"""Arm runners (§4.3): A Claude CLI, B Codex CLI, D deterministic, J Jev through the gateway.

Runners take `inputs/` + `questions/` material only. The key comes from `--key-file` in the
root-run job; it is never printed and never placed in a child process environment.
"""

import json
import os
import random
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import pack

KEY_RE = re.compile(r"(vck_[A-Za-z0-9_-]+|Bearer\s+\S+)")
VERSION_RE = re.compile(r"jev-\d+\.\d+\.\d+")
CLI = {
    "A": [
        "claude",
        "-p",
        "--bare",
        "--output-format",
        "json",
        "--tools",
        "",
        "--no-session-persistence",
    ],
    "B": ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only"]
    + ["--color", "never", "-o", "{last}", "-"],
}
MODEL_FLAG = {"A": "--model", "B": "-m"}
HINT = {
    "MTH-02": (r"problem|issue|samasya|takleef|मुश्किल|समस्या|મુશ્કેલી|સમસ્યા", "prospect", "none"),
    "MTH-04": (
        r"\b(but|however|expensive|cost|not sure|cannot|can't|nahi|nathi|lekin|pan)\b"
        r"|नहीं|लेकिन|નથી|પણ",
        "present",
        "absent",
    ),
    "MTH-05": (
        r"monday|tuesday|wednesday|thursday|friday|o'clock|\d{1,2}(am|pm)|सोमवार|સોમવાર",
        "scheduled",
        "none",
    ),
}
GATEWAY_OPTIONS = {
    "zeroDataRetention": True,
    "disallowPromptTraining": True,
    "only": ["typesafe-ai"],
}


class SpendStop(RuntimeError): ...


class GatewayError(RuntimeError): ...


def redact(text: str) -> str:
    return KEY_RE.sub("[redacted]", text)


def read_key(path: Path) -> str:
    st = os.stat(path)
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o600:
        raise PermissionError(f"{path} must be root-owned mode 0600")
    lines = [ln for ln in path.read_text().splitlines() if ln.startswith("AI_GATEWAY_API_KEY=")]
    if not lines or not lines[0].split("=", 1)[1].strip():
        raise GatewayError(f"{path} has no AI_GATEWAY_API_KEY line")
    return lines[0].split("=", 1)[1].strip()


class SpendMeter:
    """Cumulative gateway spend persisted to disk; refuses past SPEND_STOP_INR (§4.7)."""

    EMPTY = {
        "total_usd": 0.0,
        "total_inr": 0.0,
        "gateway_usd": 0.0,
        "estimated_usd": 0.0,
        "requests": 0,
        "estimated_requests": 0,
    }

    def __init__(self, path: Path):
        self.path = path
        self.state = json.loads(path.read_text()) if path.exists() else dict(self.EMPTY)

    def reserve(self, worst_inr: float) -> None:
        if self.state["total_inr"] + worst_inr > pack.SPEND_STOP_INR:
            raise SpendStop(
                f"spend stop: total ₹{self.state['total_inr']:.2f} + worst case "
                f"₹{worst_inr:.2f} > ₹{pack.SPEND_STOP_INR}"
            )

    def record(self, cost_usd: float, estimated: bool) -> None:
        s = self.state
        s["total_usd"], s["total_inr"] = (
            s["total_usd"] + cost_usd,
            s["total_inr"] + cost_usd * pack.INR_PER_USD,
        )
        s["estimated_usd" if estimated else "gateway_usd"] += cost_usd
        s["requests"], s["estimated_requests"] = (
            s["requests"] + 1,
            s["estimated_requests"] + int(estimated),
        )
        self.path.with_suffix(".tmp").write_text(json.dumps(s, indent=2) + "\n")
        os.replace(self.path.with_suffix(".tmp"), self.path)


def urllib_transport(method: str, url: str, body: bytes | None, headers: dict) -> tuple:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def worst_case_inr(state: str, n_questions: int) -> float:
    tokens = len(state.encode()) / 2 + 300 + 150 * n_questions
    return tokens / 1e6 * pack.USD_PER_M_INPUT_TOKENS * pack.INR_PER_USD


def jev_request(state: str, questions: list, definitions: dict) -> dict:
    """One `/v1/evaluate` body: ZDR, no training and the TypeSafe-only route on every request."""
    qs = {
        q["id"]: {
            "type": "choice",
            "instructions": pack.question_text(definitions, q),
            "criteria": {o: o for o in q["options"]},
        }
        for q in questions
    }
    return {
        "model": pack.GATEWAY_SLUG,
        "state": state,
        "questions": qs,
        "providerOptions": {"gateway": dict(GATEWAY_OPTIONS)},
    }


def check_version(reported: dict) -> bool:
    """Refuse an answer from another slug or version; True when a version string was reported."""
    slug = (
        reported.get("metadata", {})
        .get("gateway", {})
        .get("routing", {})
        .get("canonicalSlug", pack.GATEWAY_SLUG)
    )
    versions = set(VERSION_RE.findall(json.dumps(reported)))
    if slug != pack.GATEWAY_SLUG or versions - {pack.MODEL}:
        raise GatewayError(
            f"answered by {slug} {sorted(versions)}, not {pack.GATEWAY_SLUG} {pack.MODEL}"
        )
    return bool(versions)


def list_models(key: str, transport) -> dict:
    """Free preflight: the gateway's model list must not name a Jev version other than MODEL."""
    status, raw = transport("GET", pack.MODELS_URL, None, {"Authorization": f"Bearer {key}"})
    if status != 200:
        raise GatewayError(f"models HTTP {status}: {redact(raw[:500].decode('utf-8', 'replace'))}")
    versions = sorted(set(VERSION_RE.findall(raw.decode("utf-8", "replace"))))
    if versions and pack.MODEL not in versions:
        raise GatewayError(f"gateway lists {versions}, not {pack.MODEL}")
    return {"sha256": pack.sha(raw), "versions": versions, "pinned_listed": pack.MODEL in versions}


def jev_call(key: str, meter: SpendMeter, body: dict, transport) -> tuple:
    meter.reserve(worst_case_inr(body["state"], len(body["questions"])))
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    status, raw = transport("POST", pack.GATEWAY_URL, json.dumps(body).encode(), headers)
    if status != 200:
        raise GatewayError(f"gateway HTTP {status}: {redact(raw[:500].decode('utf-8', 'replace'))}")
    data = json.loads(raw)
    meta = data.get("providerMetadata", data.get("provider_metadata", {}))
    pinned = check_version({"model": data.get("model"), "metadata": meta})
    usage, gateway = data.get("usage", {}), meta.get("gateway", {})
    tokens, estimated = (
        int(usage.get("inputTokens", usage.get("input_tokens", 0))),
        "cost" not in gateway,
    )
    cost = tokens / 1e6 * pack.USD_PER_M_INPUT_TOKENS if estimated else float(gateway["cost"])
    meter.record(cost, estimated)
    answers = {}
    for qid, a in data["answers"].items():
        probs = a.get("probabilities", {})
        answers[qid] = {
            "label": a["choice"],
            "probability": probs.get(a["choice"], a.get("probability")),
            "confidence": a.get("confidence"),
            "probabilities": probs,
        }
    return answers, tokens, cost, "estimated" if estimated else "gateway", data.get("model"), pinned


def run_jev(pk: dict, call: dict, questions: list, key: str, meter: SpendMeter, transport) -> dict:
    state, out = (
        pack.state_text(call, pk["definitions"]),
        {"answers": {}, "input_tokens": 0, "cost_usd": 0.0},
    )
    sources, verified, model = set(), True, None
    for i in range(0, len(questions), pack.QUESTIONS_PER_REQUEST):
        body = jev_request(state, questions[i : i + pack.QUESTIONS_PER_REQUEST], pk["definitions"])
        answers, tokens, cost, source, model, pinned = jev_call(key, meter, body, transport)
        out["answers"].update(answers)
        out["input_tokens"], out["cost_usd"] = out["input_tokens"] + tokens, out["cost_usd"] + cost
        sources.add(source)
        verified = verified and pinned
    return {
        **out,
        "cost_inr": out["cost_usd"] * pack.INR_PER_USD,
        "cost_source": "+".join(sorted(sources)),
        "model_reported": model,
        "version_verified": verified,
    }


def cli_prompt(pk: dict, call: dict, questions: list) -> str:
    qs = [
        {
            "id": q["id"],
            "question": pack.question_text(pk["definitions"], q),
            "options": q["options"],
        }
        for q in questions
    ]
    return (
        pack.state_text(call, pk["definitions"])
        + "\n\nQUESTIONS\n"
        + json.dumps(qs)
        + '\n\nAnswer every question. Reply with only a JSON object {question id: {"label": '
        'one of its options, "probability": your probability of that label, 0 to 1}}.'
    )


def run_cli(arm: str, prompt: str, model: str | None, run) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        last = Path(tmp) / "last.txt"
        cmd = [a.format(last=last) for a in CLI[arm]] + ([MODEL_FLAG[arm], model] if model else [])
        done = run(cmd, input=prompt, capture_output=True, text=True, check=True, timeout=1800)
        text = json.loads(done.stdout)["result"] if arm == "A" else last.read_text()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"arm {arm}: no JSON object in the reply")
    answers = {
        qid: {"label": a["label"], "probability": float(a["probability"])}
        for qid, a in json.loads(match.group(0)).items()
    }
    return {"answers": answers, "input_tokens": None}


def run_deterministic(call: dict, questions: list) -> dict:
    """Arm D (§4.3): length, script mix, counts and keywords; a seeded prior for ranking."""
    segs, text = (
        {s["id"]: s for s in call["segments"]},
        " ".join(s["text"] for s in call["segments"]),
    )
    native = sum(ord(c) > 0x900 for c in text) / max(len(text), 1)
    rng, answers = random.Random(call["id"]), {}  # noqa: S311
    deep = min(1.0, 0.25 + 0.4 * native + 0.35 * (len(segs) >= 20))
    for q in questions:
        qid, focal = q["id"], " ".join(segs[s]["text"] for s in q.get("segment_refs", []))
        if qid == "triage":
            answers[qid] = {
                "label": "deep" if deep >= 0.5 else "cheap",
                "probability": max(deep, 1 - deep),
            }
        elif qid.endswith(":severity"):
            p = rng.random()
            answers[qid] = {
                "label": "major" if p > 0.7 else "none",
                "probability": 0.5 + abs(p - 0.5) / 2,
            }
        elif qid.endswith((":support", ":handling")):
            answers[qid] = {
                "label": "supported" if qid.endswith(":support") else "answered",
                "probability": 0.6,
            }
        else:
            pattern, hit, miss = HINT[q["construct_id"]]
            found = re.search(pattern, focal, re.I) is not None
            answers[qid] = {"label": hit if found else miss, "probability": 0.7 if found else 0.6}
    return {"answers": answers, "input_tokens": 0, "cost_usd": 0.0, "cost_inr": 0.0}


def run_arm(
    arm: str,
    pk: dict,
    request: dict,
    repeat: int,
    *,
    model=None,
    key=None,
    meter=None,
    transport=None,
    run=None,
) -> dict:
    call, questions, started = (
        pk["calls"][request["input_id"]],
        request["questions"],
        time.monotonic(),
    )
    if arm == "J":
        result, model = (
            run_jev(pk, call, questions, key, meter, transport or urllib_transport),
            pack.MODEL,
        )
    elif arm == "D":
        result, model = run_deterministic(call, questions), "deterministic-v1"
    else:
        result = run_cli(arm, cli_prompt(pk, call, questions), model, run or subprocess.run)
        model = model or "cli-default"
    return {
        "arm": arm,
        "model": model,
        "input_id": call["id"],
        "repeat": repeat,
        "input_sha256": pack.sha(json.dumps(call, sort_keys=True).encode()),
        "questions_sha256": pack.sha(json.dumps(questions, sort_keys=True).encode()),
        "screen_flags": pack.screen(call),
        "latency_ms": int((time.monotonic() - started) * 1000),
        **result,
    }
