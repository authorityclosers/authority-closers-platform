#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""Fictional HTTP/worker lifecycle fixture on the isolated AWS rehearsal host only."""

import argparse
import json
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONTAINER = "ac-rehearsal-postgres-1"


def sql(db, statement):
    if not db.startswith("cutover_fixture_"):
        raise ValueError("fixture database required")
    r = subprocess.run(
        [
            "nice",
            "-n",
            "19",
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-euc",
            'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1" -At -v ON_ERROR_STOP=1',  # noqa: E501 -- literal SQL or fixed remote shell script
            "fixture",
            db,
        ],
        input=statement.encode(),
        capture_output=True,
        check=False,
    )
    if r.returncode:
        raise RuntimeError("fixture SQL failed")
    return r.stdout


def serve(db, port):
    state = {"held": True, "drained": True, "active": 0, "failed": False}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            action = self.path.strip("/")
            ok = True
            if action == "hold":
                state["held"] = True
            elif action == "drain":
                state["drained"] = True
                deadline = time.monotonic() + 20
                while state["active"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                ok = not state["active"] and not state["failed"]
            elif action == "fence":
                ok = (
                    state["held"]
                    and state["drained"]
                    and not state["active"]
                    and not state["failed"]
                )
            elif action in {"start-held", "held-canary"}:
                ok = state["held"] and state["drained"]
                if ok:
                    sql(db, "SELECT 1;")
            elif action == "open":
                state.update(held=False, drained=False)
            elif action == "canary":
                ok = not state["held"]
                if ok:
                    sql(db, "SELECT count(*) FROM cutover_writes;")
            elif action == "write":
                ok = not state["held"]
                if ok:
                    sql(
                        db,
                        "INSERT INTO cutover_writes(note) VALUES ('fictional AWS window write');",
                    )
            elif action == "job":
                ok = not state["held"] and not state["drained"]
                if ok:
                    with lock:
                        state["active"] += 1

                    def job():
                        try:
                            time.sleep(8)
                            sql(
                                db,
                                "INSERT INTO cutover_writes(note) VALUES ('fictional drained job');",  # noqa: E501 -- literal SQL or fixed remote shell script
                            )
                        except Exception:
                            state["failed"] = True
                        finally:
                            with lock:
                                state["active"] -= 1

                    threading.Thread(target=job).start()
            else:
                ok = False
            self.send_response(200 if ok else 503)
            self.end_headers()
            self.wfile.write(json.dumps({"ok": ok, "database": db}).encode())

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["serve", "hook"])
    p.add_argument("--database", required=True)
    p.add_argument("--port", required=True, type=int)
    p.add_argument("--operation")
    p.add_argument("--container", default="ac-rehearsal-postgres-1")
    args = p.parse_args()
    if not (Path.home() / "rehearsal/FICTIONAL-ONLY").is_file() or not args.database.startswith(
        "cutover_fixture_"
    ):
        raise ValueError("fictional marker and DB required")
    if args.container != "ac-rehearsal-postgres-1" and not args.container.startswith(
        "ac-cutover-fixture-"
    ):
        raise ValueError("fixture container required")
    global CONTAINER
    CONTAINER = args.container
    if args.action == "serve":
        serve(args.database, args.port)
    else:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{args.port}/{args.operation}", timeout=30
        ) as r:
            if r.status != 200 or json.load(r).get("database") != args.database:
                raise ValueError("fixture refused")


if __name__ == "__main__":
    main()
