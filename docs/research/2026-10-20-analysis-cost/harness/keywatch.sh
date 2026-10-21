cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
$PY - <<'PYX'
import common
st, r, _ = common.http_json("https://openrouter.ai/api/v1/credits", headers={"Authorization": "Bearer " + common.key("OPENROUTER_API_KEY")}, retries=0)
credits = ((r or {}).get("data") or {}).get("total_credits") or 0
st2, r2, _ = common.http_json("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent",
    {"contents":[{"role":"user","parts":[{"text":"Reply ok."}]}],"generationConfig":{"maxOutputTokens":5}},
    {"x-goog-api-key": common.key("GEMINI_API_KEY")}, retries=0)
print(f"openrouter_credits={credits} gemini_status={st2}")
raise SystemExit(0 if (credits and credits > 0) or st2 == 200 else 1)
PYX
