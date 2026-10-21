"""Shared plumbing for the analysis-cost benchmark harness (research only, fictional calls only).

- Every paid or free-tier request is appended to ledger.jsonl with provider, model, tokens, audio seconds, list-price
  USD and latency. Nothing else (no prompt, no output) goes to the ledger.
- Budget guard: OpenRouter spend is summed from the ledger and refused above BUDGET_OPENROUTER_USD; other providers
  are free tiers / free credits and capped by request counts per run.
- Keys come from the environment (injected by ac-infisical-run from Infisical dev /sales-xray-bench). They are never
  printed or written anywhere.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("BENCH_ROOT", "/home/acdev/research/analysis-cost-20261020"))
LEDGER = ROOT / "results" / "ledger.jsonl"
BUDGET_OPENROUTER_USD = float(os.environ.get("BENCH_OPENROUTER_BUDGET", "29.0"))  # key limit raised to $30 by the owner (21 Oct), $1 margin

# List prices, USD per 1M tokens (in, out, audio-in) or per audio minute; read live 20 Oct 2026 (paper section 2).
PRICES = {
    "gemini-3.8-flash": (0.75, 3.75, 0.75),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.30),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.50),
    "gemini-2.5-flash-lite": (0.10, 0.40, 0.30),
    "gemini-2.5-flash": (0.30, 2.50, 1.00),
    "anthropic/claude-haiku-5.5": (0.10, 0.50, None),
    "openai/gpt-6-luna": (0.10, 0.50, None),
    "deepseek/deepseek-v4.1-flash": (0.15, 0.60, None),  # first-party off-peak; DeepInfra fp8 0.14/0.42
    "z-ai/glm-5.3-flash": (0.15, 0.50, None),
    "qwen/qwen3.8-flash": (0.15, 0.47, None),
    "xiaomi/mimo-v2.6-flash": (0.14, 0.28, None),
    "openai/gpt-oss-120b": (0.15, 0.60, None),
    "mistralai/mistral-small-2603": (0.15, 0.60, None),
}
PRICES.update({f"google/{k}": v for k, v in list(PRICES.items()) if k.startswith("gemini-")})
STT_PER_MIN = {
    "elevenlabs/scribe_v2": 0.22 / 60,
    "groq/whisper-large-v3-turbo": 0.04 / 60,
    "groq/whisper-large-v3": 0.111 / 60,
    "deepgram/nova-3": 0.0052,
    "assemblyai/universal-2": (0.15 + 0.02) / 60,
    "assemblyai/universal-3-5-pro": (0.21 + 0.02) / 60,
    "sarvam/batch-diarize": 0.0059,
    "local/faster-whisper": 0.0,
}


class BudgetExceeded(RuntimeError):
    pass


def ledger_append(row: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": round(time.time(), 1), **row}
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def spent(provider: str) -> float:
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("provider") == provider:
            total += float(r.get("billed_usd") or r.get("list_usd") or 0)
    return total


def key(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set (run under ac-infisical-run with /sales-xray-bench)")
    return value


def http_json(url: str, body: Any = None, headers: dict[str, str] | None = None, *, method: str | None = None,
              timeout: float = 600, raw: bytes | None = None, retries: int = 4) -> tuple[int, Any, float]:
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
    hdrs = {"Content-Type": "application/json"} if raw is None and body is not None else {}
    hdrs["User-Agent"] = "ac-analysis-cost-research/1.0 (+https://authorityclosers.com)"  # some APIs refuse urllib's default
    hdrs.update(headers or {})
    delay = 5.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data else "GET"))
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode("utf-8")
                return r.status, (json.loads(txt) if txt.strip() else {}), time.time() - t0
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = e.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else delay)
                delay = min(delay * 2, 120)
                continue
            try:
                return e.code, json.loads(txt), time.time() - t0
            except json.JSONDecodeError:
                return e.code, {"error": txt[:500]}, time.time() - t0
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead, ConnectionError) as e:
            if attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            return 0, {"error": str(e)[:300]}, time.time() - t0
    return 0, {"error": "retries exhausted"}, 0.0


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def parse_json_text(text: str) -> Any:
    """Parse a model's JSON answer; tolerate a fenced block or leading prose. Raises ValueError."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise ValueError("not JSON") from None
