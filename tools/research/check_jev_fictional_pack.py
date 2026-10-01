#!/usr/bin/env python3
"""Offline fixture integrity and construction checks; never run an evaluation arm."""
import argparse
import copy
import hashlib
import json
import re
import unicodedata as ud
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "docs/research/jev-fictional-pack-v1"
CATEGORIES = "ABCDE"
METRICS = ["eligible_tokens", "native_tokens", "language_switches",
           "script_transitions", "adjacent_token_pairs"]
PINS = {"778a5c39-8b4c-475f-b53b-731ce0e93ddb", "05f6e847-6f55-4d12-b8cb-ef3f9b7486d3",
        "4a3953b2-d8ae-4428-b50d-0f70e3994842"}
def require(ok, message):
    if not ok:
        raise ValueError(message)
def sha(data): return hashlib.sha256(data).hexdigest()
def tokens(text): return "".join(c if ud.category(c)[0] in "LM" else " " for c in text).split()
def switches(values): return sum(a != b for a, b in zip(values, values[1:], strict=False))
def quotas(n): return {c: n // 5 + (i < n % 5) for i, c in enumerate(CATEGORIES)}
def set_hash(files): return sha("".join(f"{p}\0{h}\n" for p, h in sorted(files.items())).encode())
def without_id(call): return {k: v for k, v in call.items() if k != "id"}
def check_quota(counts, n): require(dict(counts) == quotas(n), "turn quotas")
def script(token):
    names = [ud.name(c, "") for c in token if ud.category(c).startswith("L")]
    mapping = {"LATIN": "Latin", "DEVANAGARI": "Devanagari", "GUJARATI": "Gujarati"}
    found = {next((v for k, v in mapping.items() if k in n), "other") for n in names}
    require(len(found) == 1 and "other" not in found, "mixed or unknown token script")
    return next(iter(found))
def coverage(text, labels, category, language):
    ts = tokens(text)
    require(len(ts) == len(labels), "token-label count")
    eligible = []
    for token, (lang, scr) in zip(ts, labels, strict=True):
        if lang == "neutral":
            require(token in ("PERSON", "COMPANY") and scr == "neutral", "undeclared neutral")
        else:
            require(lang in ("EN", language) and scr == script(token), "token intent/script")
            require(lang != "EN" or scr == "Latin", "English script")
            eligible.append((lang, scr))
    langs, scripts = [v[0] for v in eligible], [v[1] for v in eligible]
    native = "Devanagari" if language == "HI" else "Gujarati"
    expected_script = "Latin" if category == "C" else native
    expected = ("EN", "Latin") if category == "A" else (language, expected_script)
    require(bool(eligible) and category in CATEGORIES, "empty/unknown category")
    if category in "ABC":
        require(set(eligible) == {expected}, "monolingual category")
    else:
        counts = Counter(langs)
        require(set(langs) == {"EN", language} and min(counts.values()) >= 3, "bilingual blocks")
        require(.4 <= counts["EN"] / len(langs) <= .6, "bilingual balance")
        require(switches(langs) == 1, "language switches")
        expected = {("EN", "Latin"), (language, native if category == "D" else "Latin")}
        require(set(eligible) == expected, "bilingual scripts")
    return [len(langs), sum(s != "Latin" for s in scripts), switches(langs),
            switches(scripts), len(langs) - 1]
def safe(text, vocabulary):
    require(not re.search(r"(?:\d[\s+().-]*){7,}|@|https?://|www\.|[{}]", text), "unsafe content")
    require(all(t.casefold() in vocabulary for t in tokens(text)), "outside fictional vocabulary")
    require(not re.search(r"<(?!PERSON_\d+>|COMPANY_\d+>)", text), "invalid entity token")
def grouped(segments):
    turns = []
    for seg in segments:
        if turns and turns[-1][0] == seg["turn_id"]:
            require(turns[-1][1] == seg["speaker_id"], "speaker changed inside turn")
            turns[-1][2] += " " + seg["text"]
        else:
            turns.append([seg["turn_id"], seg["speaker_id"], seg["text"]])
    require(len({t[0] for t in turns}) == len(turns), "noncontiguous turn")
    return turns
def check(root):
    def read(path): return json.loads((root / path).read_text())
    manifest = read("MANIFEST.json")
    files = {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob("*")
             if p.is_file() and p.name != "MANIFEST.json"}
    require(files == manifest["files"], "manifest file set/hash")
    require(manifest["checker_sha256"] == sha(Path(__file__).read_bytes()), "checker hash")
    for name, prefixes in [("inputs", ("inputs/", "questions/")), ("truth", ("truth/",))]:
        require(set_hash({p: h for p, h in files.items() if p.startswith(prefixes)}) ==
                manifest["set_hashes"][name], "set hash")
    require(set(read("truth/sources.json")["pins"].values()) >= PINS, "source pins")
    base, red = read("inputs/base.json"), read("inputs/red-team.json")
    truth = read("truth/base.json")
    key, vocabulary = read("truth/red-team-key.json"), set(read("truth/fictional-vocabulary.json"))
    calls = {c["id"]: c for c in base + red}
    require((len(base), len(red), len(key), len(calls)) == (36, 240, 120, 276), "fixture counts")
    require(set(truth) == {c["id"] for c in base}, "base truth IDs")
    for call in calls.values():
        ids, end = {s["id"] for s in call["segments"]}, 0
        require(len(ids) == len(call["segments"]), "segment IDs")
        for seg in call["segments"]:
            require(seg["speaker_id"] in ("seller", "prospect"), "speaker")
            require(end <= seg["start_ms"] < seg["end_ms"] <= call["duration_ms"], "timing")
            end = seg["end_ms"]
            safe(seg["text"], vocabulary)
        require(len(call["report"]["items"]) == 20, "report count")
        for item in call["report"]["items"]:
            safe(item["claim"], vocabulary)
            require(bool(item["segment_refs"]) and set(item["segment_refs"]) <= ids, "evidence")
    receipts, codes = [], set()
    for call in base:
        t, turns = truth[call["id"]], grouped(call["segments"])
        counts, totals = Counter(), [0] * 5
        require(len(turns) >= 5 and len(turns) == len(t["turns"]), "turn mapping")
        for turn, author in zip(turns, t["turns"], strict=True):
            require(turn[0] == author["turn_id"] and sha(turn[2].encode()) ==
                    author["text_sha256"] and bool(author["fact_ids"]), "turn/fact surface")
            counts[author["category"]] += 1
            language = "HI" if call["language_style"] == "hi-en" else "GU"
            values = coverage(turn[2], author["labels"], author["category"], language)
            totals = [a + b for a, b in zip(totals, values, strict=True)]
        expected = {"A": len(turns)} if call["language_style"] == "en" else quotas(len(turns))
        require(dict(counts) == expected, "turn quotas")
        require({s["segment_id"] for s in t["segments"]} ==
                {s["id"] for s in call["segments"]}, "segment truth")
        require(sum(x["error_code"] is not None for x in t["items"]) == 6, "30% mutations")
        for i, (item, target) in enumerate(zip(call["report"]["items"], t["items"], strict=True)):
            require(target["report_path"] == f"report.items[{i}]" and target["segment_refs"] ==
                    item["segment_refs"] and sha(item["claim"].encode()) ==
                    target["claim_sha256"], "report truth")
            codes.add(target["error_code"])
        receipts.append({"id": call["id"], "turns": len(turns), "categories": dict(counts),
                         **dict(zip(METRICS, totals, strict=True))})
    require(len(codes - {None}) == 8, "mutation taxonomy")
    for style in ("en", "hi-en", "gu-en"):
        require(Counter(truth[c["id"]]["size"] for c in base if c["language_style"] == style) ==
                {"short": 4, "medium": 6, "long": 2}, "length bands")
    for situation in range(1, 13):
        twins = [c for c in base if truth[c["id"]]["situation"] == situation]
        def align(c):
            t = truth[c["id"]]
            return (t["facts"], [x["fact_ids"] for x in t["turns"]], t["segments"], c["report"],
                    [(s["id"], s["turn_id"], s["speaker_id"]) for s in c["segments"]])
        require(len(twins) == 3 and align(twins[0]) == align(twins[1]) == align(twins[2]), "twins")
    grid = {(u, f"R{r}", p, lang) for u in "abcd" for r in range(1, 6)
            for p in ("early", "late") for lang in ("en", "hi-en", "gu-en")}
    require({tuple(k[x] for x in ("use", "type", "position", "language")) for k in key} == grid,
            "red-team grid")
    paired, deltas = set(), []
    for pair in key:
        clean, injected = calls[pair["clean_id"]], calls[pair["injected_id"]]
        require(without_id(clean) == without_id(calls[pair["base_id"]]), "clean base")
        expected = copy.deepcopy(clean)
        expected["id"] = injected["id"]
        seg = expected["segments"][2 if pair["position"] == "early" else -2]
        require(seg["id"] == pair["segment_id"] == pair["truth_refs"]["segment_id"], "probe truth")
        seg["text"] += " " + pair["injected_text"]
        require(expected == injected, "injection delta")
        if pair["type"] == "R5":
            require(clean["language_style"] == "en" and any(script(t) != "Latin"
                    for t in tokens(pair["injected_text"])), "R5 native English")
        paired.update([clean["id"], injected["id"]])
        deltas.append({"id": injected["id"],
                       "added_lexical_tokens": len(tokens(pair["injected_text"]))})
    require(len(paired) == 240, "unique pair members")
    return {"base_calls": 36, "report_items": 720, "mutated_items": 216, "red_team_pairs": 120,
            "coverage": receipts, "injection_deltas": deltas, "set_hashes": manifest["set_hashes"]}
def expect_bad(fn):
    try:
        fn()
    except ValueError:
        return
    raise ValueError("negative selftest accepted")
def test_selftest():
    for n, expected in ((5, [1]*5), (6, [2, 1, 1, 1, 1]), (20, [4]*5)):
        check_quota(dict(zip(CATEGORIES, expected, strict=True)), n)
        bad = dict(zip(CATEGORIES, expected, strict=True), A=expected[0] + 1)
        expect_bad(lambda n=n, bad=bad: check_quota(bad, n))
    labels = [["EN", "Latin"]]*3 + [["HI", "Latin"]]*3
    require(coverage("we read notes hum suchi padhein", labels, "E", "HI")[2:4] == [1, 0],
            "romanised language versus script")
    expect_bad(lambda: coverage("we read notes hum suchi padhein", labels, "D", "HI"))
    expect_bad(lambda: coverage("we read notes hum suchi kaagaz par padhein",
                               [["EN", "Latin"]]*3 + [["HI", "Latin"]]*5, "E", "HI"))
    require(switches(["HI", "HI"]) == 0 and switches(["Latin", "Devanagari"]) == 1,
            "same-language script change")
    split = [{"turn_id": "t", "speaker_id": "seller", "text": s} for s in ("we read", "notes")]
    require(len(grouped(split)) == 1, "split turn")
    expect_bad(lambda: safe("Call 9876543210", {"call"}))
    expect_bad(lambda: safe("Meet Alicia at WidgetCorp", {"meet", "at"}))
    expect_bad(lambda: safe("Meet {person}", {"meet", "person"}))
def test_sealed_pack(): check(ROOT)
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.selftest:
        test_selftest()
    result = check(args.root)
    if args.receipt:
        require(not args.receipt.resolve().is_relative_to(args.root.resolve()), "receipt path")
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    summary = {k: v for k, v in result.items() if k not in ("coverage", "injection_deltas")}
    print(json.dumps(summary))
