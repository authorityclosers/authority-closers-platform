#!/usr/bin/env python3
"""Check one fictional benchmark call folder (plan.json, script.json, facts.json).

Usage: python3 check_call.py calls/<call_id> [more folders...]
Prints OK or a list of errors (exit 1) and warnings. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

CALL_TYPES = {"cold_call", "inbound_followup", "demo", "objection_heavy", "negotiation_close", "lost_deal",
              "callback", "multi_party"}
MIXES = {"en-IN", "hi-en", "mr-en", "hi", "mr", "gu-en"}
FACT_TYPES = {"person_name", "company", "product", "price", "budget", "quantity", "date", "time", "duration",
              "location", "decision_maker", "competitor", "competitor_price", "objection", "commitment", "next_step",
              "timeline", "payment_terms", "discount", "personal_detail", "pain_point", "requirement",
              "contact_preference"}
TRAPS = {None, "self_correction", "alt_number_form", "third_party_name", "competitor_price", "retracted",
         "ambiguous_speaker"}
COACH_KINDS = {"missed_discovery", "talked_over", "no_next_step", "good_objection_handling", "price_too_early",
               "good_rapport", "ignored_buying_signal", "wrong_info_given", "other"}
ROLES = {"salesperson", "prospect", "third_party", "manager", "colleague", "family_member"}

# Real-looking identifiers that must never appear (fictional data only).
PII = {
    "indian mobile number": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "url": re.compile(r"(?:https?://|www\.)\S+", re.I),
    "PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "Aadhaar-like 12 digits": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "GSTIN": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2}\b"),
}
# Well-known public brands/companies: a fictional call must not use them as the seller, prospect or competitor.
BRANDS = ["tata", "reliance", "infosys", "wipro", "hdfc", "icici", "kotak", "axis bank", "sbi", "lic ", "airtel",
          "jio", "vodafone", "mahindra", "bajaj", "godrej", "asian paints", "amazon", "flipkart", "zomato", "swiggy",
          "paytm", "phonepe", "byju", "unacademy", "lodha", "dlf", "hiranandani", "prestige group", "sobha",
          "maruti", "hyundai", "toyota", "samsung", "apple", "google", "microsoft", "salesforce", "zoho", "hubspot",
          "freshworks", "leadsquared", "tally", "adani", "larsen", "l&t", "havells", "voltas", "tanishq", "titan",
          "nykaa", "ola ", "uber", "makemytrip", "oyo", "policybazaar", "cred", "razorpay", "decathlon", "ikea",
          "urban company", "housing.com", "99acres", "magicbricks", "nobroker", "justdial", "indiamart"]


def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def load(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing {path.name}")
    except json.JSONDecodeError as exc:
        errors.append(f"{path.name}: invalid JSON ({exc})")
    return None


def check(folder: Path) -> tuple[list[str], list[str], dict]:
    errors: list[str] = []
    warns: list[str] = []
    plan = load(folder / "plan.json", errors)
    script = load(folder / "script.json", errors)
    facts = load(folder / "facts.json", errors)
    if errors:
        return errors, warns, {}
    cid = plan.get("call_id")
    if cid != folder.name or script.get("call_id") != cid:
        errors.append(f"call_id mismatch: folder {folder.name}, plan {cid}, script {script.get('call_id')}")
    if plan.get("call_type") not in CALL_TYPES:
        errors.append(f"plan.call_type {plan.get('call_type')!r} not in {sorted(CALL_TYPES)}")
    if plan.get("language_mix") not in MIXES:
        errors.append(f"plan.language_mix {plan.get('language_mix')!r} not in {sorted(MIXES)}")
    target = plan.get("target_minutes")
    if not isinstance(target, (int, float)) or not 1 <= target <= 60:
        errors.append("plan.target_minutes must be 1-60")
        target = 10
    speakers = {s.get("id"): s for s in plan.get("speakers", [])}
    if len(speakers) < 2:
        errors.append("need at least 2 speakers")
    for sid, s in speakers.items():
        if s.get("role") not in ROLES:
            errors.append(f"speaker {sid} role {s.get('role')!r} not in {sorted(ROLES)}")
        if not s.get("name"):
            errors.append(f"speaker {sid} has no name")
    if not any(s.get("role") == "salesperson" for s in speakers.values()):
        errors.append("no salesperson speaker")
    if plan.get("call_type") == "multi_party" and len(speakers) < 3:
        errors.append("multi_party needs 3+ speakers")

    turns = script.get("turns", [])
    ids = [t.get("id") for t in turns]
    if len(set(ids)) != len(ids):
        errors.append("duplicate turn ids")
    by_id = {t.get("id"): t for t in turns}
    pos = {tid: i for i, tid in enumerate(ids)}
    words = 0
    used = set()
    for t in turns:
        if t.get("speaker") not in speakers:
            errors.append(f"{t.get('id')}: unknown speaker {t.get('speaker')!r}")
        used.add(t.get("speaker"))
        if not str(t.get("text", "")).strip() or not str(t.get("tts", "")).strip():
            errors.append(f"{t.get('id')}: empty text or tts")
        words += len(str(t.get("tts", "")).split())
    for sid in speakers:
        if sid not in used:
            warns.append(f"speaker {sid} never speaks")
    wpm = words / target if target else 0
    if not 105 <= wpm <= 175:
        (errors if not 80 <= wpm <= 210 else warns).append(
            f"{words} tts words for {target} min = {wpm:.0f} words/min (want 130-150)")

    full = " ".join(norm(str(t.get("text", ""))) + " " + norm(str(t.get("tts", ""))) for t in turns)
    names_blob = norm(json.dumps(plan, ensure_ascii=False))
    for label, rx in PII.items():
        for m in rx.finditer(" ".join(str(t.get("text", "")) + " " + str(t.get("tts", "")) for t in turns)):
            errors.append(f"{label} pattern in script: {m.group(0)!r}")
    for b in BRANDS:
        if re.search(r"(?<![a-z])" + re.escape(b.strip()) + r"(?![a-z])", full + " " + names_blob):
            errors.append(f"real brand/company name used: {b.strip()!r}")

    if not isinstance(facts, list) or not facts:
        errors.append("facts.json must be a non-empty list")
        facts = []
    fids = set()
    needles = 0
    traps = 0
    for f in facts:
        fid = f.get("id")
        if fid in fids:
            errors.append(f"duplicate fact id {fid}")
        fids.add(fid)
        if f.get("type") not in FACT_TYPES:
            errors.append(f"{fid}: type {f.get('type')!r} not allowed")
        if f.get("trap") not in TRAPS:
            errors.append(f"{fid}: trap {f.get('trap')!r} not allowed")
        traps += f.get("trap") is not None
        tids = f.get("turn_ids") or []
        if not tids or any(t not in by_id for t in tids):
            errors.append(f"{fid}: turn_ids {tids} missing or unknown")
            continue
        ev = f.get("evidence")
        if not ev:
            errors.append(f"{fid}: no evidence (copy the exact words from the cited turn's text)")
        else:
            hay = " ".join(norm(str(by_id[t].get("text", ""))) for t in tids)
            if norm(ev) not in hay:
                errors.append(f"{fid}: evidence {ev!r} not found verbatim in text of {tids}")
        if f.get("said_by") not in speakers:
            errors.append(f"{fid}: said_by {f.get('said_by')!r} unknown")
        if not isinstance(f.get("critical"), bool):
            errors.append(f"{fid}: critical must be true/false")
        if f.get("needle"):
            needles += 1
            if len(tids) != 1:
                errors.append(f"{fid}: a needle is mentioned in exactly one turn")
            depth = pos[tids[0]] / max(len(turns) - 1, 1)
            if abs(depth - float(f.get("depth", -1))) > 0.05:
                warns.append(f"{fid}: depth {f.get('depth')} but turn position gives {depth:.2f}")
            # once only: the evidence must not appear in any other turn
            others = [t for t in turns if t.get("id") not in tids and norm(ev or "") and norm(ev) in norm(str(t.get("text", "")))]
            if others:
                errors.append(f"{fid}: needle evidence also appears in {[t['id'] for t in others][:3]}")
    n_min = max(25, int(target))
    if len(facts) < min(n_min, 60):
        errors.append(f"{len(facts)} facts; want >= {min(n_min, 60)} for a {target}-min call")
    if target >= 15 and needles < 2:
        errors.append(f"{needles} needles; calls >= 15 min need 2-4")
    if target >= 6 and traps < 2:
        errors.append(f"{traps} traps; calls >= 6 min need >= 2")
    for k in plan.get("coaching_truths", []):
        if k.get("kind") not in COACH_KINDS:
            errors.append(f"coaching truth {k.get('id')}: kind {k.get('kind')!r}")
        if any(t not in by_id for t in k.get("turn_ids", [])):
            errors.append(f"coaching truth {k.get('id')}: unknown turn ids")
    if not 2 <= len(plan.get("coaching_truths", [])) <= 8:
        errors.append("want 2-6 coaching_truths")
    stats = {"call_id": cid, "est_minutes": round(words / 140, 1), "turns": len(turns), "facts": len(facts),
             "needles": needles, "traps": traps, "words": words}
    return errors, warns, stats


def main() -> int:
    bad = 0
    for arg in sys.argv[1:]:
        errors, warns, stats = check(Path(arg))
        for w in warns:
            print(f"WARN {arg}: {w}")
        if errors:
            bad += 1
            for e in errors[:60]:
                print(f"ERROR {arg}: {e}")
            if len(errors) > 60:
                print(f"ERROR {arg}: ... {len(errors) - 60} more")
        else:
            print(f"OK {arg} {json.dumps(stats, ensure_ascii=False)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
