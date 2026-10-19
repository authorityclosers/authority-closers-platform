#!/usr/bin/env python3
"""ac-admin: Authority Closers Admin settings from the command line, and as an MCP server.

Download from Admin (Accounts -> Integrations -> Staff keys). One file, Python 3.10+,
standard library only. Signs in with a staff key made in Admin by a verified control
account. The key is read from AC_ADMIN_KEY (or the OS keychain, service "ac-admin",
when the optional keyring package is installed). It is never a command-line argument,
so it stays out of shell history and process lists, and this tool never prints it.

    export AC_ADMIN_KEY=ac_live_...                        # ac_stg_... / ac_dev_... elsewhere
    export AC_ADMIN_BASE=https://admin.authorityclosers.com  # the default

    ac-admin settings list                 # every setting, its value now, whether it changes here
    ac-admin settings get ID               # one setting: value, revision, options or bounds
    ac-admin settings set ID VALUE [--reason TEXT]
    ac-admin mcp                           # an MCP server on stdio (for AI assistants)

A key reaches only the settings Admin lists (GET /v1/admin/settings); each change goes
through that area's own route, with its checks and audit. Output is JSON. Exit status 0
on success, 1 when Admin refused (its answer is printed), 2 on a usage or connection
problem.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_BASE = "https://admin.authorityclosers.com"
VERSION = "1.0.0"
TIMEOUT = 30
TRUE = {"true", "on", "yes", "1"}
FALSE = {"false", "off", "no", "0"}
KEY_SHAPE = re.compile(r"ac_[a-z]{2,8}_[A-Za-z0-9_-]{20,}")


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status, self.message = status, message


class UsageError(ValueError):
    pass


Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


def _urlopen(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def pointer(document: Any, path: str | None) -> Any:
    """RFC 6901 JSON pointer; None when any step is missing."""
    if path in (None, "", "/"):
        return document
    current = document
    for raw in str(path).lstrip("/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


class Client:
    """Admin settings for one staff key."""

    def __init__(self, key: str, base: str = DEFAULT_BASE, transport: Transport = _urlopen):
        if not key.startswith("ac_"):
            raise UsageError("Set AC_ADMIN_KEY to a staff key made in Admin (ac_...).")
        if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
            raise UsageError("AC_ADMIN_BASE must be https://")
        self._key, self.base, self.transport = key, base.rstrip("/"), transport
        self._manifest: dict[str, Any] | None = None

    def call(self, method: str, path: str, body: Any = None, idempotent: bool = False) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)  # noqa: S310
        request.add_header("Authorization", f"Bearer {self._key}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"ac-admin/{VERSION}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if idempotent:
            request.add_header("Idempotency-Key", str(uuid.uuid4()))
        status, raw = self.transport(request)
        try:
            payload = json.loads(raw or b"null")
        except ValueError:
            payload = None
        if not 200 <= status < 300:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise ApiError(status, detail if isinstance(detail, str) else "Admin refused.")
        return payload

    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            self._manifest = self.call("GET", "/v1/admin/settings")
        return self._manifest

    def setting(self, setting_id: str) -> dict[str, Any]:
        for item in self.manifest().get("settings", []):
            if item.get("id") == setting_id:
                return dict(item)
        raise UsageError(f"No setting {setting_id!r}; see: ac-admin settings list")

    def _answers(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        for item in items:
            path = item["read"]["path"]
            if path not in answers:
                try:
                    answers[path] = self.call("GET", path)
                except ApiError as error:
                    answers[path] = error
        return answers

    def list(self) -> list[dict[str, Any]]:
        items = list(self.manifest().get("settings", []))
        answers = self._answers(items)
        rows = []
        for item in items:
            answer = answers[item["read"]["path"]]
            rows.append(
                {
                    "id": item["id"],
                    "area": item.get("area_title") or item.get("area"),
                    "label": item["label"],
                    "value": None
                    if isinstance(answer, ApiError)
                    else pointer(answer, item["read"]["value"]),
                    "changes_here": item.get("write") is not None,
                }
            )
        return rows

    def get(self, setting_id: str) -> dict[str, Any]:
        item = self.setting(setting_id)
        answer = self.call("GET", item["read"]["path"])
        return {
            "id": item["id"],
            "label": item["label"],
            "kind": item["kind"],
            "value": pointer(answer, item["read"]["value"]),
            "revision": pointer(answer, item["read"].get("revision")),
            "options": options(item, answer),
            "minimum": item.get("minimum"),
            "maximum": maximum(item, answer),
            "changes_here": item.get("write") is not None,
            "why_not": item.get("why_not"),
            "help": item.get("help"),
        }

    def set(self, setting_id: str, text: str, reason: str | None = None) -> Any:
        item = self.setting(setting_id)
        write = item.get("write")
        if write is None:
            raise UsageError(item.get("why_not") or "This setting is changed on its page.")
        answer = self.call("GET", item["read"]["path"])
        value = parse(item, answer, text)
        body = request_body(item, answer, value, reason)
        return self.call(
            write["method"], write["path"], body, idempotent=bool(write.get("idempotency_key"))
        )


def options(item: Mapping[str, Any], answer: Any) -> list[str]:
    source = item.get("options_from")
    if source:
        menu = pointer(answer, source["list"]) or []
        return [str(entry.get(source["value"])) for entry in menu if isinstance(entry, dict)]
    return [str(option["value"]) for option in item.get("options") or []]


def maximum(item: Mapping[str, Any], answer: Any) -> Any:
    found = pointer(answer, item.get("maximum_from")) if item.get("maximum_from") else None
    return found if isinstance(found, int) else item.get("maximum")


def parse(item: Mapping[str, Any], answer: Any, text: str) -> Any:
    """The typed value from what was typed: words for on/off, rupees for money."""
    kind, word = item["kind"], text.strip()
    if kind == "bool":
        labels = {str(v).lower(): k == "true" for k, v in (item.get("labels") or {}).items()}
        lowered = word.lower()
        if lowered in TRUE or labels.get(lowered) is True:
            return True
        if lowered in FALSE or labels.get(lowered) is False:
            return False
        raise UsageError("Give true or false (or the setting's own words, e.g. paused).")
    if kind == "enum":
        allowed = options(item, answer)
        if word not in allowed:
            raise UsageError(f"Choose one of: {', '.join(allowed)}")
        return word
    if kind in ("int", "money_paise"):
        try:
            number = float(word)
        except ValueError:
            raise UsageError("Give a number.") from None
        value = round(number * 100) if kind == "money_paise" else round(number)
        low, high = item.get("minimum"), maximum(item, answer)
        if (low is not None and value < low) or (high is not None and value > high):
            scale = 100 if kind == "money_paise" else 1
            raise UsageError(f"Between {(low or 0) / scale:g} and {(high or 0) / scale:g}.")
        return value
    return word


def request_body(
    item: Mapping[str, Any], answer: Any, value: Any, reason: str | None = None
) -> dict[str, Any]:
    """The same steps as Admin's registry: revision, merge, reason."""
    write = item["write"]
    if write.get("needs_reason") and not (reason and reason.strip()):
        raise UsageError("This change needs --reason.")
    merged: Any = None
    if write.get("merge"):
        merged = copy.deepcopy(pointer(answer, write["merge"]["container"]))
        if not isinstance(merged, dict):
            raise UsageError("The current settings could not be read.")
        target = merged
        for part in write["merge"]["key"][:-1]:
            target = target.setdefault(part, {})
        target[write["merge"]["key"][-1]] = value
    fill = {
        "$value": value,
        "$revision": pointer(answer, item["read"].get("revision"))
        if item["read"].get("revision")
        else None,
        "$reason": (reason or "").strip(),
        "$merged": merged,
    }
    return {
        key: fill[template] if isinstance(template, str) and template in fill else template
        for key, template in write["body"].items()
    }


# ----- MCP (Model Context Protocol) over stdio ------------------------------------

PROTOCOL = "2025-06-18"
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_settings",
        "description": "Every Authority Closers Admin setting, its value now and whether it "
        "can be changed with this key.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_setting",
        "description": "One Admin setting: its value, revision, and the options or bounds a "
        "change must respect.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Setting id from list_settings"}
            },
            "required": ["id"],
        },
    },
    {
        "name": "set_setting",
        "description": "Change one Admin setting through its area's own checks and audit. "
        "Values are words: true/false (or the setting's own words), an option, a number, or "
        "rupees for money. Some changes need a reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "value": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["id", "value"],
        },
    },
]


def _tool(client: Client, name: str, args: dict[str, Any]) -> Any:
    if name == "list_settings":
        return client.list()
    if name == "get_setting":
        return client.get(str(args["id"]))
    if name == "set_setting":
        return client.set(str(args["id"]), str(args["value"]), args.get("reason"))
    raise KeyError(name)


def handle(client: Client, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC request in, its response out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result: Any = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ac-admin", "version": VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            data = _tool(client, str(params.get("name")), dict(params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
        except (ApiError, UsageError) as error:
            text = f"Admin refused: {error}"
            result = {"content": [{"type": "text", "text": text}], "isError": True}
        except KeyError as error:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32602, "message": f"Unknown tool or argument: {error}"},
            }
        except OSError as error:
            result = {
                "content": [
                    {"type": "text", "text": f"Could not reach Admin: {type(error).__name__}"}
                ],
                "isError": True,
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(client: Client, stdin: Any = sys.stdin, stdout: Any = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            reply = handle(client, message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


# ----- command line --------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ac-admin", description="Admin settings, by key.")
    parser.add_argument("--version", action="version", version=f"ac-admin {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    settings = commands.add_parser("settings").add_subparsers(dest="action", required=True)
    settings.add_parser("list")
    get = settings.add_parser("get")
    get.add_argument("id")
    change = settings.add_parser("set")
    change.add_argument("id")
    change.add_argument("value")
    change.add_argument("--reason")
    commands.add_parser("mcp")
    return parser


def _key(environ: Mapping[str, str]) -> str:
    key = environ.get("AC_ADMIN_KEY", "")
    if key:
        return key
    try:  # optional: the OS keychain, when the keyring package is installed
        import keyring  # type: ignore[import-not-found]

        return keyring.get_password("ac-admin", "default") or ""
    except Exception:  # noqa: BLE001 - no keychain is not an error
        return ""


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    transport: Transport = _urlopen,
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    out, err = stdout or sys.stdout, stderr or sys.stderr
    arguments = list(sys.argv[1:] if argv is None else argv)
    # A key in the arguments would sit in shell history and process lists: refuse it.
    if any(KEY_SHAPE.search(argument) for argument in arguments):
        print("Never pass the key as an argument; set AC_ADMIN_KEY instead.", file=err)
        return 2
    args = _parser().parse_args(arguments)
    env = os.environ if environ is None else environ
    try:
        client = Client(_key(env), env.get("AC_ADMIN_BASE", DEFAULT_BASE), transport)
    except UsageError as error:
        print(str(error), file=err)
        return 2
    if args.command == "mcp":
        serve(client)
        return 0
    try:
        if args.action == "list":
            result: Any = client.list()
        elif args.action == "get":
            result = client.get(args.id)
        else:
            result = client.set(args.id, args.value, args.reason)
    except ApiError as error:
        print(json.dumps({"error": {"status": error.status, "message": error.message}}), file=err)
        return 1
    except UsageError as error:
        print(str(error), file=err)
        return 2
    except OSError as error:
        print(f"Could not reach Admin: {type(error).__name__}", file=err)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
