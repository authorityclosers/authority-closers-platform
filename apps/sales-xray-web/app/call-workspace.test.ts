import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SELECT_WORKSPACE_EVENT } from "./call-ownership";
import { callWorkspace, openInCallWorkspace } from "./call-workspace";

const call = "11111111-1111-4111-8111-111111111111";
const personal = "22222222-2222-4222-8222-222222222222";
const organisation = "33333333-3333-4333-8333-333333333333";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

let home: Response;
let selected: string;
let switches: unknown[];
const listen = (event: Event) =>
  switches.push((event as CustomEvent<unknown>).detail);

beforeEach(() => {
  home = json({ tenant_id: organisation });
  selected = personal;
  switches = [];
  window.history.replaceState(
    null,
    "",
    `/analysis/calls/${call}?section=overview`,
  );
  window.addEventListener(SELECT_WORKSPACE_EVENT, listen);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      path.endsWith(`/call/${call}`)
        ? home
        : path === "/v1/me/sales-xray-workspaces"
          ? json({ selected_tenant_id: selected, workspaces: [] })
          : json({}, 404),
    ),
  );
});
afterEach(() => {
  window.removeEventListener(SELECT_WORKSPACE_EVENT, listen);
  vi.unstubAllGlobals();
});

it("opens a call held by another of the person's workspaces there", async () => {
  // 16 Oct: the Mac had the organisation selected, this browser Personal.
  expect(await openInCallWorkspace(call)).toBe(true);
  expect(switches).toEqual([
    {
      tenantId: organisation,
      next: `/analysis/calls/${call}?section=overview`,
    },
  ]);
});

it("stays put when the call is in the selected workspace or not readable", async () => {
  selected = organisation;
  expect(await openInCallWorkspace(call)).toBe(false);
  selected = personal;
  home = json({ detail: "Saved call not found." }, 404);
  expect(await openInCallWorkspace(call)).toBe(false);
  expect(switches).toEqual([]);
});

it("asks nothing for a malformed id and ignores malformed answers", async () => {
  expect(await callWorkspace("not-a-call")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
  home = json({ tenant_id: "not-a-tenant" });
  expect(await callWorkspace(call)).toBeNull();
});
