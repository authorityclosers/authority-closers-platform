"""Fire synthetic events at dev, inside a sandbox organisation, and read every effect back.

    triggers.py <tenant_id> <seller> <out.json> [--only burst,dupes,...] [--burst 100]

As the fictional seller, through the app's own endpoints (never the database):

- ``burst``: N new leads inside a minute (assignment rules), then who got them, and the
  badge, alert, bell, Leads "today" and My day numbers before and after;
- ``dupes``: the same number again, in other spellings (+91, 0-trunk, spaces), and a name
  twin with a new number;
- ``calllog``: one phone-log batch of up to 200 calls on the seller's leads (dated inside
  the last working day), sent twice: the second must log nothing new;
- ``uploads``: an upload with a wrong checksum, a missing consent, another seller's
  identity, a non-audio body, and a retried recording-call (must give the same call);
- ``due``: a call-back task due in two minutes, then whether it shows in Soon, the badge,
  the task buckets and the bell when it falls due, and a snooze;
- ``leaving``: the seller turns new leads off mid-day, a small burst follows, nobody routes
  to them, and they turn it back on.

Leads it adds are named "SIM ..." with numbers +91 00000 5xxxx (AC) / 6xxxx (Fortline).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location("sim_inject", Path(__file__).with_name("inject.py"))
assert _spec and _spec.loader
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)

NS = uuid.UUID("0a7e4c3b-5d2f-4e61-8b9a-7c6d5e4f3a21")
LAB_NUMBERS = ("+91000003", "+91000004", "+91000005", "+91000006")
PREFIX = {"3100ddbc-4549-4a5e-85b8-421af6edd588": "5", "37c71e51-22aa-412a-8a0a-fbb589a29e14": "6"}


def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1)


class Lab:
    def __init__(self, tenant_id: str, seller: str, run_tag: str) -> None:
        self.tenant_id, self.seller, self.tag = tenant_id, seller, run_tag
        self.http = inject.Http("http://127.0.0.1:8101", inject.DEV_HOST)
        self.me = inject.sign_in(self.http, seller, tenant_id)

    def get(self, path: str, ok: tuple[int, ...] = (200,)) -> Any:
        try:
            return self.http.call("GET", path, ok=ok)[1]
        except inject.Refused as error:
            return {"_status": error.status, "_detail": _detail(error)}

    def post(
        self, path: str, body: Any, ok: tuple[int, ...] = (200, 201, 202), **kw: Any
    ) -> tuple[int, Any]:
        try:
            return self.http.call("POST", path, body, ok=ok, **kw)
        except inject.Refused as error:
            return error.status, {"_detail": _detail(error)}

    def numbers(self) -> dict[str, Any]:
        """What the seller's screens count right now."""
        badge = self.get("/v1/lead-desk/badge")
        alert = self.get("/v1/lead-desk/alert")
        soon = self.get("/v1/lead-desk/soon")
        bell = self.get("/v1/notifications")
        today = self.get("/v1/lead-desk/leads?scope=mine&created=today")
        # Three different measures, on purpose: Late = past due (open stages); Due today;
        # Follow-ups Overdue = planned before today; the badge's overdue = over an hour late.
        late = self.get("/v1/lead-desk/leads?scope=mine&due=late")
        due_today = self.get("/v1/lead-desk/leads?scope=mine&due=today")
        overdue = self.get("/v1/lead-desk/leads?scope=mine&view=follow_ups&when=overdue")
        tasks = self.get("/v1/lead-desk/tasks")
        my_day = self.get("/v1/lead-desk/my-day")
        return {
            "badge": _strip(badge),
            "alert": _strip(alert),
            "soon": (soon or {}).get("item"),
            # The bell is product updates (/v1/notifications), not lead reminders.
            "bell_unread": _first(bell, ("unread", "unread_count", "count")),
            "leads_created_today": _first(today, ("total", "count")),
            "leads_late": _first(late, ("total", "count")),
            "leads_due_today": _first(due_today, ("total", "count")),
            "follow_ups_overdue": _first(overdue, ("total", "count")),
            # Call-backs are a lead's follow-ups, never on the Tasks list (calling kinds).
            "task_counts": (tasks or {}).get("counts"),
            "my_day": _strip(my_day, depth=1),
        }

    def phone(self, n: int) -> str:
        return f"+91 00000 {PREFIX[self.tenant_id]}{n:04d}"

    def add_lead(self, name: str, phone: str, assign: str = "rules") -> tuple[int, Any, float]:
        started = time.monotonic()
        status, body = self.post(
            "/v1/lead-desk/leads",
            {
                "command_id": str(uuid.uuid5(NS, f"{self.tag}:{name}:{phone}")),
                "name": name,
                "phone": phone,
                "source": "manual",
                "assign": assign,
            },
            ok=(201,),
        )
        return status, body, (time.monotonic() - started) * 1000


def _detail(error: Any) -> Any:
    body = getattr(error, "body", None)
    return body.get("detail") if isinstance(body, dict) else None


def _first(payload: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                return payload[key]
    return None


def _strip(payload: Any, depth: int = 2) -> Any:
    """Numbers and short words only (no names), for the run file."""
    if depth < 0:
        return None
    if isinstance(payload, dict):
        return {
            k: _strip(v, depth - 1)
            for k, v in payload.items()
            if isinstance(v, (int, float, bool))
            or (isinstance(v, (dict, list)) and depth > 0)
            or (isinstance(v, str) and len(v) < 60 and k not in {"lead_name", "name", "phone"})
        }
    if isinstance(payload, list):
        return len(payload)
    return payload


def t_burst(lab: Lab, count: int, start_index: int = 0) -> dict[str, Any]:
    before = lab.numbers()
    latencies: list[float] = []
    statuses: dict[str, int] = {}
    owners: dict[str, int] = {}
    began = time.monotonic()
    for i in range(count):
        n = start_index + i
        status, body, ms = lab.add_lead(f"SIM Burst {lab.tag} {n:03d}", lab.phone(n))
        latencies.append(ms)
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        if status == 201:
            owner = (body.get("lead") or {}).get("owner_name") or "unassigned"
            owners[owner] = owners.get(owner, 0) + 1
        # 100 in a minute: pace to the minute, never faster than the server answers.
        target = began + (i + 1) * 60 / max(count, 1)
        pause = target - time.monotonic()
        if pause > 0:
            time.sleep(pause)
    elapsed = time.monotonic() - began
    time.sleep(5)
    after = lab.numbers()
    return {
        "sent": count,
        "seconds": round(elapsed, 1),
        "statuses": statuses,
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "max_ms": round(max(latencies), 1) if latencies else None,
        "owners": owners,
        "before": before,
        "after": after,
    }


def t_dupes(lab: Lab) -> dict[str, Any]:
    base = 900
    phone = lab.phone(base)
    digits = phone.replace("+91", "").replace(" ", "")
    first = lab.add_lead(f"SIM Dupe {lab.tag}", phone, assign="me")
    original = ((first[1] or {}).get("lead") or {}).get("lead_id")
    tries = {
        "same_number": phone,
        "no_spaces": phone.replace(" ", ""),
        "trunk_zero": "0" + digits,
        "country_no_plus": "91" + digits,
        "dashes": "+91-00000-" + digits[-5:],
    }
    out: dict[str, Any] = {"first": first[0]}
    for label, value in tries.items():
        status, body, _ = lab.add_lead(f"SIM Dupe {lab.tag} {label}", value, assign="me")
        got = ((body or {}).get("lead") or {}).get("lead_id")
        # A 201 may hand back the existing lead: only a new lead id is a duplicate.
        out[label] = {
            "status": status,
            "same_lead": got == original if got else None,
            "detail": (body or {}).get("_detail"),
        }
    twin = lab.add_lead(f"SIM Dupe {lab.tag}", lab.phone(base + 1), assign="me")
    out["name_twin_new_number"] = twin[0]
    match = lab.get(
        "/v1/lead-desk/leads/match?phone=" + phone.replace("+", "%2B").replace(" ", "%20")
    )
    out["match"] = (
        {k: match.get(k) for k in ("found", "yours")} if isinstance(match, dict) else match
    )
    out["duplicates_queue"] = _strip(lab.get("/v1/lead-desk/duplicates", ok=(200,)), depth=1)
    return out


def t_calllog(lab: Lab, size: int = 60) -> dict[str, Any]:
    book = lab.get("/v1/lead-desk/phone-book")
    # The sandbox's own leads only: the lab's leads ("+91 00000 3/4/5/6xxxx") are newer than
    # the working day these calls are dated in, and the server rightly skips those.
    numbers = [
        n for n in book.get("numbers") or [] if not n.replace(" ", "").startswith(LAB_NUMBERS)
    ][:size]
    hours = book.get("work_hours") or {}
    start = inject.call_start({"id": "S01", "duration_seconds": 60}, hours, datetime.now(UTC))
    rows = []
    for i, number in enumerate(numbers):
        at = start + timedelta(seconds=97 * i)
        rows.append(
            {
                "log_id": f"sim-{lab.tag}-{i}",
                "number": number,
                "started_at": at.isoformat(),
                "duration_seconds": (0, 0, 14, 45, 120, 300)[i % 6],
                "direction": ("outgoing", "outgoing", "missed", "incoming", "outgoing", "rejected")[
                    i % 6
                ],
            }
        )
    device = str(uuid.uuid5(NS, f"device:{lab.seller}"))
    out: dict[str, Any] = {"rows": len(rows), "book_numbers": len(book.get("numbers") or [])}
    before = lab.get("/v1/lead-desk/activity/summary")
    for attempt in ("first", "repeat"):
        began = time.monotonic()
        status, body = lab.post(
            "/v1/lead-desk/phone-log", {"device_id": device, "calls": rows}, ok=(200,)
        )
        out[attempt] = {
            "status": status,
            "ms": round((time.monotonic() - began) * 1000),
            **{k: (body or {}).get(k) for k in ("logged", "already", "skipped")},
            "detail": (body or {}).get("_detail"),
        }
    over = (rows * (201 // max(1, len(rows)) + 1))[:201]
    status, body = lab.post(
        "/v1/lead-desk/phone-log", {"device_id": device, "calls": over}, ok=(200,)
    )
    out["over_200"] = {"status": status, "sent": len(over), "detail": (body or {}).get("_detail")}
    out["activity_before"] = _strip(before, depth=1)
    out["activity_after"] = _strip(lab.get("/v1/lead-desk/activity/summary"), depth=1)
    return out


def t_uploads(lab: Lab, audio: Path) -> dict[str, Any]:
    acq = inject.ACQ
    policy = lab.get("/v1/conversation/acquisition/upload-policy")
    data = audio.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    book = lab.get("/v1/lead-desk/phone-book")
    identity = f"{book.get('tenant_id')}:{book.get('person_id')}"
    cases: dict[str, tuple[bytes, dict[str, str]]] = {
        "wrong_checksum": (
            data,
            {
                "X-Source-SHA256": "0" * 64,
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "accepted",
            },
        ),
        "no_consent": (data, {"X-Source-SHA256": sha, "X-Upload-Policy": policy["policy_sha256"]}),
        "old_terms": (
            data,
            {"X-Source-SHA256": sha, "X-Upload-Policy": "a" * 64, "X-Upload-Consent": "accepted"},
        ),
        "other_seller": (
            data,
            {
                "X-Source-SHA256": sha,
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "standing",
                "X-Auto-Capture-Identity": f"{book.get('tenant_id')}:{uuid.uuid4()}",
            },
        ),
        "not_audio": (
            b"this is not audio " * 64,
            {
                "X-Source-SHA256": hashlib.sha256(b"this is not audio " * 64).hexdigest(),
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "accepted",
            },
        ),
        "valid_web": (
            data,
            {
                "X-Source-SHA256": sha,
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "accepted",
            },
        ),
        "valid_standing": (
            data,
            {
                "X-Source-SHA256": sha,
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "standing",
                "X-Auto-Capture-Identity": identity,
            },
        ),
    }
    out: dict[str, Any] = {}
    for label, (body, headers) in cases.items():
        sid = str(uuid.uuid5(NS, f"{lab.tag}:upload:{label}"))
        try:
            status, answer = lab.http.call(
                "PUT", acq + sid + "/source", raw=body, headers=headers, ok=(202,), timeout=300
            )
            out[label] = {"status": status, "state": (answer or {}).get("state")}
        except inject.Refused as error:
            out[label] = {"status": error.status, "detail": _detail(error)}
    # A retried recording-call (same command id) must return the same call.
    leads = lab.get("/v1/lead-desk/leads?scope=mine&stage=new")
    rows = (leads or {}).get("leads") or []
    if rows:
        detail = lab.get(f"/v1/lead-desk/leads/{rows[-1]['lead_id']}")
        hours = book.get("work_hours") or {}
        start = inject.call_start({"id": "S29", "duration_seconds": 30}, hours, datetime.now(UTC))
        command = str(uuid.uuid5(NS, f"{lab.tag}:retry"))
        body = {
            "command_id": command,
            "number": detail.get("phone"),
            "started_at": start.isoformat(),
            "duration_seconds": 30,
        }
        first = lab.post(
            "/v1/lead-desk/recording-call",
            body,
            ok=(200,),
            headers={"X-Auto-Capture-Identity": identity, "Idempotency-Key": command},
        )
        again = lab.post(
            "/v1/lead-desk/recording-call",
            body,
            ok=(200,),
            headers={"X-Auto-Capture-Identity": identity, "Idempotency-Key": command},
        )
        out["recording_call_retry"] = {
            "first": first[0],
            "again": again[0],
            "same_event": (first[1] or {}).get("event_id") == (again[1] or {}).get("event_id"),
        }
        future = {
            **body,
            "command_id": str(uuid.uuid4()),
            "started_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        }
        out["recording_call_future"] = lab.post("/v1/lead-desk/recording-call", future, ok=(200,))[
            0
        ]
        old = {
            **body,
            "command_id": str(uuid.uuid4()),
            "started_at": (datetime.now(UTC) - timedelta(days=5)).isoformat(),
        }
        out["recording_call_5_days_old"] = lab.post("/v1/lead-desk/recording-call", old, ok=(200,))[
            0
        ]
    return out


def t_due(lab: Lab) -> dict[str, Any]:
    status, body, _ = lab.add_lead(f"SIM Due {lab.tag}", lab.phone(950), assign="me")
    lead_id = (body.get("lead") or {}).get("lead_id") if status == 201 else None
    if not lead_id:
        return {"error": status, "detail": (body or {}).get("_detail")}
    due_at = datetime.now(UTC) + timedelta(minutes=2)
    status, task = lab.post(
        f"/v1/lead-desk/leads/{lead_id}/tasks",
        {
            "command_id": str(uuid.uuid5(NS, f"{lab.tag}:due")),
            "kind": "call_back",
            "starts_at": due_at.isoformat(),
            "title": "SIM call back",
        },
        ok=(200, 201),
    )
    out: dict[str, Any] = {
        "task_status": status,
        "due_at": due_at.isoformat(),
        "before_due": lab.numbers(),
    }
    time.sleep(max(0, (due_at - datetime.now(UTC)).total_seconds()) + 70)
    out["after_due"] = lab.numbers()
    task_id = (task or {}).get("task_id") or (task or {}).get("id")
    if task_id:
        out["snooze"] = lab.post(
            f"/v1/lead-desk/tasks/{task_id}/snooze",
            {
                "command_id": str(uuid.uuid5(NS, f"{lab.tag}:snooze")),
                "expected_revision": int((task or {}).get("revision") or 1),
                "choice": "15m",
            },
            ok=(200,),
        )[0]
        out["after_snooze"] = lab.numbers()
    return out


def t_leaving(lab: Lab, count: int = 10) -> dict[str, Any]:
    me_before = _strip(lab.get("/v1/lead-desk/me"), depth=1)
    off = lab.http.call("PUT", "/v1/lead-desk/me/taking", {"taking": False}, ok=(200,))[0]
    burst = t_burst(lab, count, start_index=600)
    on = lab.http.call("PUT", "/v1/lead-desk/me/taking", {"taking": True}, ok=(200,))[0]
    return {"me_before": me_before, "off": off, "burst": burst, "on": on}


def t_intake(lab: Lab) -> dict[str, Any]:
    """The public intake endpoints (website line, Google Ads, capture, Meta webhook) with keys
    and signatures that are wrong or missing: each is refused, and no lead appears. No cookie
    is sent; a sandbox organisation has no live source to aim at, so only refusals are tested."""
    anon = inject.Http(lab.http.base, lab.http.host)
    bogus = "sxw_" + uuid.uuid4().hex[:24]
    page = "https://shop.example.com/contact"
    lead = {"name": "SIM Intake", "phone": lab.phone(990), "email": "sim@example.com"}

    def hit(method: str, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        try:
            status, answer = anon.call(method, path, body, headers=headers or {}, ok=(200, 202))
        except inject.Refused as error:
            status, answer = error.status, error.body
        detail = answer.get("detail") if isinstance(answer, dict) else None
        outcome = answer.get("outcome") if isinstance(answer, dict) else None
        return {"status": status, "detail": detail, "outcome": outcome}

    site = {"Origin": "https://shop.example.com"}
    before = lab.numbers()["leads_created_today"]
    out = {
        "site_no_key": hit("POST", "/v1/lead-desk/site/lead", {"u": page, "fields": lead}, site),
        "site_unknown_key": hit(
            "POST", "/v1/lead-desk/site/lead", {"k": bogus, "u": page, "fields": lead}, site
        ),
        "site_other_page": hit(
            "POST",
            "/v1/lead-desk/site/lead",
            {"k": bogus, "u": page, "fields": lead},
            {"Origin": "https://evil.example.org"},
        ),
        "site_no_page": hit("POST", "/v1/lead-desk/site/lead", {"k": bogus, "fields": lead}, site),
        "site_hello_unknown_key": hit(
            "POST", "/v1/lead-desk/site/hello", {"k": bogus, "u": page}, site
        ),
        "google_no_key": hit(
            "POST",
            f"/v1/lead-desk/capture/{uuid.uuid4()}/google-ads",
            {"lead_id": "x", "is_test": True},
        ),
        "google_unknown_source": hit(
            "POST",
            f"/v1/lead-desk/capture/{uuid.uuid4()}/google-ads",
            {
                "google_key": "not-a-real-key",
                "lead_id": "TeSter-123-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                "is_test": True,
                "user_column_data": [
                    {"column_id": "FULL_NAME", "string_value": "SIM Intake"},
                    {"column_id": "PHONE_NUMBER", "string_value": lab.phone(991)},
                ],
            },
        ),
        "capture_no_key": hit("POST", f"/v1/lead-desk/capture/{uuid.uuid4()}", lead),
        "capture_unknown_key": hit(
            "POST", f"/v1/lead-desk/capture/{uuid.uuid4()}", lead, {"X-Lead-Desk-Key": "bogus-key"}
        ),
        "meta_verify_wrong_token": hit(
            "GET",
            "/v1/lead-desk/meta/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42",
            None,
        ),
        "meta_no_signature": hit(
            "POST",
            "/v1/lead-desk/meta/webhook",
            {
                "object": "page",
                "entry": [
                    {"id": "0", "changes": [{"field": "leadgen", "value": {"leadgen_id": "0"}}]}
                ],
            },
        ),
        "meta_bad_signature": hit(
            "POST",
            "/v1/lead-desk/meta/webhook",
            {"object": "page", "entry": []},
            {"X-Hub-Signature-256": "sha256=" + "0" * 64},
        ),
    }
    out["leads_created_today"] = {"before": before, "after": lab.numbers()["leads_created_today"]}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id")
    parser.add_argument("seller")
    parser.add_argument("out")
    parser.add_argument("--only", default="burst,dupes,calllog,uploads,due,leaving,intake")
    parser.add_argument("--burst", type=int, default=100)
    parser.add_argument("--audio", default="out/S05/S05.m4a")
    parser.add_argument("--tag", default=datetime.now(UTC).strftime("%m%d%H%M"))
    args = parser.parse_args()
    lab = Lab(args.tenant_id, args.seller, args.tag)
    report: dict[str, Any] = {
        "tenant_id": args.tenant_id,
        "seller": args.seller,
        "tag": args.tag,
        "started": datetime.now(UTC).isoformat(),
    }
    runs = {
        "burst": lambda: t_burst(lab, args.burst),
        "dupes": lambda: t_dupes(lab),
        "calllog": lambda: t_calllog(lab),
        "uploads": lambda: t_uploads(lab, Path(args.audio)),
        "due": lambda: t_due(lab),
        "leaving": lambda: t_leaving(lab),
        "intake": lambda: t_intake(lab),
    }
    try:
        for name in args.only.split(","):
            try:
                report[name] = runs[name]()
            except Exception as error:  # noqa: BLE001 - one trigger's failure is its result
                report[name] = {"error": str(error)[:300]}
            print(name, json.dumps(report[name], default=str)[:300], flush=True)
    finally:
        report["http"] = lab.http.log
        report["finished"] = datetime.now(UTC).isoformat()
        with contextlib.suppress(Exception):  # the session ends with the process
            lab.http.call("POST", "/v1/auth/logout", ok=(200, 204, 401))
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1, default=str), "utf-8"
        )


if __name__ == "__main__":
    sys.exit(main())
