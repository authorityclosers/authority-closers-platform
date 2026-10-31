"""Grade what Sales X-Ray made of a synthetic call against the scenario's answer key.

    grade.py <out-dir with S??/truth.json> <results-dir with S??.json> [--md scorecard.md]

Per scenario:
- the report: present when it should be, held with the right code when it should not
  (the short-call rule: under 60 s of transcript ai_short_call, under 20 s or one side
  under 8 s ai_no_conversation);
- speaker roles: the share of transcript time given to the right side (seller/prospect),
  segments lined up with the truth timeline by time, or by words when there is no time;
- the transcript: word error rate against the script (only when both are in one script);
- extracted facts: precision and recall against the key, in the call data engine's own
  type keys (money with lakh/thousand/k handled, keyword groups, numbers, the outcome);
- the stage and the next follow-up on the lead afterwards;
- latency from the accepted upload to the report.

Pure functions up top (tested in tests/unit/ci/test_simulation_grader.py); I/O at the end.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

IST = timedelta(hours=5, minutes=30)
ROLE_WORDS = {
    "seller": ("seller", "salesperson", "sales", "rep", "agent", "caller", "you", "host", "self"),
    "prospect": ("prospect", "customer", "client", "buyer", "lead", "other", "guest", "callee"),
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_NUMBERS = {
    **{f"{t}-{u}": tv + uv for t, tv in _TENS.items() for u, uv in _UNITS.items()},
    **{f"{t} {u}": tv + uv for t, tv in _TENS.items() for u, uv in _UNITS.items()},
    **_TENS,
    **_TEENS,
    **_UNITS,
}


# ----- text ---------------------------------------------------------------------------


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = re.sub(r"(?<=\w)\.(?=\w)", "", text)  # p.m. -> pm
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return norm(text).split()


def script_of(text: str) -> str:
    """'latin', 'devanagari' or 'mixed' by letters."""
    latin = sum(1 for c in text if "a" <= c.lower() <= "z")
    deva = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    total = latin + deva
    if total == 0:
        return "latin"
    if deva / total > 0.7:
        return "devanagari"
    if latin / total > 0.7:
        return "latin"
    return "mixed"


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate (Levenshtein over tokens), 0.0-1.0+; 1.0 for an empty hypothesis."""
    ref, hyp = tokens(reference), tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h))
        previous = current
    return previous[-1] / len(ref)


# ----- numbers and money --------------------------------------------------------------


def amounts(text: str) -> list[float]:
    """Rupee amounts in free text: '2.5 lakh', '₹2,50,000', '45k', 'forty-five thousand',
    '1.55 L', 'one lakh fifty-five thousand', '3 lakh rupees'."""
    if not text:
        return []
    t = unicodedata.normalize("NFKC", str(text)).casefold().replace("₹", " ").replace("rs.", " ")
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    for word, value in sorted(_WORD_NUMBERS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{re.escape(word)}\b", str(value), t)
    t = re.sub(r"\band a half\b", ".5", t)
    t = re.sub(r"(\d+)\s+\.5", r"\1.5", t)
    found: list[float] = []
    units = {
        "crore": 1e7,
        "cr": 1e7,
        "lakh": 1e5,
        "lakhs": 1e5,
        "lac": 1e5,
        "l": 1e5,
        "thousand": 1e3,
        "k": 1e3,
        "hundred": 1e2,
    }
    # "1 lakh 55 thousand" / "1 lakh 55" (Indian speech) first.
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|l)\b\s*(\d+)\s*(thousand|k)?\b", t):
        found.append(float(m.group(1)) * 1e5 + float(m.group(2)) * 1e3)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(crore|cr|lakhs|lakh|lac|l|thousand|k|hundred)?\b", t):
        value = float(m.group(1))
        unit = m.group(2)
        found.append(value * units[unit] if unit else value)
    return found


def amount_matches(spec: dict[str, Any], text: str, value: Any = None) -> bool:
    candidates = amounts(text)
    if isinstance(value, dict):
        for key in ("amount", "value", "inr", "min", "max", "amount_inr"):
            if isinstance(value.get(key), (int, float)):
                candidates.append(float(value[key]))
    elif isinstance(value, (int, float)):
        candidates.append(float(value))
    targets = [spec["amount"], *spec.get("also", [])]
    for got in candidates:
        if any(abs(got - want) <= 0.05 * want for want in targets):
            return True
        if "low" in spec and spec["low"] * 0.95 <= got <= spec["high"] * 1.05:
            return True
    return False


def number_matches(spec: dict[str, Any], text: str, value: Any = None) -> bool:
    want = spec["number"]
    got = {int(x) for x in amounts(text) if float(x).is_integer()}
    if isinstance(value, dict):
        got |= {int(v) for v in value.values() if isinstance(v, (int, float))}
    elif isinstance(value, (int, float)):
        got.add(int(value))
    return want in got


# ----- facts --------------------------------------------------------------------------


def groups(spec: Any) -> list[list[str]]:
    """['anil'] -> [['anil']]; [['a', 'b'], ['c']] stays."""
    if isinstance(spec, list) and spec and all(isinstance(x, str) for x in spec):
        return [spec]
    return [list(g) for g in spec]


def fact_text(obj: dict[str, Any]) -> str:
    parts = [str(obj.get(k) or "") for k in ("display", "text", "label", "summary")]
    value = obj.get("value")
    if isinstance(value, dict):
        parts += [str(v) for v in value.values() if isinstance(v, (str, int, float))]
    elif value is not None:
        parts.append(str(value))
    return " ".join(p for p in parts if p)


def objects_from(payload: Any) -> list[dict[str, Any]]:
    """Every call-data object (a dict with a type_key) anywhere in an API answer."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            key = node.get("type_key") or node.get("type")
            if (
                isinstance(key, str)
                and "." in key
                and any(k in node for k in ("value", "display", "text"))
            ):
                found.append({**node, "type_key": key})
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(payload)
    seen: set[tuple[str, str]] = set()
    unique = []
    for obj in found:
        mark = (obj["type_key"], fact_text(obj))
        if mark not in seen:
            seen.add(mark)
            unique.append(obj)
    return unique


GRADED_SKIP = {"meeting", "forbid"}


def grade_facts(key: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Recall over the key's items; precision over the extracted objects of the graded
    types (an object counts as right when it matches one of its type's expected items)."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        by_type.setdefault(obj["type_key"], []).append(obj)
    expected = 0
    hit = 0
    right_objects: set[int] = set()
    detail: list[dict[str, Any]] = []
    for type_key, spec in key.items():
        if type_key in GRADED_SKIP:
            continue
        found = by_type.get(type_key, [])
        if isinstance(spec, str):  # enum
            expected += 1
            ok = [
                o
                for o in found
                if spec in norm(fact_text(o)).replace(" ", "_")
                or o.get("value") == spec
                or (isinstance(o.get("value"), dict) and spec in o["value"].values())
            ]
            hit += bool(ok)
            right_objects.update(id(o) for o in ok)
            detail.append(
                {
                    "type": type_key,
                    "want": spec,
                    "ok": bool(ok),
                    "got": [fact_text(o) for o in found][:3],
                }
            )
        elif isinstance(spec, dict):
            expected += 1
            matcher = amount_matches if "amount" in spec else number_matches
            ok = [o for o in found if matcher(spec, fact_text(o), o.get("value"))]
            hit += bool(ok)
            right_objects.update(id(o) for o in ok)
            detail.append(
                {
                    "type": type_key,
                    "want": spec.get("amount", spec.get("number")),
                    "ok": bool(ok),
                    "got": [fact_text(o) for o in found][:3],
                }
            )
        else:
            for group in groups(spec):
                expected += 1
                ok = [o for o in found if any(norm(alt) in norm(fact_text(o)) for alt in group)]
                hit += bool(ok)
                right_objects.update(id(o) for o in ok)
                detail.append(
                    {
                        "type": type_key,
                        "want": group[0],
                        "ok": bool(ok),
                        "got": [fact_text(o) for o in found][:3],
                    }
                )
    graded = [o for o in objects if o["type_key"] in key and o["type_key"] not in GRADED_SKIP]
    forbidden = [o for o in objects if o["type_key"] in set(key.get("forbid", []))]
    for obj in forbidden:
        detail.append(
            {"type": obj["type_key"], "want": "nothing", "ok": False, "got": [fact_text(obj)]}
        )
    judged = len(graded) + len(forbidden)
    correct = sum(1 for o in graded if id(o) in right_objects)
    return {
        "expected": expected,
        "hit": hit,
        "recall": round(hit / expected, 3) if expected else None,
        "precision": round(correct / judged, 3) if judged else None,
        "extracted": len(objects),
        "forbidden": len(forbidden),
        "detail": detail,
    }


# ----- speakers -----------------------------------------------------------------------


def role_of(label: Any, speaker_map: dict[str, str]) -> str | None:
    if label is None:
        return None
    mapped = speaker_map.get(str(label), str(label))
    text = norm(mapped)
    for role, words in ROLE_WORDS.items():
        if any(w in text.split() or text.startswith(w) for w in words):
            return role
    return None


def segments_from(transcript: Any) -> list[dict[str, Any]]:
    """Transcript segments as {start, end, speaker, text} (seconds), whatever the shape."""
    out: list[dict[str, Any]] = []

    def seconds(node: dict[str, Any], *names: str) -> float | None:
        for name in names:
            value = node.get(name)
            if isinstance(value, (int, float)):
                return value / 1000 if name.endswith("_ms") else float(value)
        return None

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text") or node.get("content")
            speaker = next(
                (
                    node[k]
                    for k in ("speaker", "speaker_label", "speaker_id", "role", "label", "who")
                    if k in node
                ),
                None,
            )
            if isinstance(text, str) and speaker is not None and len(text) < 5000:
                out.append(
                    {
                        "start": seconds(node, "start_ms", "start", "start_s", "begin_ms"),
                        "end": seconds(node, "end_ms", "end", "end_s", "finish_ms"),
                        "speaker": speaker,
                        "text": text,
                    }
                )
                return
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(transcript)
    return out


def speaker_roles(speaker_map_payload: Any) -> dict[str, str]:
    """label -> role words from a speaker-map answer, any shape."""
    roles: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            label = node.get("speaker") or node.get("label") or node.get("speaker_label")
            role = node.get("role") or node.get("side") or node.get("name")
            if label is not None and isinstance(role, str):
                roles[str(label)] = role
            for key, value in node.items():
                if isinstance(value, str) and re.fullmatch(
                    r"(spk|speaker)?[ _-]?\w{1,3}", key.casefold()
                ):
                    roles.setdefault(key, value)
                walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(speaker_map_payload)
    return roles


def grade_roles(
    timeline: list[dict[str, Any]],
    turns: list[list[str]],
    segments: list[dict[str, Any]],
    speaker_map: dict[str, str],
) -> dict[str, Any]:
    """The share of transcript time (or words) given to the side that really spoke."""
    truth_role = {"S": "seller", "P": "prospect", "I": "other"}
    right = total = 0.0
    unknown = 0
    labels = {str(s["speaker"]) for s in segments}
    for segment in segments:
        role = role_of(segment["speaker"], speaker_map)
        if role is None:
            unknown += 1
        best, best_score = None, 0.0
        if segment["start"] is not None and segment["end"] is not None and timeline:
            for row in timeline:
                overlap = min(segment["end"], row["end"]) - max(segment["start"], row["start"])
                if overlap > best_score:
                    best, best_score = row["who"], overlap
        else:
            words = set(tokens(segment["text"]))
            for who, said in turns:
                ref = set(tokens(said))
                score = len(words & ref) / (len(words | ref) or 1)
                if score > best_score:
                    best, best_score = who, score
        if best is None or truth_role[best] == "other":
            continue
        weight = max(1, len(tokens(segment["text"])))
        total += weight
        right += weight if role == truth_role[best] else 0
    # Labels with no role word: try the better of the two assignments (A=seller or B=seller).
    if unknown and len(labels) == 2 and total:
        flip = _best_assignment(timeline, turns, segments, sorted(labels))
        return {**flip, "labels": len(labels), "mapped": False}
    return {
        "accuracy": round(right / total, 3) if total else None,
        "labels": len(labels),
        "mapped": unknown == 0,
    }


def _best_assignment(
    timeline: list[dict[str, Any]],
    turns: list[list[str]],
    segments: list[dict[str, Any]],
    labels: list[str],
) -> dict[str, Any]:
    scores = []
    for seller_label in labels:
        mapping = {lab: ("seller" if lab == seller_label else "prospect") for lab in labels}
        scores.append(grade_roles(timeline, turns, segments, mapping)["accuracy"] or 0.0)
    return {"accuracy": round(max(scores), 3), "note": "unnamed labels: best of both assignments"}


# ----- report, stage, follow-up -------------------------------------------------------


def expected_report(truth: dict[str, Any]) -> tuple[bool | None, list[str]]:
    """(report expected?, acceptable hold codes). None: either is fine."""
    expect = truth["expect"]
    seconds = truth.get("duration_seconds") or 0
    if expect.get("report") is False:
        return False, list(expect.get("hold") or ["ai_no_conversation", "ai_short_call"])
    if seconds < 20:
        return False, ["ai_no_conversation", "ai_short_call"]
    if seconds < 60 or expect.get("report") == "short_ok" and seconds < 75:
        return None, ["ai_short_call"]
    if expect.get("report") == "either":
        return None, list(expect.get("hold") or [])
    return True, []


def hold_code(progress: dict[str, Any]) -> str | None:
    for key in ("execution_hold", "failure_code", "hold_code", "reason_code"):
        value = progress.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for inner in ("code", "reason", "failure_code"):
                if isinstance(value.get(inner), str):
                    return value[inner]
    for stage in progress.get("stages") or []:
        if isinstance(stage, dict) and isinstance(stage.get("failure_code"), str):
            return stage["failure_code"]
    return None


def due_check(spec: dict[str, Any] | None, call_at: datetime, due: datetime | None) -> bool | None:
    """Is the lead's next follow-up/meeting where the call said? None: nothing to check."""
    if not spec:
        return None if due is None else None
    if due is None:
        return False
    local, call_local = due + IST, call_at + IST
    ok = True
    if "weekday" in spec:
        ok &= WEEKDAYS[local.weekday()] == spec["weekday"] and local.date() > call_local.date()
    if "day_offset" in spec:
        ok &= (local.date() - call_local.date()).days == spec["day_offset"]
    if "month_day" in spec:
        ok &= [local.month, local.day] == spec["month_day"]
    if spec.get("hour") is not None:
        ok &= local.hour == spec["hour"]
    return bool(ok)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def next_due(lead: dict[str, Any]) -> datetime | None:
    meeting = lead.get("meeting") or {}
    for key in ("at", "starts_at", "start", "scheduled_at"):
        found = parse_time(meeting.get(key)) if isinstance(meeting, dict) else None
        if found:
            return found
    times = []
    for task in lead.get("tasks") or []:
        for key in ("due_at", "due", "at"):
            found = parse_time(task.get(key))
            if found:
                times.append(found)
                break
    row = lead.get("lead") or {}
    for key in ("next_follow_up_at", "follow_up_at", "due_at", "next_at"):
        found = parse_time(row.get(key))
        if found:
            times.append(found)
    return min(times) if times else None


# ----- one scenario -------------------------------------------------------------------


def grade(truth: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    want_report, holds = expected_report(truth)
    progress = run.get("progress") or {}
    has_report = bool(progress.get("has_report"))
    code = hold_code(progress)
    out: dict[str, Any] = {
        "id": truth["id"],
        "title": truth["title"],
        "language": truth["language"],
        "path": run.get("path") or truth["path"],
        "seconds": truth.get("duration_seconds"),
        "error": run.get("error"),
    }
    if run.get("error") and not run.get("submission_id"):
        out["result"] = "blocked"
        return out
    out["report"] = {"want": want_report, "got": has_report, "hold": code}
    report_ok = (
        has_report
        if want_report is True
        else (not has_report and (code in holds or not holds))
        if want_report is False
        else True
    )
    accepted = parse_time(run.get("upload_accepted"))
    reported = parse_time(run.get("report_at") or run.get("stopped_at"))
    out["latency_s"] = (
        round((reported - accepted).total_seconds()) if accepted and reported else None
    )
    segments = segments_from(run.get("transcript"))
    hyp = " ".join(s["text"] for s in segments)
    ref = " ".join(t[1] for t in truth["turns"] if t[0] != "I")
    if segments and script_of(hyp) == script_of(ref):
        out["wer"] = round(wer(ref, hyp), 3)
    else:
        out["wer"] = None
        out["wer_note"] = (
            "no transcript" if not segments else f"script {script_of(hyp)} vs {script_of(ref)}"
        )
    out["roles"] = grade_roles(
        truth.get("timeline") or [], truth["turns"], segments, speaker_roles(run.get("speaker_map"))
    )
    objects = objects_from(run.get("call_data")) + [
        o
        for o in objects_from(run.get("report"))
        if o["type_key"].startswith(("money.", "commitment.", "outcome."))
    ]
    out["facts"] = grade_facts(truth["key"], objects)
    lead = run.get("lead") or {}
    stage = (lead.get("lead") or {}).get("stage")
    out["stage"] = {
        "before": (run.get("lead_before") or {}).get("stage"),
        "after": stage,
        "want": truth["expect"].get("stage"),
        "ok": None
        if not lead or truth["expect"].get("stage_ok") is None
        else stage in truth["expect"]["stage_ok"],
    }
    call_at = parse_time(run.get("call_started_at")) or accepted or datetime.now(UTC)
    out["follow_up"] = {
        "want": truth["expect"].get("follow_up"),
        "ok": due_check(truth["expect"].get("follow_up"), call_at, next_due(lead))
        if lead
        else None,
    }
    log = run.get("phone_log") or {}
    if run.get("path") == "phone":
        out["landing"] = {
            "one_call_on_lead": bool(log.get("already") == 1 and not log.get("logged")),
            "attached": bool(run.get("attached")),
        }
    checks = [report_ok]
    if want_report:
        recall = out["facts"]["recall"]
        checks.append(recall is not None and recall >= 0.6)
        roles = out["roles"]["accuracy"]
        checks.append(roles is not None and roles >= 0.8)
    if out["stage"]["ok"] is not None:
        checks.append(out["stage"]["ok"])
    out["result"] = "pass" if all(checks) else "fail"
    return out


# ----- scorecard ----------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)}%"


def markdown(rows: list[dict[str, Any]]) -> str:
    head = (
        "| Scenario | Path | Length | Result | Report (want/got/hold) | Roles | WER | Facts R/P | "
        "Stage before→after (want) | Follow-up | Latency |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    lines = []
    for r in rows:
        if r["result"] == "blocked":
            lines.append(
                f"| {r['id']} {r['title']} | {r['path']} | {r.get('seconds') or '–'} s | "
                "**blocked** | "
                f"{(r.get('error') or '')[:90]} | | | | | | |"
            )
            continue
        rep = r["report"]
        facts = r["facts"]
        st = r["stage"]
        fu = r["follow_up"]["ok"]
        follow = "–" if fu is None else ("ok" if fu else "wrong")
        lines.append(
            f"| {r['id']} {r['title']} | {r['path']} | {r['seconds']} s | **{r['result']}** | "
            f"{rep['want']}/{rep['got']}/{rep['hold'] or '–'} | {_pct(r['roles']['accuracy'])} | "
            f"{_pct(r['wer']) if r['wer'] is not None else r.get('wer_note', '–')} | "
            f"{_pct(facts['recall'])} / {_pct(facts['precision'])} | "
            f"{st['before']}→{st['after']} ({st['want']}) | {follow} | "
            f"{r['latency_s'] if r['latency_s'] is not None else '–'} s |"
        )
    return head + "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("results")
    parser.add_argument("--md")
    args = parser.parse_args()
    rows = []
    for truth_file in sorted(Path(args.out).glob("S??/truth.json")):
        truth = json.loads(truth_file.read_text(encoding="utf-8"))
        result_file = Path(args.results) / f"{truth['id']}.json"
        if not result_file.exists():
            continue
        rows.append(grade(truth, json.loads(result_file.read_text(encoding="utf-8"))))
    Path(args.results, "grades.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), "utf-8"
    )
    if args.md:
        Path(args.md).write_text(markdown(rows), "utf-8")
    for r in rows:
        print(
            r["id"],
            r["result"],
            json.dumps({k: r.get(k) for k in ("report", "wer", "latency_s")})[:200],
        )


if __name__ == "__main__":
    sys.exit(main())
