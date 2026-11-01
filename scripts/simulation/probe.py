"""Can these sandbox sellers capture and analyse calls right now? Read-only.

    probe.py <tenant_id> <alias> [<alias> ...]

Per seller: the workspace, write eligibility, automatic-analysis consent, the call
allowance, work hours. Reads only; passwords come from the environment (see inject.py).
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("sim_inject", Path(__file__).with_name("inject.py"))
assert _spec and _spec.loader
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)


def probe(tenant_id: str, alias: str) -> dict[str, object]:
    http_ = inject.Http("http://127.0.0.1:8101", inject.DEV_HOST)
    out: dict[str, object] = {"seller": alias}
    try:
        inject.sign_in(http_, alias, tenant_id)
        status, _ = http_.call(
            "GET", "/v1/me/sales-xray-profile/write-eligibility", ok=(204, 200, 403, 409, 422)
        )
        out["write_eligible"] = status in (200, 204)
        _, consent = http_.call("GET", "/v1/sales-xray/call-ai/auto-analysis")
        out["consent"] = consent.get("state")
        _, session = http_.call("GET", "/v1/conversation/acquisition/session")
        out["allowance"] = session.get("allowance")
        _, book = http_.call("GET", "/v1/lead-desk/phone-book")
        out["work_hours_inside"] = (book.get("work_hours") or {}).get("inside")
    except (inject.Refused, SystemExit) as error:
        out["error"] = str(error)
    finally:
        with contextlib.suppress(Exception):  # the session ends with the process
            http_.call("POST", "/v1/auth/logout", ok=(200, 204, 401))
    return out


if __name__ == "__main__":
    for name in sys.argv[2:]:
        print(json.dumps(probe(sys.argv[1], name)))
