// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { StaffKeys } from "./staff-keys";
import { normalizeStaffKeys } from "./staff-keys-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const KEY = "ac_dev_" + "k".repeat(43);
const DATA = normalizeStaffKeys({
  keys: [
    {
      id: "k-1",
      name: "Laptop CLI",
      prefix: "ac_dev_Ab12Cd34",
      scopes: ["settings:read", "settings:write"],
      state: "active",
      created_at: "2026-10-19T09:00:00+00:00",
      expires_at: "2026-11-18T09:00:00+00:00",
      last_used_at: null,
    },
    {
      id: "k-0",
      name: "Old",
      prefix: "ac_dev_Zz99Yy88",
      scopes: ["settings:read"],
      state: "revoked",
      revoked_at: "2026-10-19T08:00:00+00:00",
    },
  ],
  limits: {
    active: 2,
    days: 30,
    fresh_minutes: 10,
    scopes: ["settings:read", "settings:write"],
  },
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
    item.textContent?.startsWith(text),
  )!;

async function type(element: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set?.call(element, value);
  await act(async () => {
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("lists keys by prefix with their use, never the key, and offers revoke only on live ones", async () => {
  await act(async () => root.render(<StaffKeys data={DATA} />));
  const text = host.textContent ?? "";
  expect(text).toContain("ac_dev_Ab12Cd34…");
  expect(text).toContain("Never used");
  expect(text).toContain("settings:write");
  expect(text).toContain("Revoked");
  expect(host.querySelector('a[href="/tools/ac-admin.py"]')).not.toBeNull();
  expect(
    host.querySelector('button[aria-label="Revoke Laptop CLI"]'),
  ).not.toBeNull();
  expect(host.querySelector('button[aria-label="Revoke Old"]')).toBeNull();
});

it("makes a key, shows it once, and can hide it", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          id: "k-2",
          name: "MCP",
          prefix: "ac_dev_kkkkkkkk",
          scopes: ["settings:read"],
          state: "active",
          key: KEY,
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const one = normalizeStaffKeys({
    keys: [DATA.keys[1]],
    limits: { active: 2 },
  });
  await act(async () => root.render(<StaffKeys data={one} />));
  await act(async () => button("Make a staff key").click());
  await type(
    host.querySelector<HTMLInputElement>('input[aria-label="Key name"]')!,
    "MCP",
  );
  await act(async () => button("Make key").click());
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/v1/admin/staff-keys");
  expect(JSON.parse(String(init.body))).toEqual({
    name: "MCP",
    scopes: ["settings:read"],
  });
  expect(host.textContent).toContain(KEY);
  expect(host.textContent).toContain("won’t show again");
  expect(refresh).toHaveBeenCalled();
  await act(async () => button("Done, hide it").click());
  expect(host.textContent).not.toContain(KEY);
});

it("says to sign in again when the sign-in is too old", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail:
              "Sign in again to make a key: it needs a sign-in within the last 10 minutes.",
          }),
          { status: 403, headers: { "content-type": "application/json" } },
        ),
    ),
  );
  const one = normalizeStaffKeys({ keys: [], limits: { active: 2 } });
  await act(async () => root.render(<StaffKeys data={one} />));
  await act(async () => button("Make a staff key").click());
  await type(
    host.querySelector<HTMLInputElement>('input[aria-label="Key name"]')!,
    "CLI",
  );
  await act(async () => button("Make key").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Sign in again",
  );
  expect(host.querySelector('a[href="/login"]')).not.toBeNull();
});

it("turns Make off at two active keys", async () => {
  const full = normalizeStaffKeys({
    keys: [
      { ...DATA.keys[0], id: "a" },
      { ...DATA.keys[0], id: "b", name: "Second" },
    ].map((key) => ({
      id: key.id,
      name: key.name,
      prefix: key.prefix,
      scopes: key.scopes,
      state: "active",
    })),
    limits: { active: 2 },
  });
  await act(async () => root.render(<StaffKeys data={full} />));
  expect(button("Make a staff key").disabled).toBe(true);
});
