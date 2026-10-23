#!/usr/bin/env python3
"""Move one organisation from a separate Pulse install into the shared Pulse, in one transaction.

Owner order, 23 Oct 2026 (~06:20 IST, relayed by the orchestrator): bring Authority Closers' own Pulse
(ac, pulse.authorityclosers.com) into the real Pulse (EA's production Pulse on ea) as its own organisation.
This carries out Pulse's gated plan docs/ops/ORG-MOVE.md steps 3 to 6 (its tools/org-move.py only plans).
Owner-approved data change (AGENTS.md, OWNER-APPROVED DATA CHANGES): dry run by default, before and after
printed, one transaction, audited with the approver, the issue and the owner's words; on apply, a pg_dump of
the target first.

  export   (on the source server, root): one read-only snapshot of the organisation into a bundle directory:
           bundle.sql (COPY blocks) and manifest.json (migrations, each table's columns and row count, sha256).
  import   (on the target server, root): the bundle in one transaction. Dry run = rolled back.
  verify   (target, read-only): row counts and the isolation read as the API role, after an apply.
  census   (any Pulse, read-only): rows per organisation in every organisation table (for before/after diffs).

What moves: the organisation row and its handle, and every row with its org_id in every organisation table
(the tables with org_id and forced row-level security in pulse, pulse_priv and privacy, found from the
catalogue at run time). What stays: the install row, the source's copy of its licence (the target keeps the
register), sessions, sign-in rate counters and used sign-in links. Password records and two-step state
(pulse.login_credential, pulse_priv.auth_account) move only with --carry-passwords: their hashes are copied as
they are, never read, set or printed.

How the rows load: with triggers paused (session_replication_role = replica, like pg_restore
--disable-triggers), so no notification, derived row or timestamp fires; unique keys stay enforced, so a
clashing id aborts everything. UUIDs are kept. Sequence and identity columns (pulse.event.seq and tx_id,
pulse.chat_event.seq, privacy.access_log.id) take fresh numbers from the target, in their original order; the
export refuses if a foreign key points at one of them. Projection cursors restart at 0 (the events were
renumbered). Then, with triggers on (Pulse's own audit records them): the address row, an account link, the
licence register's hosting, and one audit_event. Before commit, table by table: the row count must equal the
manifest and every foreign key from the organisation's rows must resolve; otherwise it raises and nothing stays.

Run (as root; it uses docker):
  python3 pulse-org-move.py export --org authority-closers --out /root/ac-org-move/<run>
  python3 pulse-org-move.py import --bundle <dir> --exec "docker exec -i ea-postgres" --db-user ea_admin \\
      --host pulse.authorityclosers.com --link suyash=<person uuid> --licence-central            # dry run
  ... import ... --apply --approver "Suyash Kulkarni (owner)" --issue "<card>" --words "approve data change: ..."
"""

# ruff: noqa: E501, S603, S607, S608
# An operator's SQL tool: statements are built from catalogue names (qname/qcol) and quoted values (lit),
# and psql/docker are the operator's own binaries, so the SQL-injection and subprocess rules don't fit.
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

SCHEMAS = ("pulse", "pulse_priv", "privacy")
SCRIPT = "scripts/data-changes/pulse-org-move.py"
APP = "pulse-org-move"
# Organisation tables that never move: install-level, the platform's register, and short-lived sign-in state.
EXCLUDE = {
    "pulse.install": "install row: the target keeps its own install company",
    "pulse_priv.pulse_licence": "licence register: kept by the platform organisation in the target",
    "pulse.login_session": "sessions: everyone signs in again at the new home",
    "pulse.auth_rate": "sign-in rate counters: short-lived",
    "pulse_priv.auth_link": "sign-in and reset links: used or expired; new ones come from the target",
}
CREDENTIALS = {
    "pulse.login_credential": "password records (bcrypt hashes)",
    "pulse_priv.auth_account": "two-step state",
}
# Columns the target fills itself although they are not sequences: the transaction id of an event.
FRESH_EXTRA = {"pulse.event": ("tx_id",)}
# Rows rewritten on the way: projection cursors restart, because event numbers change.
TRANSFORM = {
    "pulse.projection_cursor": {"last_tx": "'0'::xid8", "last_seq": "0", "status": "'building'"},
}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9._]{2,29}$")


def now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def lit(value: str) -> str:
    """A SQL string literal (standard_conforming_strings is on in every Pulse)."""
    return "'" + str(value).replace("'", "''") + "'"


def qname(table: str) -> str:
    return ".".join('"' + p.replace('"', '""') + '"' for p in table.split("."))


def qcol(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Pg:
    """psql inside a database container, SQL on stdin; nothing secret on argv."""

    def __init__(self, runner: str, user: str, database: str) -> None:
        self.runner = shlex.split(runner)
        self.user, self.database = user, database
        self.container = self.runner[-1] if self.runner and self.runner[0] == "docker" else ""

    def argv(self, *tool: str) -> list[str]:
        runner = list(self.runner)
        if runner[:2] == ["docker", "exec"]:
            runner[2:2] = ["-e", f"PGAPPNAME={APP}"]
        return [*runner, *tool]

    def psql(
        self,
        script: str,
        *,
        quiet: bool = True,
        check: bool = True,
        stdout=None,
        notices: list | None = None,
    ) -> str:
        flags = ["-X", "-v", "ON_ERROR_STOP=1"] + (["-q", "-A", "-t"] if quiet else [])
        proc = subprocess.run(
            self.argv("psql", "-U", self.user, "-d", self.database, *flags),
            input=script.encode("utf-8"),
            stdout=stdout or subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        err = proc.stderr.decode("utf-8", "replace")
        if notices is not None:
            notices.extend(err.splitlines())
        elif err.strip():
            sys.stderr.write(err)
        if check and proc.returncode != 0:
            raise SystemExit(f"psql failed ({proc.returncode}): {err.strip()[-2000:]}")
        return proc.stdout.decode("utf-8", "replace") if stdout is None else ""

    def one_json(self, sql: str) -> object:
        out = self.psql(sql).strip().splitlines()
        return json.loads(out[-1]) if out else None

    def soften(self, seconds: float = 2.0) -> threading.Thread:
        """Best effort: lowest CPU and I/O priority for this tool's database backends (the heavy part runs there).

        The container cannot renice (no CAP_SYS_NICE), so the backend's pid inside the container is matched to its
        host pid through /proc/<pid>/status NSpid, and the host renices it."""

        def work() -> None:
            time.sleep(seconds)
            # Priority is a courtesy, never a failure.
            with contextlib.suppress(Exception):
                inner = set(
                    self.psql(
                        f"select pid from pg_stat_activity where application_name = {lit(APP)} "
                        "and pid <> pg_backend_pid();",
                        check=False,
                    ).split()
                )
                for proc in Path("/proc").iterdir():
                    if not proc.name.isdigit():
                        continue
                    try:
                        status = (proc / "status").read_text()
                        cmd = (proc / "cmdline").read_bytes().decode(errors="replace")
                    except OSError:
                        continue
                    ns = next(
                        (ln.split()[1:] for ln in status.splitlines() if ln.startswith("NSpid:")),
                        [],
                    )
                    if len(ns) > 1 and ns[-1] in inner and cmd.startswith("postgres:"):
                        subprocess.run(
                            ["renice", "-n", "19", "-p", proc.name],
                            capture_output=True,
                            check=False,
                        )
                        subprocess.run(
                            ["ionice", "-c3", "-p", proc.name], capture_output=True, check=False
                        )

        t = threading.Thread(target=work, daemon=True)
        t.start()
        return t


# --------------------------------------------------------------------------------------------- discovery
DISCOVER = """
begin isolation level repeatable read read only;
with o as (select * from pulse.org where id::text = :'org' or slug = :'org' or handle = :'org'),
tabs as (
  select c.oid, n.nspname || '.' || c.relname as t, c.relrowsecurity and c.relforcerowsecurity as forced
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = any(string_to_array(:'schemas', ',')) and c.relkind in ('r', 'p') and not c.relispartition
     and exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'org_id' and not a.attisdropped))
select json_build_object(
  'org', (select row_to_json(o) from o),
  'orgs', (select count(*) from pulse.org),
  'migrations', (select json_agg(version order by version) from public.schema_migrations),
  'handles', (select coalesce(json_agg(row_to_json(h)), '[]') from pulse_priv.handle_name h, o where h.kind = 'org' and h.ref = o.id),
  'tables', (select json_agg(json_build_object(
      't', t.t, 'forced', t.forced,
      'rows', case when (select id from o) is null then 0 else (xpath('/row/n/text()', query_to_xml(
                format('select count(*) as n from %s where org_id = %L', t.oid::regclass, (select id from o)), false, true, '')))[1]::text::bigint end,
      'columns', (select json_agg(json_build_object('name', a.attname, 'type', format_type(a.atttypid, a.atttypmod),
                     'generated', a.attgenerated <> '',
                     'fresh', a.attidentity <> '' or coalesce(pg_get_expr(d.adbin, d.adrelid), '') like 'nextval(%%')
                     order by a.attnum)
                   from pg_attribute a left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
                  where a.attrelid = t.oid and a.attnum > 0 and not a.attisdropped),
      'referenced', (select coalesce(json_agg(distinct a.attname), '[]') from pg_constraint con
                       cross join lateral unnest(con.confkey) k(n) join pg_attribute a on a.attrelid = con.confrelid and a.attnum = k.n
                      where con.contype = 'f' and con.confrelid = t.oid)
    ) order by t.t) from tabs t));
rollback;
"""


def discover(pg: Pg, org: str) -> dict:
    sql = (f"\\set org {lit(org)}\n\\set schemas {lit(','.join(SCHEMAS))}\n" + DISCOVER).replace(
        "%%", "%"
    )
    return pg.one_json(sql)  # type: ignore[return-value]


def plan_tables(info: dict, carry_passwords: bool) -> tuple[list[dict], list[dict]]:
    """Which tables move, with which columns; and which stay behind, with why."""
    moving, staying = [], []
    exclude = dict(EXCLUDE)
    if not carry_passwords:
        exclude.update(
            {
                t: why + ": not carried (people get set-password links)"
                for t, why in CREDENTIALS.items()
            }
        )
    for t in info["tables"]:
        name, rows = t["t"], int(t["rows"])
        if not rows:
            continue
        if name in exclude:
            staying.append({"table": name, "rows": rows, "why": exclude[name]})
            continue
        if not t["forced"]:
            raise SystemExit(
                f"{name} has org_id but no forced row-level security: decide on it before a move ({rows} rows)"
            )
        fresh = [c["name"] for c in t["columns"] if c["fresh"]] + list(FRESH_EXTRA.get(name, ()))
        clash = sorted(set(fresh) & set(t["referenced"]))
        if clash:
            raise SystemExit(
                f"{name}.{clash}: a foreign key points at a column the target renumbers; extend the tool first"
            )
        columns = [c["name"] for c in t["columns"] if not c["generated"] and c["name"] not in fresh]
        moving.append(
            {
                "table": name,
                "rows": rows,
                "columns": columns,
                "fresh": fresh,
                "all_columns": [c["name"] for c in t["columns"] if not c["generated"]],
            }
        )
    return moving, staying


def select_for(entry: dict, org_id: str) -> str:
    cols = []
    for c in entry["columns"]:
        expr = TRANSFORM.get(entry["table"], {}).get(c)
        cols.append(f"{expr} as {qcol(c)}" if expr else qcol(c))
    order = (
        " order by " + ", ".join(qcol(c) for c in entry["fresh"] if c != "tx_id")
        if [c for c in entry["fresh"] if c != "tx_id"]
        else ""
    )
    return (
        f"select {', '.join(cols)} from {qname(entry['table'])} where org_id = {lit(org_id)}{order}"
    )


# --------------------------------------------------------------------------------------------- export
def cmd_export(args: argparse.Namespace) -> int:
    pg = Pg(args.exec, args.db_user, args.database)
    info = discover(pg, args.org)
    org = info.get("org")
    if not org:
        raise SystemExit(f"No organisation {args.org!r} in the source")
    moving, staying = plan_tables(info, args.carry_passwords)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(out, 0o700)
    oid = org["id"]
    org_cols = list(org.keys())
    parts = ["\\set ON_ERROR_STOP on", "begin isolation level repeatable read read only;"]

    def block(table: str, cols: list[str], select: str) -> None:
        parts.append(
            f"select {lit('COPY ' + qname(table) + ' (' + ', '.join(qcol(c) for c in cols) + ') FROM stdin;')};"
        )
        parts.append(f"copy ({select}) to stdout;")
        parts.append("select '\\.';")

    block(
        "pulse.org",
        org_cols,
        f"select {', '.join(qcol(c) for c in org_cols)} from pulse.org where id = {lit(oid)}",
    )
    block(
        "pulse_priv.handle_name",
        ["handle", "kind", "ref", "created_at"],
        f"select handle, kind, ref, created_at from pulse_priv.handle_name where kind = 'org' and ref = {lit(oid)}",
    )
    for entry in moving:
        block(entry["table"], entry["columns"], select_for(entry, oid))
    parts.append("rollback;")
    bundle = out / "bundle.sql"
    fd = os.open(bundle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        pg.psql("\n".join(parts) + "\n", stdout=f)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    manifest = {
        "contract": "pulse-org-move.v1",
        "created_at": now(),
        "source": {"exec": args.exec, "database": args.database},
        "org": org,
        "handles": info["handles"],
        "migrations": info["migrations"],
        "carry_passwords": args.carry_passwords,
        "tables": [
            {k: e[k] for k in ("table", "rows", "columns", "fresh", "all_columns")} for e in moving
        ],
        "staying": staying,
        "rows": sum(e["rows"] for e in moving),
        "bundle_sha256": digest,
        "bundle_bytes": bundle.stat().st_size,
    }
    path = out / "manifest.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, default=str)
    print(
        f"{org['name']} ({org['code']}, {oid}): {manifest['rows']} rows in {len(moving)} tables -> {out}"
    )
    print(f"  bundle {manifest['bundle_bytes']} bytes, sha256 {digest}")
    print(f"  migrations {len(info['migrations'])}, last {info['migrations'][-1]}")
    for s in staying:
        print(f"  stays: {s['table']} ({s['rows']}): {s['why']}")
    return 0


# --------------------------------------------------------------------------------------------- import
TARGET_INFO = """
begin read only;
select json_build_object(
  'migrations', (select json_agg(version order by version) from public.schema_migrations),
  'org_taken', (select json_agg(json_build_object('id', id, 'slug', slug, 'code', code, 'handle', handle)) from pulse.org
                 where id::text = :'oid' or slug = :'slug' or code = :'code' or handle = :'handle'),
  'handle_taken', exists (select 1 from pulse_priv.handle_name where handle = :'handle'),
  'host_taken', (select org_id from pulse.org_domain where host = :'host'),
  'account', (select json_build_object('id', id, 'handle', handle) from pulse_priv.pulse_account where handle = :'link_handle'),
  'licence', (select json_build_object('id', id, 'hosting', hosting, 'address', address) from pulse_priv.pulse_licence where org_id::text = :'oid'),
  'columns', (select json_object_agg(n.nspname || '.' || c.relname,
       (select json_agg(a.attname order by a.attnum) from pg_attribute a where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped and a.attgenerated = ''))
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = any(string_to_array(:'schemas', ',')) and c.relkind in ('r', 'p') and not c.relispartition),
  'orgs', (select json_agg(json_build_object('id', id, 'handle', handle) order by created_at) from pulse.org));
rollback;
"""


def check_target(pg: Pg, m: dict, host: str, link_handle: str) -> tuple[dict, list[str]]:
    org = m["org"]
    sql = (
        "\n".join(
            f"\\set {k} {lit(v)}"
            for k, v in {
                "oid": org["id"],
                "slug": org["slug"],
                "code": org["code"],
                "handle": org.get("handle") or "",
                "host": host or "",
                "link_handle": link_handle or "",
                "schemas": ",".join(SCHEMAS),
            }.items()
        )
        + "\n"
        + TARGET_INFO
    )
    t = pg.one_json(sql)
    problems = []
    if t["migrations"] != m["migrations"]:
        src, dst = set(m["migrations"]), set(t["migrations"])
        problems.append(
            f"migrations differ: only in source {sorted(src - dst)[:5]}, only in target {sorted(dst - src)[:5]}"
        )
    if t["org_taken"]:
        problems.append(
            f"the target already has an organisation with this id, slug, code or handle: {t['org_taken']}"
        )
    if t["handle_taken"]:
        problems.append(f"the handle @{org.get('handle')} is taken in the target")
    if host and t["host_taken"]:
        problems.append(f"the address {host} is already claimed by {t['host_taken']}")
    if link_handle and not t["account"]:
        problems.append(f"no Pulse account @{link_handle} in the target")
    for e in m["tables"]:
        have = t["columns"].get(e["table"])
        if have is None:
            problems.append(f"{e['table']} does not exist in the target")
        elif set(have) != set(e["all_columns"]):
            problems.append(
                f"{e['table']}: columns differ (only in source {sorted(set(e['all_columns']) - set(have))}, "
                f"only in target {sorted(set(have) - set(e['all_columns']))})"
            )
    return t, problems


def import_script(
    m: dict,
    bundle: str,
    t: dict,
    *,
    actor: str,
    host: str,
    link: tuple[str, str] | None,
    licence_central: bool,
    licence_note: str,
    apply: bool,
) -> str:
    org = m["org"]
    oid = org["id"]
    expected = {e["table"]: e["rows"] for e in m["tables"]}
    expected["pulse.org"] = 1
    summary = {
        "moved_rows": m["rows"],
        "tables": len(m["tables"]),
        "bundle_sha256": m["bundle_sha256"],
        "from": m["source"],
        "staying": {s["table"]: s["rows"] for s in m["staying"]},
        "carry_passwords": m["carry_passwords"],
        "renumbered": {e["table"]: e["fresh"] for e in m["tables"] if e["fresh"]},
    }
    head = f"""\\set ON_ERROR_STOP on
\\set QUIET on
begin;
set local lock_timeout = '15s';
set local statement_timeout = '15min';
do $guard$ begin
  perform set_config('pulse.actor_account', {lit(actor)}, true);
  if (select json_agg(version order by version)::jsonb from public.schema_migrations) <> {lit(json.dumps(m["migrations"]))}::jsonb then
    raise exception 'pulse-org-move: the target''s migrations changed since the check';
  end if;
  if exists (select 1 from pulse.org where id = {lit(oid)}) then raise exception 'pulse-org-move: organisation already here'; end if;
end $guard$;
\\echo == moving {org["name"]} ({org["code"]}): {m["rows"]} rows in {len(m["tables"])} tables, triggers paused
set local session_replication_role = replica;
"""
    live = [
        "set local session_replication_role = origin;",
        f"do $o$ begin perform set_config('pulse.org_id', {lit(oid)}, true); end $o$;",
    ]
    if host:
        live.append(
            f"insert into pulse.org_domain(host, org_id, sign_in, is_primary, added_by) values ({lit(host)}, {lit(oid)}, 'password', true, {lit(actor[:200])});"
        )
    if link:
        handle, person = link
        live.append(f"""insert into pulse_priv.account_member(account_id, member_org, person_id, kind)
select a.id, {lit(oid)}, {lit(person)}, 'staff' from pulse_priv.pulse_account a where a.handle = {lit(handle)};""")
    if licence_central and t.get("licence"):
        live.append(f"""update pulse_priv.pulse_licence set hosting = 'central', note = {lit(licence_note)}
 where org_id = {lit(oid)} and hosting = 'self-hosted';""")
    live.append(f"""insert into pulse.audit_event(org_id, id, actor_id, actor_account, action, resource, resource_id, source, at, changes)
values ({lit(oid)}, gen_random_uuid(), null, {lit(actor)}, 'import', 'org', {lit(oid)}, 'data-change', now(), {lit(json.dumps(summary))}::jsonb);""")
    counts = f"""
do $counts$
declare exp jsonb := {lit(json.dumps(expected))}::jsonb; k text; n bigint; bad text[] := '{{}}';
begin
  for k in select jsonb_object_keys(exp) loop
    if k = 'pulse.org' then select count(*) into n from pulse.org where id = {lit(oid)};
    else execute format('select count(*) from %s where org_id = %L', k::regclass, {lit(oid)}) into n; end if;
    if n <> (exp ->> k)::bigint then bad := bad || format('%s: %s rows, expected %s', k, n, exp ->> k); end if;
  end loop;
  if array_length(bad, 1) > 0 then raise exception 'pulse-org-move: % table(s) differ from the manifest: %', array_length(bad, 1), array_to_string(bad, '; '); end if;
  raise notice 'pulse-org-move: % tables match the manifest', (select count(*) from jsonb_object_keys(exp));
end $counts$;
"""
    wants = {
        "pulse.org_domain": bool(host),
        "pulse_priv.account_member": bool(link),
        "pulse_priv.pulse_licence": bool(licence_central and t.get("licence")),
    }
    verify = f"""
do $verify$
declare exp jsonb := {lit(json.dumps(expected))}::jsonb; bad text[] := '{{}}'; fk record; orphans bigint; checked int := 0;
begin
  for fk in
    select con.conname, cn.nspname || '.' || cc.relname as child, pn.nspname || '.' || pc.relname as parent,
           (select array_agg(a.attname order by x.ord) from unnest(con.conkey) with ordinality x(n, ord) join pg_attribute a on a.attrelid = con.conrelid and a.attnum = x.n) as ccols,
           (select array_agg(a.attname order by x.ord) from unnest(con.confkey) with ordinality x(n, ord) join pg_attribute a on a.attrelid = con.confrelid and a.attnum = x.n) as pcols
      from pg_constraint con
      join pg_class cc on cc.oid = con.conrelid join pg_namespace cn on cn.oid = cc.relnamespace
      join pg_class pc on pc.oid = con.confrelid join pg_namespace pn on pn.oid = pc.relnamespace
     where con.contype = 'f' and con.conparentid = 0 and exp ? (cn.nspname || '.' || cc.relname) and cn.nspname || '.' || cc.relname <> 'pulse.org'
  loop
    execute format('select count(*) from %s c where c.org_id = %L and %s and not exists (select 1 from %s p where %s)',
      fk.child::regclass, {lit(oid)},
      (select string_agg(format('c.%I is not null', c), ' and ') from unnest(fk.ccols) c),
      fk.parent::regclass,
      (select string_agg(format('p.%I = c.%I', fk.pcols[i], fk.ccols[i]), ' and ') from generate_subscripts(fk.ccols, 1) i)) into orphans;
    checked := checked + 1;
    if orphans > 0 then bad := bad || format('%s (%s -> %s): %s rows point at nothing', fk.conname, fk.child, fk.parent, orphans); end if;
  end loop;
  if {"true" if wants["pulse.org_domain"] else "false"} and not exists (select 1 from pulse.org_domain where org_id = {lit(oid)} and host = {lit(host)}) then bad := bad || 'address row missing'::text; end if;
  if {"true" if wants["pulse_priv.account_member"] else "false"} and not exists (select 1 from pulse_priv.account_member where member_org = {lit(oid)} and person_id = {lit(link[1] if link else oid)}) then bad := bad || 'account link missing'::text; end if;
  if {"true" if wants["pulse_priv.pulse_licence"] else "false"} and not exists (select 1 from pulse_priv.pulse_licence where org_id = {lit(oid)} and hosting = 'central') then bad := bad || 'licence not central'::text; end if;
  if array_length(bad, 1) > 0 then raise exception 'pulse-org-move: % problem(s): %', array_length(bad, 1), array_to_string(bad, '; '); end if;
  raise notice 'pulse-org-move: % foreign keys checked, none broken; live rows in place', checked;
end $verify$;
"""
    report = f"""\\pset tuples_only on
\\pset format unaligned
select 'after: organisations ' || string_agg(coalesce(handle, slug) || '=' || id, ', ' order by created_at) from pulse.org;
select 'after: address ' || host || ' -> ' || org_id || ' (' || sign_in || ')' from pulse.org_domain where org_id = {lit(oid)};
select 'after: account link @' || a.handle || ' -> person ' || m.person_id from pulse_priv.account_member m join pulse_priv.pulse_account a on a.id = m.account_id where m.member_org = {lit(oid)};
select 'after: licence ' || licence_key || ' hosting ' || hosting from pulse_priv.pulse_licence where org_id = {lit(oid)};
select 'after: modules ' || body::text from pulse.tenant_config where org_id = {lit(oid)} and doc_kind = 'tenant' and doc_key = 'modules' and is_active;
\\echo {"== APPLIED (committed)" if apply else "== DRY RUN: rolled back, nothing changed"}
{"commit;" if apply else "rollback;"}
"""
    return head + bundle + "\n" + counts + "\n".join(live) + "\n" + verify + report


def snapshot(pg: Pg, backups: Path, label: str) -> Path:
    backups.mkdir(parents=True, exist_ok=True)
    path = backups / f"{pg.database}-before-{label}-{now()}.dump"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        proc = subprocess.Popen(
            pg.argv("pg_dump", "-U", pg.user, "-d", pg.database, "-Fc"), stdout=out
        )
        pg.soften()
        code = proc.wait()
    if code != 0 or path.stat().st_size < 100_000:
        raise SystemExit(f"Snapshot failed ({code}); nothing was changed: {path}")
    return path


def cmd_import(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle)
    m = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    bundle_bytes = (bundle_dir / "bundle.sql").read_bytes()
    if hashlib.sha256(bundle_bytes).hexdigest() != m["bundle_sha256"]:
        raise SystemExit("bundle.sql does not match its manifest's sha256")
    if args.apply and not (args.approver.strip() and args.words.strip() and args.issue.strip()):
        raise SystemExit("--apply needs --approver, --words (verbatim) and --issue")
    host = (args.host or "").strip().lower()
    if host and not HOST_RE.match(host):
        raise SystemExit(f"--host {host!r} is not a hostname")
    link = None
    if args.link:
        handle, _, person = args.link.partition("=")
        if not HANDLE_RE.match(handle) or not UUID_RE.match(person):
            raise SystemExit("--link is <account handle>=<person uuid in the moved organisation>")
        link = (handle, person)
    pg = Pg(args.exec, args.db_user, args.database)
    t, problems = check_target(pg, m, host, link[0] if link else "")
    if link and not any(link[1] in line for line in [bundle_bytes.decode("utf-8", "replace")]):
        problems.append(f"person {link[1]} is not in the bundle")
    org = m["org"]
    print(f"{org['name']} ({org['code']}, {org['id']}) -> {args.database} via {args.exec}")
    print(f"  target organisations now: {', '.join(o['handle'] or o['id'] for o in t['orgs'])}")
    print(
        f"  {m['rows']} rows in {len(m['tables'])} tables; passwords {'carried' if m['carry_passwords'] else 'not carried'}"
    )
    for p in problems:
        print("  blocks the move:", p)
    if problems:
        return 2
    actor = (
        f"Data change {SCRIPT} · approver: {args.approver or 'dry run'} · issue: {args.issue or 'none'} · "
        f"words: {args.words or 'none'}"
    )[:500]
    note = args.licence_note or (
        f"Moved onto the shared Pulse on {datetime.now(UTC):%d %b %Y}; "
        "it ran on its own server from 15 Oct."
    )
    script = import_script(
        m,
        bundle_bytes.decode("utf-8"),
        t,
        actor=actor,
        host=host,
        link=link,
        licence_central=args.licence_central,
        licence_note=note[:400],
        apply=args.apply,
    )
    if args.print_sql:
        print(script[:4000])
        return 0
    if args.apply and args.no_snapshot:
        if args.database == "pulse":
            raise SystemExit(
                "--no-snapshot is for scratch copies only; the production database always gets a snapshot"
            )
        print("  snapshot: skipped (scratch copy)")
    elif args.apply:
        print(f"  snapshot: {snapshot(pg, Path(args.backups), 'org-move-' + org['slug'])}")
    started = time.time()
    out = pg.psql(script, quiet=False)
    sys.stdout.write(out)
    print(f"  {'applied' if args.apply else 'dry run'} in {time.time() - started:.1f} s")
    return 0


# --------------------------------------------------------------------------------------------- verify / census
def cmd_verify(args: argparse.Namespace) -> int:
    """After an apply: counts against the manifest, and what the API role sees inside and outside the organisation."""
    m = json.loads((Path(args.bundle) / "manifest.json").read_text(encoding="utf-8"))
    pg = Pg(args.exec, args.db_user, args.database)
    oid = m["org"]["id"]
    expected = {e["table"]: e["rows"] for e in m["tables"]}
    # The move writes one audit_event of its own (the import's record), on top of the organisation's history.
    moves = (
        pg.one_json(
            f"select count(*) from pulse.audit_event where org_id = {lit(oid)} and resource = 'org' "
            f"and action = 'import' and actor_account like {lit('Data change ' + SCRIPT + '%')};"
        )
        or 0
    )
    expected["pulse.audit_event"] = expected.get("pulse.audit_event", 0) + int(moves)
    # Each organisation's viewer: an admin (the API's policies read as a signed-in person, never as nobody).
    admins = (
        pg.one_json("""select json_object_agg(o.id, (select r.person_id from pulse.role_assignment r join pulse.person p on p.id = r.person_id
        where r.org_id = o.id and r.role_key = 'admin' and p.status = 'active' and (r.valid_to is null or r.valid_to > current_date)
        order by r.valid_from nulls first, r.person_id limit 1)) from pulse.org o;""")
        or {}
    )
    viewer = args.viewer or admins.get(oid)
    others = {k: v for k, v in admins.items() if k != oid}

    def as_viewer(org: str, person: str | None) -> str:
        return (
            f"perform set_config('pulse.org_id', {lit(org)}, true); "
            f"perform set_config('pulse.viewer_id', {lit(person or '')}, true);"
        )

    sql = f"""begin read only;
do $v$
declare exp jsonb := {lit(json.dumps(expected))}::jsonb; k text; n bigint;
begin
  for k in select jsonb_object_keys(exp) order by 1 loop
    execute format('select count(*) from %s where org_id = %L', k::regclass, {lit(oid)}) into n;
    raise notice 'V%', json_build_object('t', k, 'expected', (exp ->> k)::bigint, 'rows', n);
  end loop;
end $v$;
set local role {qcol(args.api_role)};
do $v$
declare exp jsonb := {lit(json.dumps(expected))}::jsonb; k text; n bigint; f bigint;
begin
  {as_viewer(oid, viewer)}
  for k in select jsonb_object_keys(exp) order by 1 loop
    if not has_table_privilege(current_user, k::regclass, 'select') then
      raise notice 'V%', json_build_object('t', k, 'api', 'no select grant'); continue;
    end if;
    execute format('select count(*), count(*) filter (where org_id <> %L) from %s', {lit(oid)}, k::regclass) into n, f;
    raise notice 'V%', json_build_object('t', k, 'api_inside', n, 'api_foreign_inside', f);
  end loop;
end $v$;
"""
    for other, person in others.items():
        sql += f"""do $v$
declare exp jsonb := {lit(json.dumps(expected))}::jsonb; k text; n bigint; total bigint;
begin
  {as_viewer(other, person)}
  for k in select jsonb_object_keys(exp) order by 1 loop
    if not has_table_privilege(current_user, k::regclass, 'select') then continue; end if;
    execute format('select count(*) filter (where org_id = %L), count(*) from %s', {lit(oid)}, k::regclass) into n, total;
    raise notice 'V%', json_build_object('t', k, 'from', {lit(other)}, 'sees_moved', n, 'sees_own', total - n);
  end loop;
end $v$;
"""
    sql += "rollback;\n"
    notices: list[str] = []
    pg.psql(sql, notices=notices)
    bad, limited = 0, []
    for line in notices:
        if "V{" not in line:
            if line.strip() and "NOTICE" not in line:
                print(line)
            continue
        r = json.loads(line[line.index("V{") + 1 :])
        if "expected" in r and r["rows"] != r["expected"]:
            bad += 1
            print("MISMATCH", r)
        if r.get("api_foreign_inside") or r.get("sees_moved"):
            bad += 1
            print("ISOLATION", r)
        if "api_inside" in r and r["api_inside"] != expected[r["t"]]:
            limited.append(f"{r['t']} {r['api_inside']}/{expected[r['t']]}")
        if r.get("api") == "no select grant":
            limited.append(f"{r['t']} (API role has no select grant)")
    print(
        f"verify: {len(expected)} tables, counts {'match' if not bad else 'see above'} (audit includes {moves} move record); "
        f"read as {args.api_role} with an admin viewer inside, and from {len(others)} other organisation(s) as their admin: "
        f"{'none of the moved rows visible' if not bad else 'see above'}"
    )
    if limited:
        print(
            "  narrower API view (policies beyond org_id, e.g. private chats; expected):",
            "; ".join(limited),
        )
    return 1 if bad else 0


def cmd_census(args: argparse.Namespace) -> int:
    """Rows per organisation in every organisation table, as JSON lines (for a before/after diff)."""
    pg = Pg(args.exec, args.db_user, args.database)
    sql = f"""begin read only;
select format('select json_build_object(''t'', %L, ''by_org'', (select coalesce(json_object_agg(coalesce(org_id::text, ''-''), n), ''{{}}'') from (select org_id, count(*) n from %s group by 1) x));', n.nspname || '.' || c.relname, c.oid::regclass)
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = any(string_to_array({lit(",".join(SCHEMAS))}, ',')) and c.relkind in ('r', 'p') and not c.relispartition
   and exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'org_id' and not a.attisdropped)
 order by 1 \\gexec
rollback;
"""
    proc = subprocess.Popen(
        pg.argv(
            "psql",
            "-U",
            pg.user,
            "-d",
            pg.database,
            "-X",
            "-q",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    pg.soften()
    out, _ = proc.communicate(sql.encode())
    rows = [json.loads(x) for x in out.decode().splitlines() if x.startswith("{")]
    Path(args.out).write_text(json.dumps(rows, indent=0), encoding="utf-8")
    print(f"census: {len(rows)} tables -> {args.out}")
    return 0 if proc.returncode == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser, exec_: str, user: str) -> None:
        p.add_argument("--exec", default=exec_, help=f"how to reach psql (default: {exec_})")
        p.add_argument("--db-user", default=user)
        p.add_argument("--database", default="pulse")

    e = sub.add_parser("export", help="the organisation into a bundle (read only)")
    common(e, "docker exec -i pulse-postgres-1", "pulse_admin")
    e.add_argument("--org", required=True, help="id, slug or handle")
    e.add_argument("--out", required=True, help="a new directory (mode 700)")
    e.add_argument(
        "--carry-passwords",
        action="store_true",
        help="also carry password records and two-step state",
    )
    e.set_defaults(fn=cmd_export)

    i = sub.add_parser(
        "import", help="the bundle into the target, one transaction (dry run unless --apply)"
    )
    common(i, "docker exec -i ea-postgres", "ea_admin")
    i.add_argument("--bundle", required=True)
    i.add_argument(
        "--host",
        default="",
        help="the organisation's own address, password sign-in (pulse.org_domain)",
    )
    i.add_argument(
        "--link",
        default="",
        help="<account handle>=<person uuid>: link a target Pulse account to a moved person",
    )
    i.add_argument(
        "--licence-central",
        action="store_true",
        help="the licence register: hosting self-hosted -> central",
    )
    i.add_argument("--licence-note", default="")
    i.add_argument("--apply", action="store_true")
    i.add_argument("--approver", default="")
    i.add_argument("--words", default="")
    i.add_argument("--issue", default="")
    i.add_argument("--backups", default="/var/backups/pulse")
    i.add_argument(
        "--no-snapshot",
        action="store_true",
        help="scratch copies only: apply without a pg_dump first",
    )
    i.add_argument("--print-sql", action="store_true")
    i.set_defaults(fn=cmd_import)

    v = sub.add_parser("verify", help="after an apply: counts and the isolation read (read only)")
    common(v, "docker exec -i ea-postgres", "ea_admin")
    v.add_argument("--bundle", required=True)
    v.add_argument("--api-role", default="pulse_api")
    v.add_argument(
        "--viewer",
        default="",
        help="person uuid to read as inside the organisation (default: its first admin)",
    )
    v.set_defaults(fn=cmd_verify)

    c = sub.add_parser(
        "census", help="rows per organisation in every organisation table (read only)"
    )
    common(c, "docker exec -i ea-postgres", "ea_admin")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=cmd_census)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
