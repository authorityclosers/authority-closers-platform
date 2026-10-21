"""Build the paper page: site/index.html (template) + site/data/*.json (scores fetched from ac) ->
site/build/sales-xray-analysis-cost.html."""
import json
import pathlib

here = pathlib.Path(__file__).parent
data_dir = here / "data"


def load(name, default):
    p = data_dir / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


asr = load("asr.json", [])
for r in asr:  # keep only what the page uses
    r["per_call"] = [{k: p.get(k) for k in ("call", "min", "tcer", "spk_acc", "lang_mix")} for p in r.get("per_call", [])
                     if not p.get("failed")]
    for k in ("cer", "twer", "crit_kept", "by_lang"):
        r.pop(k, None)
retain = [{k: r.get(k) for k in ("arm", "variant", "retained", "garbled", "by_lang", "critical_facts")} for r in load("retain.json", [])]
lb = [{k: r.get(k) for k in ("arm", "judge", "recall", "critical_recall", "needle_recall", "trap_accuracy", "hallucination",
                             "truth_coverage", "false_claims_per_call", "analysis_inr_per_min", "all_in_inr_per_min")}
      for r in load("leaderboard.json", [])]
fits = load("fits.json", {})
fits.pop("fits", None)
review = load("review.json", {})
data = {"asr": asr, "retain": retain, "leaderboard": lb, "fits": fits, "review": review,
        "consistency": load("consistency.json", []), "bootstrap": load("bootstrap.json", []),
        "bootstrap_same": load("bootstrap_same_input.json", []), "realcalls": load("realcalls.json", []), "realboot": load("realboot.json", []), "round8": load("round8.json", [])}
page = (here / "index.html").read_text(encoding="utf-8").replace("%%DATA%%", json.dumps(data, ensure_ascii=False))
out = here / "build" / "sales-xray-analysis-cost.html"
out.parent.mkdir(exist_ok=True)
out.write_text(page, encoding="utf-8", newline="\n")
print(out, len(page))
