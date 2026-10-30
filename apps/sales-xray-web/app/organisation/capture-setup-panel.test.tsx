// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { CaptureTeamRow } from "../capture-setup/capture-setup-client";
import { CaptureSetupPanel, captureLine } from "./capture-setup-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 30 Oct 2026: "the organisation owner sees who hasn't set it up in Team".

const row = (
  name: string,
  state: CaptureTeamRow["state"],
  extra: Partial<CaptureTeamRow> = {},
): CaptureTeamRow => ({
  person_id: `id-${name}`,
  name,
  role: "member",
  state,
  at: "2026-10-29T06:00:00+00:00",
  phone: null,
  ...extra,
});

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function mount(
  people: CaptureTeamRow[] | null,
  status = 200,
  missingToday = 0,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            schema: "sales-xray-capture-setup-team/1",
            people,
            missing_today: missingToday,
          }),
          { status, headers: { "content-type": "application/json" } },
        ),
    ),
  );
  await act(async () => root.render(<CaptureSetupPanel />));
  for (let i = 0; i < 6; i++) await act(async () => await Promise.resolve());
}

it("counts who still needs it and names why, never a phone number", async () => {
  await mount([
    row("Asha Fictional", "not_started", { at: null }),
    row("Ravi Fictional", "declined"),
    row("Karan Fictional", "set_up", { phone: "Redmi 13" }),
  ]);
  expect(host.textContent).toContain("2 of 3 not set up");
  const items = [...host.querySelectorAll("li")].map(
    (item) => item.textContent,
  );
  expect(items[0]).toContain("Not set up");
  expect(items[1]).toContain("Said not now on 29 Oct");
  expect(items[2]).toContain("Redmi 13 · since 29 Oct");
  expect(host.textContent).not.toMatch(/\+\d{6,}/);
});

it("says when everyone is set up, and shows nothing it can't read", async () => {
  await mount([row("Karan Fictional", "set_up", { phone: "Redmi 13" })]);
  expect(host.textContent).toContain("Everyone is set up");
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount(null, 403);
  expect(host.textContent).toBe("");
});

it("words every state plainly", () => {
  expect(captureLine(row("A", "phone_pending"))).toBe(
    "Agreed, but hasn't opened the app on a phone yet",
  );
  expect(captureLine(row("A", "turned_off"))).toBe(
    "Turned call capture off on 29 Oct",
  );
  expect(captureLine(row("A", "consent_changed"))).toBe(
    "The terms changed: needs to agree again",
  );
});

it("counts today's calls without a recording, in all and per seller", async () => {
  await mount(
    [
      row("Ravi Fictional", "set_up", { phone: "Redmi 13", missing_today: 2 }),
      row("Karan Fictional", "set_up", { phone: "Galaxy A15" }),
    ],
    200,
    2,
  );
  expect(host.textContent).toContain(
    "Everyone is set up · 2 calls without a recording today",
  );
  const items = [...host.querySelectorAll("li")].map(
    (item) => item.textContent,
  );
  expect(items[0]).toContain("2 calls without a recording today · Redmi 13");
  expect(items[1]).not.toContain("without a recording");
});
