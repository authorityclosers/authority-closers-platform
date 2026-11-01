"""Put a synthetic call into Sales X-Ray through the app's own paths, as a sandbox seller.

    inject.py <truth.json> <results-dir> [--path phone|web] [--base URL] [--timeout-min N]
              [--seller ALIAS --tenant ID]

``--seller`` runs the call as another sandbox seller than the script's (when only one
seller has call minutes); the run records both.

- ``phone``: a fake phone speaking the Android app's own capture API, in its order
  (apps/phone/.../CallLogSync.java, CaptureUploadWorker.java, CaptureApi.java): phone book,
  call-log sync, upload terms and standing consent, the lead's call, the recording, the
  attach, then the plan if the server did not start it.
- ``web``: the /analysis/new upload (this call's own tick), then quote and plan.

Never the database. The seller's password comes from the environment only
(SANDBOX_LOGIN_<ALIAS>, injected by ac-infisical-run from Infisical dev /sandbox-logins)
and is never printed. Only the sandbox organisations are allowed. Writes
``<results>/<id>.json``: every step's time, and what the app answered (fictional content).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEV_HOST = "salesxray-dev.authorityclosers.com"
SANDBOX_TENANTS = {
    "3100ddbc-4549-4a5e-85b8-421af6edd588",  # AC Sales Sandbox (dev)
    "37c71e51-22aa-412a-8a0a-fbb589a29e14",  # Fortline Cyber Institute (Sandbox) (dev)
}
NS = uuid.UUID("6f1c2a52-3b7e-4c1e-9d55-0d1f5a9e2b11")  # this lab's id space
ACQ = "/v1/conversation/acquisition/submissions/"


def name_uuid(text: str) -> str:
    """Java's UUID.nameUUIDFromBytes: MD5, version 3, no namespace."""
    digest = bytearray(hashlib.md5(text.encode(), usedforsecurity=False).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def email_for(alias: str) -> str:
    return f"admin+{alias}@authorityclosers.com"


def secret_name(alias: str) -> str:
    return "SANDBOX_LOGIN_" + alias.replace(".", "_").upper()


class Http:
    """One signed-in browser-like session against the dev API on loopback."""

    def __init__(self, base: str, host: str) -> None:
        self.base = base.rstrip("/")
        self.host = host
        self.origin = f"https://{host}"
        self.cookies: dict[str, str] = {}
        self.log: list[dict[str, Any]] = []

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
        ok: tuple[int, ...] = (200, 201, 202, 204),
        timeout: float = 120,
    ) -> tuple[int, Any]:
        target = self.base.split("://", 1)[1]
        conn = http.client.HTTPConnection(target, timeout=timeout)
        head = {
            "Host": self.host,
            "Origin": self.origin,
            "Accept": "application/json",
            "User-Agent": "ac-simulation-lab/1 (fake-phone)",
        }
        if self.cookies:
            head["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        data: bytes | None = None
        if raw is not None:
            data = raw
            head["Content-Type"] = "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode()
            head["Content-Type"] = "application/json"
        head.update(headers or {})
        started = time.monotonic()
        # The API restarts on a deploy: wait up to three minutes for it, as the phone's
        # WorkManager would. Every write here carries an idempotency key or command id.
        for attempt in range(18):
            try:
                conn.request(method, path, body=data, headers=head)
                response = conn.getresponse()
                payload = response.read()
                break
            except (ConnectionRefusedError, ConnectionResetError, http.client.RemoteDisconnected):
                conn.close()
                if attempt == 17:
                    raise
                time.sleep(10)
                conn = http.client.HTTPConnection(target, timeout=timeout)
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                pair = value.split(";", 1)[0]
                name, _, val = pair.partition("=")
                if val:
                    self.cookies[name.strip()] = val.strip()
                else:
                    self.cookies.pop(name.strip(), None)
        conn.close()
        status = response.status
        try:
            parsed: Any = json.loads(payload) if payload else None
        except ValueError:
            parsed = {"_text": payload[:300].decode(errors="replace")}
        self.log.append(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "method": method,
                "path": path.split("?")[0],
                "status": status,
                "ms": round((time.monotonic() - started) * 1000),
            }
        )
        if status not in ok:
            raise Refused(method, path, status, parsed)
        return status, parsed


class Refused(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: Any) -> None:
        detail = body.get("detail") if isinstance(body, dict) else None
        super().__init__(f"{method} {path.split('?')[0]} -> {status} {detail!r}"[:400])
        self.status, self.body = status, body


def sign_in(http_: Http, alias: str, tenant_id: str) -> dict[str, Any]:
    if tenant_id not in SANDBOX_TENANTS:
        raise SystemExit("refused: not a sandbox organisation")
    password = os.environ.get(secret_name(alias))
    if not password:
        raise SystemExit(f"refused: {secret_name(alias)} is not in the environment")
    # Sign-in allows 10 at once and one more a minute (http/rate_limits.py, per address), so
    # a 429 waits for the next token instead of failing the call.
    for attempt in range(12):
        try:
            http_.call(
                "POST", "/v1/auth/password/login", {"email": email_for(alias), "password": password}
            )
            break
        except Refused as error:
            if error.status != 429 or attempt == 11:
                raise
            time.sleep(65)
    del password
    http_.call("POST", "/v1/context", {"tenant_id": tenant_id})
    _, me = http_.call("GET", "/v1/me/workspaces")
    if str(me.get("selected_tenant_id")) != tenant_id:
        raise SystemExit("refused: the sandbox workspace is not selected")
    return {"person_id": me.get("person_id"), "tenant_id": tenant_id}


FROM_STAGE = {
    "S04": "interested",
    "S16": "interested",
    "S24": "meeting_scheduled",
    "S30": "interested",
}
COLD = {"S02", "S19", "S28"}


def pick_lead(
    http_: Http, truth: dict[str, Any], results: Path, skip: set[str]
) -> list[dict[str, Any]]:
    """The seller's own existing leads this call could be with, best first.

    The server takes a phone's recording only for a lead created before the call (and the
    phone dates calls inside work hours), so the lab calls the sandbox's existing leads,
    never-used ones first, in the stage the story starts from."""
    stage = FROM_STAGE.get(truth["id"], "new")
    used = _registry(results)
    taken = {v["lead_id"] for k, v in used.items() if k != truth["id"]}
    # ``stage`` filters by kind (interested also holds the meeting steps); a pipeline's own
    # stage key goes in ``step``.
    # A seller with no unused lead at that step: the interested kind, then a new lead
    # (the run records the stage the lead really started from).
    queries = (
        ["stage=new"] if stage == "new" else [f"step={stage}", "stage=interested", "stage=new"]
    )
    mine = used.get(truth["id"])
    rows: list[dict[str, Any]] = []
    for filter_ in queries:
        query = f"/v1/lead-desk/leads?scope=mine&{filter_}"
        if truth["id"] in COLD:
            query += "&side=cold"
        for offset in (0, 50, 100):
            _, page = http_.call("GET", query + f"&offset={offset}")
            batch = page.get("leads") or page.get("rows") or page.get("items") or []
            rows.extend(batch)
            if len(batch) < 50:
                break
        if any(str(r["lead_id"]) not in taken for r in rows):
            break
    ordered = sorted(rows, key=lambda r: str(r["lead_id"]))
    if mine:
        ordered = [r for r in ordered if str(r["lead_id"]) == mine["lead_id"]] + ordered
    return [r for r in ordered if str(r["lead_id"]) not in taken | skip][:6]


def _registry(results: Path) -> dict[str, Any]:
    file = results / "leads.json"
    return json.loads(file.read_text()) if file.exists() else {}


def _register(results: Path, sid: str, lead: dict[str, Any]) -> None:
    data = _registry(results)
    data[sid] = lead
    (results / "leads.json").write_text(json.dumps(data, indent=1))


IST = timedelta(hours=5, minutes=30)


def scenario_number(scenario_id: str) -> int:
    return int("".join(ch for ch in scenario_id if ch.isdigit()))


def schedule_offset(truth_file: Path, gap_min: float = 3) -> float | None:
    """Minutes after the first slot when this call starts, when the calls run back to back
    (each after the one before ends, plus a gap), so one seller never has two calls at once.
    None when the sibling answer keys are not beside this one."""
    offset = 0.0
    for other in sorted(truth_file.parent.parent.glob("S*/truth.json")):
        data = json.loads(other.read_text(encoding="utf-8"))
        if other == truth_file:
            return offset
        offset += data["duration_seconds"] / 60 + gap_min
    return None


def call_start(
    truth: dict[str, Any],
    hours: dict[str, Any] | None,
    now: datetime,
    offset_min: float | None = None,
) -> datetime:
    """When the call happened: just now inside work hours; outside them, inside the last
    working day's hours (a phone that uploads late), one slot per scenario (``offset_min``
    after the first, or every 14 minutes), so the server sees what a real phone would send.
    The server clock is never touched."""
    seconds = max(1, int(round(truth["duration_seconds"])))
    if not hours or hours.get("inside"):
        return now - timedelta(seconds=seconds + 45)
    days = set(hours.get("days") or range(7))
    local = now + IST
    day = local.date()
    open_h, open_m = (int(x) for x in str(hours.get("start", "10:30")).split(":"))
    close_h, close_m = (int(x) for x in str(hours.get("end", "19:00")).split(":"))
    opening = datetime(day.year, day.month, day.day, open_h, open_m, tzinfo=UTC)
    if day.weekday() not in days or local.replace(tzinfo=UTC) < opening:
        day -= timedelta(days=1)
    while day.weekday() not in days:
        day -= timedelta(days=1)
    first = datetime(day.year, day.month, day.day, open_h, open_m, tzinfo=UTC) + timedelta(
        minutes=20
    )
    last = datetime(day.year, day.month, day.day, close_h, close_m, tzinfo=UTC) - timedelta(
        seconds=seconds + 300
    )
    if offset_min is None:
        offset_min = 14 * (scenario_number(truth["id"]) - 1)
    slot = first + timedelta(minutes=offset_min)
    return min(max(slot, first), last) - IST


def phone_path(
    http_: Http,
    truth: dict[str, Any],
    file: Path,
    run: dict[str, Any],
    results: Path,
    offset_min: float | None = None,
) -> str:
    seconds = max(1, int(round(truth["duration_seconds"])))
    # 1. The phone book, as both CallLogSync and CaptureApi.book() read it.
    _, book = http_.call("GET", "/v1/lead-desk/phone-book")
    started = call_start(truth, book.get("work_hours"), datetime.now(UTC), offset_min)
    stamp = int(started.timestamp() * 1000)
    run["call_started_at"] = started.isoformat()
    identity = (
        f"{book['tenant_id']}:{book['person_id']}" if book.get("organisation_workspace") else ""
    )
    run["book"] = {
        "organisation_workspace": book.get("organisation_workspace"),
        "numbers": len(book.get("numbers", [])),
        "work_hours": book.get("work_hours"),
    }
    # 2. CaptureUploadWorker.gate(): terms and the seller's standing consent.
    _, policy = http_.call("GET", "/v1/conversation/acquisition/upload-policy")
    _, consent = http_.call("GET", "/v1/sales-xray/call-ai/auto-analysis")
    run["consent"] = {
        "state": consent.get("state"),
        "can_start": consent.get("can_start"),
        "terms_match": consent.get("terms_sha256") == policy.get("policy_sha256"),
    }
    standing = bool(
        consent.get("state") == "on"
        and consent.get("can_start")
        and consent.get("terms_sha256") == policy.get("policy_sha256")
    )
    if not standing:
        raise SystemExit(
            "refused: automatic analysis is not on for this seller (the phone would hold)"
        )
    job = str(uuid.uuid5(NS, f"job:{truth['id']}:{stamp}"))
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    auto = {"X-Auto-Capture-Identity": identity, "Idempotency-Key": job}
    # 3. The exact lead call, before any audio (CaptureUploadWorker); the lead is one of the
    # seller's own that existed before the call.
    call: dict[str, Any] | None = None
    tried: list[str] = []
    for row in pick_lead(http_, truth, results, set()):
        _, detail = http_.call("GET", f"/v1/lead-desk/leads/{row['lead_id']}")
        number = detail.get("phone") or row.get("phone")
        tried.append(str(row["lead_id"]))
        if not number:
            continue
        try:
            _, call = http_.call(
                "POST",
                "/v1/lead-desk/recording-call",
                {
                    "command_id": job,
                    "number": number,
                    "started_at": started.isoformat(),
                    "duration_seconds": seconds,
                },
                headers=auto,
            )
        except Refused as error:
            if error.status == 409 and "exactly one" in str(error):
                continue
            raise
        lead_before = detail["lead"]
        run["lead_before"] = {
            "lead_id": str(row["lead_id"]),
            "name": lead_before.get("name"),
            "stage": lead_before.get("stage"),
            "company": lead_before.get("company"),
            "city": lead_before.get("city"),
            "events": len(detail.get("events") or []),
            "meeting": detail.get("meeting"),
        }
        _register(results, truth["id"], {"lead_id": str(row["lead_id"])})
        break
    run["leads_tried"] = tried
    if call is None:
        raise SystemExit("refused: no lead of this seller existed before the call")
    run["recording_call"] = call
    # 4. Call-log sync (READ_CALL_LOG builds) sees the same call: it must not add a second.
    _, logged = http_.call(
        "POST",
        "/v1/lead-desk/phone-log",
        {
            "device_id": str(uuid.uuid5(NS, f"device:{truth['seller']}")),
            "calls": [
                {
                    "log_id": str(stamp),
                    "number": "".join(c for c in number if c.isdigit() or c == "+"),
                    "started_at": started.isoformat(),
                    "duration_seconds": seconds,
                    "direction": "outgoing",
                }
            ],
        },
    )
    run["phone_log"] = {k: logged.get(k) for k in ("logged", "already", "skipped")}
    run["phone_log"]["calls"] = logged.get("calls")
    sid = name_uuid(f"sx-auto:{identity}:{call['event_id']}:0")
    status, _ = http_.call("GET", ACQ + sid, ok=(200, 404))
    run["upload_started"] = datetime.now(UTC).isoformat()
    _, progress = http_.call(
        "PUT",
        ACQ + sid + "/source",
        raw=file.read_bytes(),
        headers={
            **auto,
            "X-Source-SHA256": sha,
            "X-Capture-Source": "android_dialer_pickup",
            "X-Upload-Policy": policy["policy_sha256"],
            "X-Upload-Consent": "standing",
        },
        timeout=900,
    )
    run["upload_accepted"] = datetime.now(UTC).isoformat()
    if progress.get("source_sha256") != sha:
        raise SystemExit("refused: the server holds another file for this call")
    _, attached = http_.call(
        "POST",
        f"/v1/lead-desk/leads/{call['lead_id']}/recordings",
        {
            "command_id": name_uuid(f"sx-auto:{job}:attach:0"),
            "submission_id": sid,
            "call_event_id": call["event_id"],
        },
    )
    run["attached"] = True
    run["sha256"] = sha
    run["lead_id_from_call"] = call["lead_id"]
    return sid


def web_path(http_: Http, truth: dict[str, Any], file: Path, run: dict[str, Any]) -> str:
    _, policy = http_.call("GET", "/v1/conversation/acquisition/upload-policy")
    sid = str(uuid.uuid5(NS, f"web:{truth['id']}:{time.time_ns()}"))
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    run["upload_started"] = datetime.now(UTC).isoformat()
    _, progress = http_.call(
        "PUT",
        ACQ + sid + "/source",
        raw=file.read_bytes(),
        headers={
            "X-Source-SHA256": sha,
            "X-Upload-Policy": policy["policy_sha256"],
            "X-Upload-Consent": "accepted",
        },
        timeout=900,
    )
    run["upload_accepted"] = datetime.now(UTC).isoformat()
    run["sha256"] = sha
    return sid


def accept_plan(http_: Http, sid: str, run: dict[str, Any]) -> None:
    _, plan = http_.call(
        "POST",
        ACQ + sid + "/plan/quote",
        {"report_language": "en"},
        headers={"Idempotency-Key": f"capture-quote:{sid}"},
    )
    run["quote"] = {k: plan.get(k) for k in ("max_cost_paise", "accepted", "estimated_cost_paise")}
    if not plan.get("accepted"):
        http_.call(
            "POST",
            ACQ + sid + "/plan",
            {
                "plan_id": plan["id"],
                "plan_fingerprint": plan["plan_fingerprint"],
                "privacy_revision": plan["privacy_revision"],
                "accepted": True,
            },
            headers={"Idempotency-Key": f"accept-plan:{plan['id']}"},
        )
    run["plan_accepted"] = datetime.now(UTC).isoformat()


def follow(http_: Http, sid: str, run: dict[str, Any], deadline: float) -> dict[str, Any]:
    """Poll like the phone: until a report, a hold or failure, or the deadline."""
    states: list[str] = []
    planned = False
    progress: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, progress = http_.call("GET", ACQ + sid)
        state = f"{progress.get('state')}/{progress.get('local_state')}"
        if not states or states[-1].split("@")[0] != state:
            states.append(f"{state}@{datetime.now(UTC).isoformat(timespec='seconds')}")
        if progress.get("has_report"):
            # A later --collect-only keeps the first time the report was seen (latency).
            run.setdefault("report_at", datetime.now(UTC).isoformat())
            break
        if (
            progress.get("local_state") in {"failed", "cancelled"}
            or progress.get("state") in {"held", "failed", "cancelled", "completed"}
            or progress.get("execution_hold")
        ):
            run["stopped_at"] = datetime.now(UTC).isoformat()
            break
        if (
            not planned
            and not progress.get("automatic_progression")
            and progress.get("local_state") == "completed"
        ):
            accept_plan(http_, sid, run)
            planned = True
        time.sleep(10)
    else:
        run["timed_out"] = True
    run.setdefault("states", states)
    return progress


def collect(http_: Http, sid: str, lead_id: str | None, run: dict[str, Any]) -> None:
    def safe(method: str, path: str) -> Any:
        try:
            return http_.call(method, path, ok=(200,))[1]
        except Refused as error:
            return {
                "_refused": error.status,
                "_detail": (error.body or {}).get("detail")
                if isinstance(error.body, dict)
                else None,
            }

    run["progress"] = safe("GET", ACQ + sid)
    run["report"] = safe("GET", ACQ + sid + "/report")
    run["transcript"] = safe("GET", ACQ + sid + "/transcript")
    run["speaker_map"] = safe("GET", ACQ + sid + "/speaker-map")
    if lead_id:
        run["call_data"] = safe("GET", f"/v1/sales-xray/call-data/leads/{lead_id}")
        run["lead"] = safe("GET", f"/v1/lead-desk/leads/{lead_id}")
    run["ai_changes"] = safe("GET", "/v1/lead-desk/ai-changes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("truth")
    parser.add_argument("results")
    parser.add_argument("--path", choices=("phone", "web"))
    parser.add_argument("--base", default="http://127.0.0.1:8101")
    parser.add_argument("--host", default=DEV_HOST)
    parser.add_argument("--timeout-min", type=float, default=40)
    parser.add_argument("--collect-only", help="a submission id already uploaded")
    parser.add_argument("--seller", help="run as this sandbox seller instead of the script's")
    parser.add_argument("--tenant", help="that seller's sandbox organisation")
    args = parser.parse_args()
    truth_file = Path(args.truth)
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    scripted_seller = truth["seller"]
    if args.seller:
        truth = {**truth, "seller": args.seller, "tenant_id": args.tenant or truth["tenant_id"]}
    path = args.path or truth["path"]
    file = truth_file.parent / truth["file"]
    out = Path(args.results)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{truth['id']}.json"
    run: dict[str, Any] = (
        json.loads(target.read_text()) if args.collect_only and target.exists() else {}
    )
    if run.get("error"):  # what stopped the first follow, kept apart from this collection
        run["first_error"] = run.pop("error")
    run.update(
        {
            "id": truth["id"],
            "path": path,
            "seller": truth["seller"],
            "scripted_seller": scripted_seller,
            "started": datetime.now(UTC).isoformat(),
        }
    )
    http_ = Http(args.base, args.host)
    deadline = time.monotonic() + args.timeout_min * 60
    try:
        run["session"] = sign_in(http_, truth["seller"], truth["tenant_id"])
        if args.collect_only:
            sid = args.collect_only
        elif path == "phone":
            sid = phone_path(http_, truth, file, run, out, schedule_offset(truth_file))
        else:
            sid = web_path(http_, truth, file, run)
        run["submission_id"] = sid
        lead_id = (run.get("recording_call") or {}).get("lead_id")
        follow(http_, sid, run, deadline)
        collect(http_, sid, str(lead_id) if lead_id else None, run)
    except Refused as error:
        run["error"] = str(error)
    except SystemExit as error:
        run["error"] = str(error)
    except OSError as error:  # a dropped connection or timeout: rerun with --collect-only
        run["error"] = f"network: {error}"
    finally:
        run["http"] = http_.log
        run["finished"] = datetime.now(UTC).isoformat()
        with contextlib.suppress(Exception):  # the session ends with the process
            http_.call("POST", "/v1/auth/logout", ok=(200, 204, 401))
        target.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        truth["id"],
        path,
        run.get("submission_id"),
        run.get("error") or "ok",
        run.get("states", [])[-1:],
    )


if __name__ == "__main__":
    sys.exit(main())
