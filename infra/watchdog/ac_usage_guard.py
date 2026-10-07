"""Usage guard: keep the company running on included subscriptions, never on paid credits.

Owner orders, 30 Sep and 1 Oct 2026. Every two minutes (systemd timer) it reads both
subscriptions: the Claude CLI login's usage buckets (Anthropic usage endpoint) and the Codex
weekly bucket (from the newest Codex session log on this host; no network call).

Policy:
- Codex (Sol 6.1 / Luna 6) is the preferred engine. Claude-origin seats run on Sol 6.1 xhigh.
- Codex at or above CODEX_ALERT_AT: one board alert per weekly window, asking the owner (via the
  CEO) to use the included "Full reset" before the limit. Paid credits are never used.
- Codex at or above CODEX_FAILOVER_AT, while Claude has headroom: every Codex seat moves to Claude
  (Opus 5.5) so work continues without credits. When Codex is back under CODEX_RETURN_BELOW (its
  weekly reset or a full reset), they move back.
- Claude at or above CLAUDE_DIVERT_AT while Claude-origin seats are on Claude: they move to Sol.
Original adapter type and config are kept in the state file and restored exactly.

Usage:  ac_usage_guard.py check | status | plan | divert | restore
No token, key or config value is ever printed.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

CREDENTIALS = Path("/home/acdev/.claude/.credentials.json")
AUTH = Path("/root/.paperclip/auth.json")
API = "http://127.0.0.1:3100"
COMPANY = "543c7c03-9779-4c06-b9d2-e67f91197265"
STATE = Path("/var/lib/ac-usage-guard/state.json")
LOG = Path("/var/lib/ac-usage-guard/guard.log")
CODEX_SESSIONS = (
    Path("/home/acdev/.codex/sessions"),
    Path(f"/home/acdev/.paperclip/instances/default/companies/{COMPANY}/codex-home/sessions"),
)
ALERT_ISSUE = "AUT-991"
CEO = "5c491a14-d699-477e-a7a6-4535afa5cd64"
CLAUDE_DIVERT_AT = 99
CLAUDE_RETURN_WEEKLY_BELOW = 70
WEEK = 7 * 86400
# 2 Oct pacer: quality-critical Sol seats that move to Claude Opus while Claude is behind its weekly pace.
FLEX_SEATS = {
    "044cc30f-0a4d-4bcb-82e9-1e4e95148664": "Lead Engineer",
    "2c625bb9-1917-43ed-b462-74e30e34f6cf": "Platform Lead Engineer · Sol",
    "f3bf11bf-694f-45a9-8318-d45a041a79d3": "Admin Lead Engineer · Sol",
    "67432044-fe02-4913-a627-9c07db234c75": "Dev Environment Engineer · Sol",
    "10c721cf-7a41-4298-8e6f-342a1eda2a3b": "Billing Engineer · Sol",
}
FLEX_BEHIND = 1000     # owner 3 Oct: Claude is for CEO/CTO decisions, research and visual checks only; no pacing seats onto it
FLEX_AHEAD = 10        # Claude this many points ahead of pace -> flex seats back to Sol
FLEX_CLAUDE_CAP = 85   # never pace above this Claude weekly use
FLEX_MIN_HOURS = 6   # 2 Oct: bring Claude-origin seats home when Claude has room again
CLAUDE_RETURN_SESSION_BELOW = 80
TOKEN_REFRESH_EVERY = 3600
UNREADABLE_ALERT_AFTER = 2 * 3600
CLAUDE_HEADROOM_BELOW = 90
CODEX_ALERT_AT = 90
CODEX_FAILOVER_AT = 1000  # owner 3 Oct: never move Codex seats onto Claude (cold caches burn Claude); alert at 90%, work pauses at the limit
CODEX_RETURN_BELOW = 60
SOL_COMMAND = "/home/acdev/.local/bin/ac-paperclip-codex"
SOL_MODEL = "gpt-6.1-sol"
CLAUDE_COMMAND = "/home/acdev/.local/bin/ac-paperclip-claude"
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_ONLY_KEYS = ("effort", "dangerouslySkipPermissions", "maxTurnsPerRun", "graceSec", "timeoutSec")
CODEX_ONLY_KEYS = ("modelReasoningEffort", "dangerouslyBypassApprovalsAndSandbox")


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}"
    print(line)
    with LOG.open("a") as handle:
        handle.write(line + "\n")


def board_token() -> str:
    return str(next(iter(json.loads(AUTH.read_text())["credentials"].values()))["token"])


def api(method: str, path: str, body: dict | None = None) -> dict | list:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + board_token(), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def claude_usage() -> dict[str, int]:
    oauth = json.loads(CREDENTIALS.read_text()).get("claudeAiOauth") or {}
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": "Bearer " + str(oauth["accessToken"]),
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "ac-usage-guard/2",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
    percents: dict[str, int] = {}
    for limit in body.get("limits") or []:
        kind, percent = limit.get("kind"), limit.get("percent")
        if isinstance(kind, str) and isinstance(percent, (int, float)):
            scope = (limit.get("scope") or {}).get("model") or {}
            name = kind if kind != "weekly_scoped" else f"weekly_{scope.get('display_name', 'scoped')}".lower()
            percents[name] = int(percent)
    percents.setdefault("session", int((body.get("five_hour") or {}).get("utilization") or 0))
    percents.setdefault("weekly_all", int((body.get("seven_day") or {}).get("utilization") or 0))
    resets = (body.get("seven_day") or {}).get("resets_at")
    if isinstance(resets, str):
        try:
            percents["weekly_resets_at"] = int(datetime.fromisoformat(resets.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return percents


CLAUDE_CACHE = Path("/var/lib/ac-usage-guard/claude-usage.json")
CLAUDE_READ_EVERY = 20 * 60  # the endpoint rate-limits frequent reads (429 on a 2-minute timer)
CLAUDE_CACHE_MAX_AGE = 2 * 3600


def keep_token_fresh(state: dict) -> None:
    """The Claude CLI refreshes its own OAuth token when it runs. With every Claude seat on Sol nothing runs, the
    token expires and usage becomes unreadable (2 Oct). One tiny Haiku prompt, at most hourly, keeps it fresh."""
    try:
        oauth = json.loads(CREDENTIALS.read_text()).get("claudeAiOauth") or {}
        expires = float(oauth.get("expiresAt") or 0) / 1000
    except (OSError, ValueError):
        return
    if expires - time.time() > 600 or time.time() - float(state.get("token_refreshed", 0)) < TOKEN_REFRESH_EVERY:
        return
    state["token_refreshed"] = time.time()
    done = subprocess.run(
        ["sudo", "-u", "acdev", "-H", "bash", "-lc",
         "export PATH=/home/acdev/.local/bin:/home/acdev/.local/opt/node/bin:$PATH; "
         "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; cd /tmp && "
         "timeout 120 claude -p 'Reply with the single word OK.' --model claude-haiku-4-5-20251001 --max-turns 1"],
        capture_output=True, text=True, timeout=180)
    log(f"Claude token refresh: {'ok' if done.returncode == 0 else 'failed ' + done.stderr.strip()[-120:]}")


def claude_usage_cached(now: float | None = None) -> dict[str, int]:
    """Claude usage, read live at most every CLAUDE_READ_EVERY; on an error the last good reading
    (under CLAUDE_CACHE_MAX_AGE) stands. Raises only when there is no usable reading at all."""

    now = time.time() if now is None else now
    try:
        cached = json.loads(CLAUDE_CACHE.read_text())
    except (OSError, ValueError):
        cached = {}
    age = now - float(cached.get("at", 0))
    if cached.get("usage") and age < CLAUDE_READ_EVERY:
        return dict(cached["usage"])
    try:
        usage = claude_usage()
    except (OSError, KeyError, ValueError, urllib.error.URLError) as error:
        if cached.get("usage") and age < CLAUDE_CACHE_MAX_AGE:
            log(f"Claude usage read failed ({type(error).__name__}); using the reading from {int(age // 60)} min ago")
            return dict(cached["usage"])
        raise
    CLAUDE_CACHE.write_text(json.dumps({"at": now, "usage": usage}))
    return usage


def codex_usage() -> dict:
    """The newest Codex weekly snapshot from this host's session logs: used %, reset time, credits."""

    files = sorted(
        (p for root in CODEX_SESSIONS if root.exists() for p in root.rglob("rollout-*.jsonl")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:8]
    best: dict = {}
    for path in files:
        for line in path.open(encoding="utf-8", errors="replace"):
            if '"rate_limits"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            limits = (row.get("payload") or {}).get("rate_limits") or {}
            for window in (limits.get("primary") or {}, limits.get("secondary") or {}):
                if window.get("window_minutes") == 10080 and window.get("used_percent") is not None:
                    at = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp()
                    if at > best.get("at", 0):
                        best = {
                            "at": at,
                            "used": float(window["used_percent"]),
                            "resets_at": window.get("resets_at"),
                            "credits": (limits.get("credits") or {}).get("balance"),
                        }
    return best


def state() -> dict:
    value = json.loads(STATE.read_text()) if STATE.exists() else {}
    value.setdefault("diverted", {})        # Claude-origin seats now on Sol
    value.setdefault("codex_diverted", {})  # Codex-origin seats now on Claude
    value.setdefault("since", None)
    value.setdefault("alerted_reset", None)
    return value


def save(value: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(value, indent=1))


def sol_config(config: dict) -> dict:
    result = copy.deepcopy(config)
    for key in CLAUDE_ONLY_KEYS:
        result.pop(key, None)
    result.update(command=SOL_COMMAND, model=SOL_MODEL, modelReasoningEffort="xhigh",
                  dangerouslyBypassApprovalsAndSandbox=True)
    result.setdefault("paperclipSkillSync", {"desiredSkills": ["paperclipai/paperclip/paperclip"]})
    result.setdefault("cwd", "/home/acdev/src/authority-closers-platform")
    return result


def claude_config(config: dict) -> dict:
    result = copy.deepcopy(config)
    for key in CODEX_ONLY_KEYS:
        result.pop(key, None)
    result.update(command=CLAUDE_COMMAND, model=CLAUDE_MODEL, effort="high", dangerouslySkipPermissions=True)
    result.setdefault("cwd", "/home/acdev/src/authority-closers-platform")
    return result


def raw_configs() -> dict[str, dict]:
    """Adapter configs straight from Paperclip's database. The API redacts secret-looking env values
    (2 Oct: a move through the API dropped a seat's test database settings)."""
    try:
        import psycopg
        dsn = json.loads(Path("/home/acdev/.paperclip/instances/default/config.json").read_text())["database"]["connectionString"]
        with psycopg.connect(dsn) as conn:
            return {str(r[0]): r[1] or {} for r in conn.execute(
                "select id, adapter_config from agents where company_id = %s", (COMPANY,)).fetchall()}
    except Exception as error:  # noqa: BLE001 - fall back to the API copy (sanitized on write)
        log(f"raw configs unavailable: {type(error).__name__}")
        return {}


def agents_of(adapter: str) -> list[dict]:
    rows = api("GET", f"/api/companies/{COMPANY}/agents")
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    chosen = [a for a in rows if a.get("adapterType") == adapter and a.get("status") != "terminated"]
    raw = raw_configs() if chosen else {}
    for agent in chosen:
        if agent["id"] in raw:
            agent["adapterConfig"] = raw[agent["id"]]
    return chosen


PLAIN_ENV = {"LD_LIBRARY_PATH": "/home/acdev/.local/lib/playwright-deps"}


def sanitized(config: dict) -> dict:
    """A config Paperclip will store: redacted env placeholders become known plain values or are dropped."""
    out = dict(config)
    env = dict(out.get("env") or {})
    for key, value in list(env.items()):
        if isinstance(value, dict) and value.get("value") == "***REDACTED***":
            if key in PLAIN_ENV:
                env[key] = {"type": "plain", "value": PLAIN_ENV[key]}
            else:
                log(f"dropped redacted env {key} while moving a seat")
                del env[key]
    if env:
        out["env"] = env
    else:
        out.pop("env", None)
    return out


def move(agent_id: str, adapter: str, config: dict) -> None:
    api("PATCH", f"/api/agents/{agent_id}", {"adapterType": adapter, "adapterConfig": sanitized(config),
                                              "replaceAdapterConfig": True})


def claude_seats_to_sol(current: dict, reason: str) -> list[str]:
    moved = []
    for agent in agents_of("claude_local"):
        if agent["id"] in current["diverted"] or agent["id"] in (current.get("flex") or {}):
            continue
        current["diverted"][agent["id"]] = {"name": agent["name"], "adapterType": "claude_local",
                                            "adapterConfig": agent.get("adapterConfig") or {}}
        move(agent["id"], "codex_local", sol_config(agent.get("adapterConfig") or {}))
        moved.append(agent["name"])
    if moved:
        current["since"] = time.time()
        log(f"Claude seats to Sol 6.1 ({reason}): {', '.join(moved)}")
    return moved


def claude_seats_home(current: dict, reason: str) -> list[str]:
    restored = []
    for agent_id, original in list(current["diverted"].items()):
        move(agent_id, original["adapterType"], original["adapterConfig"])
        restored.append(original["name"])
        del current["diverted"][agent_id]
    if restored:
        log(f"Claude seats back on Claude ({reason}): {', '.join(restored)}")
    return restored


def codex_seats_to_claude(current: dict, reason: str) -> list[str]:
    moved = []
    for agent in agents_of("codex_local"):
        if agent["id"] in current["diverted"] or agent["id"] in current["codex_diverted"]:
            continue
        current["codex_diverted"][agent["id"]] = {"name": agent["name"], "adapterType": "codex_local",
                                                  "adapterConfig": agent.get("adapterConfig") or {}}
        move(agent["id"], "claude_local", claude_config(agent.get("adapterConfig") or {}))
        moved.append(agent["name"])
    if moved:
        log(f"Codex seats to Claude ({reason}): {', '.join(moved)}")
    return moved


def codex_seats_home(current: dict, reason: str) -> list[str]:
    restored = []
    for agent_id, original in list(current["codex_diverted"].items()):
        move(agent_id, original["adapterType"], original["adapterConfig"])
        restored.append(original["name"])
        del current["codex_diverted"][agent_id]
    if restored:
        log(f"Codex seats back on Codex ({reason}): {', '.join(restored)}")
    return restored


def alert(text: str) -> None:
    issue = api("GET", f"/api/issues/{ALERT_ISSUE}")
    if not isinstance(issue, dict) or not issue.get("id"):
        log(f"alert not posted: {ALERT_ISSUE} not found")
        return
    body = f"**Usage guard (ac server):**\nDecision needed: {text}"
    api("POST", f"/api/issues/{issue['id']}/comments", {"body": body})
    log(f"alert posted on {ALERT_ISSUE}")


def pace_target(resets_at: float | None, now: float | None = None) -> float | None:
    """Percent of the weekly window already elapsed (what an even spend would have used by now)."""
    if not resets_at:
        return None
    now = time.time() if now is None else now
    return max(0.0, min(100.0, 100.0 * (1 - (float(resets_at) - now) / WEEK)))


def pace_steps(claude: dict, codex: dict, current: dict, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    c_target, x_target = pace_target(claude.get("weekly_resets_at"), now), pace_target(codex.get("resets_at"), now)
    c_used, x_used = claude.get("weekly_all"), codex.get("used")
    if c_target is None or x_target is None or c_used is None or x_used is None:
        return []
    flex = current.get("flex") or {}
    if not flex:
        if (c_used + FLEX_BEHIND <= c_target and x_used >= x_target - 5 and c_used < FLEX_CLAUDE_CAP
                and claude.get("session", 100) < 70 and not current.get("codex_diverted")):
            return ["flex_to_claude"]
        return []
    dwell = now - float(current.get("flex_since") or 0)
    if c_used >= 90:
        return ["flex_home"]
    if dwell >= FLEX_MIN_HOURS * 3600 and (c_used >= c_target + FLEX_AHEAD or c_used >= FLEX_CLAUDE_CAP
                                           or x_used + 20 <= x_target):
        return ["flex_home"]
    return []


def flex_to_claude(current: dict, reason: str) -> list[str]:
    moved = []
    current.setdefault("flex", {})
    for agent in agents_of("codex_local"):
        if agent["id"] not in FLEX_SEATS or agent["id"] in current["flex"] or agent["id"] in current["codex_diverted"]:
            continue
        current["flex"][agent["id"]] = {"name": agent["name"], "adapterType": "codex_local",
                                        "adapterConfig": agent.get("adapterConfig") or {}}
        move(agent["id"], "claude_local", claude_config(agent.get("adapterConfig") or {}))
        moved.append(agent["name"])
    if moved:
        current["flex_since"] = time.time()
        log(f"Pacer: Sol seats to Claude Opus ({reason}): {', '.join(moved)}")
    return moved


def flex_home(current: dict, reason: str) -> list[str]:
    restored = []
    for agent_id, original in list((current.get("flex") or {}).items()):
        move(agent_id, original["adapterType"], original["adapterConfig"])
        restored.append(original["name"])
        del current["flex"][agent_id]
    if restored:
        log(f"Pacer: seats back on Sol ({reason}): {', '.join(restored)}")
    return restored


def decide(claude: dict[str, int], codex: dict) -> list[str]:
    """What the guard would do now, as plain steps (also used by `plan`)."""

    current = state()
    claude_peak = max(claude.get("session", 0), claude.get("weekly_all", 0))
    codex_used = codex.get("used")
    steps = []
    if codex_used is not None and codex_used >= CODEX_FAILOVER_AT and claude.get("weekly_all", 100) < CLAUDE_HEADROOM_BELOW:
        if current["diverted"]:
            steps.append("claude_seats_home")
        steps.append("codex_seats_to_claude")
    elif codex_used is not None and codex_used < CODEX_RETURN_BELOW and current["codex_diverted"]:
        steps.append("codex_seats_home")
    elif claude_peak >= CLAUDE_DIVERT_AT and (codex_used is None or codex_used < CODEX_FAILOVER_AT):
        if current.get("flex"):
            steps.append("flex_home")
        steps.append("claude_seats_to_sol")
    elif (current["diverted"] and claude and claude.get("weekly_all", 100) < CLAUDE_RETURN_WEEKLY_BELOW
          and claude.get("session", 100) < CLAUDE_RETURN_SESSION_BELOW):
        steps.append("claude_seats_home")  # 2 Oct: limits reset; the seats must not stay on Sol forever
    reset, alerted_reset = codex.get("resets_at"), current["alerted_reset"]
    same_window = reset == alerted_reset or (
        isinstance(reset, (int, float)) and isinstance(alerted_reset, (int, float))
        and abs(reset - alerted_reset) <= 3600
    )
    if codex_used is not None and codex_used >= CODEX_ALERT_AT and not same_window:
        steps.append("alert")
    if not any(step in steps for step in ("claude_seats_to_sol", "codex_seats_to_claude", "flex_home")):
        steps += pace_steps(claude, codex, current)
    return steps


def check(apply: bool = True) -> None:
    current_state = state()
    if apply:
        keep_token_fresh(current_state)
        save(current_state)
    try:
        claude = claude_usage_cached()
        current_state["claude_read_ok"] = time.time()
    except (OSError, KeyError, ValueError, urllib.error.URLError) as error:
        log(f"Claude usage read failed: {type(error).__name__}")
        claude = {}
        last_ok = float(current_state.get("claude_read_ok") or current_state.get("since") or time.time())
        if apply and time.time() - last_ok > UNREADABLE_ALERT_AFTER and \
                time.time() - float(current_state.get("unreadable_alerted", 0)) > 12 * 3600:
            current_state["unreadable_alerted"] = time.time()
            alert(f"Claude usage has been unreadable for {int((time.time() - last_ok) // 3600)} h, so the guard cannot "
                  f"move seats between Claude and Sol safely ({len(current_state['diverted'])} Claude seats on Sol). "
                  "Root Operator: check the server's Claude login.")
    if apply:
        save(current_state)
    codex = codex_usage()
    steps = decide(claude, codex)
    summary = (" ".join(f"claude.{k}={v}%" for k, v in sorted(claude.items()))
               + f" codex.weekly={codex.get('used')}% credits={codex.get('credits')}")
    if not apply:
        print(f"{summary}\nplan: {steps or ['nothing']}")
        return
    current = state()
    reason = f"usage {summary}"
    for step in steps:
        if step == "alert":
            alert(f"Codex weekly usage is at {codex.get('used'):.0f}% (resets {codex.get('resets_at')}). "
                  "Owner: use the included Full reset in ChatGPT → Settings → Usage before it reaches "
                  "100%. At 100% Codex work pauses until the weekly reset. Paid credits are not used.")
            current["alerted_reset"] = codex.get("resets_at")
        else:
            globals()[step](current, reason)
    save(current)
    if not steps:
        print(f"ok {summary} claude_on_sol={len(current['diverted'])} codex_on_claude={len(current['codex_diverted'])}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    current = state()
    if command == "check":
        check()
    elif command == "plan":
        check(apply=False)
    elif command == "divert":
        claude_seats_to_sol(current, "manual")
        save(current)
    elif command == "restore":
        claude_seats_home(current, "manual")
        save(current)
    elif command == "status":
        try:
            claude = claude_usage_cached()
        except (OSError, KeyError, ValueError, urllib.error.URLError) as error:
            claude = {"unavailable": type(error).__name__}
        print(json.dumps({
            "claude_seats_on_sol": sorted(v["name"] for v in current["diverted"].values()),
            "codex_seats_on_claude": sorted(v["name"] for v in current["codex_diverted"].values()),
            "claude": claude,
            "codex": codex_usage(),
        }, indent=1))
    else:
        raise SystemExit("usage: ac_usage_guard.py check|plan|status|divert|restore")


if __name__ == "__main__":
    main()
