// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { CaptureTeamRow } from "../capture-setup/capture-setup-client";
import { WorkspaceAccessContext } from "../workspace-access";
import {
  CaptureSetupPanel,
  captureLine,
  recordingLine,
} from "./capture-setup-panel";

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
  me: string | null = null,
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
  await act(async () =>
    root.render(
      me ? (
        <WorkspaceAccessContext.Provider
          value={{
            status: "ready",
            authenticated: true,
            context: { personId: me, sessionId: "s", tenantId: "t" },
            retry: () => {},
          }}
        >
          <CaptureSetupPanel />
        </WorkspaceAccessContext.Provider>
      ) : (
        <CaptureSetupPanel />
      ),
    ),
  );
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
  // Done reads Ready: "Set up" is only ever an action (ph1-38).
  const badges = [...host.querySelectorAll("li > [data-state]")].map(
    (badge) => badge.textContent,
  );
  expect(badges).toEqual(["Not set up", "Said not now", "Ready"]);
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

it("never says everyone is set up while a phone has call logging off", async () => {
  // Phone personas ph1-23, 1 Nov 2026: Connections said a phone had call logging
  // off while Team said everyone was set up. One rule now, from the server.
  await mount([
    row("Karan Fictional", "set_up", {
      phone: "Redmi 13 5G",
      call_log_off: "Redmi 13 5G",
    }),
  ]);
  expect(host.textContent).toContain("Call logging off on 1 phone");
  expect(host.textContent).not.toContain("Everyone is set up");
  expect(host.querySelector("li")?.textContent).toContain(
    "Call logging off on Redmi 13 5G: on that phone, Settings, Selling, Log work calls",
  );
});
it("shows each phone's recording as a dot and a line with its fix", async () => {
  // Competitor teardown, item 7, 1 Nov 2026: the owner sees whether each phone records.
  const now = Date.parse("2026-11-01T09:00:00+05:30");
  const at = (minutes: number) =>
    new Date(now - minutes * 60_000).toISOString();
  expect(recordingLine({ state: "ok", last_at: at(12), fix: null }, now)).toBe(
    "Recording OK · last file 12 min ago",
  );
  expect(
    recordingLine(
      { state: "late", last_at: "2026-10-27T11:00:00+05:30", fix: "recorder" },
      now,
    ),
  ).toBe("No recordings since Tue · Turn on call recording");
  expect(
    recordingLine({ state: "off", last_at: null, fix: "folder" }, now),
  ).toBe("No recordings folder · Allow folder");
  expect(
    recordingLine({ state: "late", last_at: null, fix: "test" }, now),
  ).toBe("No call recording found yet · Place a test call");
  await mount([
    row("Karan Fictional", "set_up", {
      phone: "Redmi 13 5G",
      recording: { state: "off", last_at: null, fix: "folder" },
    }),
  ]);
  const line = host.querySelector('small[data-state="off"]');
  expect(line?.textContent).toBe("No recordings folder · Allow folder");
});

// Phone personas ph1-46 (v1.25): "Everyone is set up" and Ready beside a red
// "Call recording off", "Turn on call recording" as dead text, and one of the
// seller's two phones missing.
const off = row("Karan Fictional", "recording_off", {
  phone: "Redmi 13",
  phones: ["Redmi 13", "Nord CE 2 5G"],
  recording: {
    state: "off",
    last_at: null,
    fix: "recorder",
    phone: "Nord CE 2 5G",
  },
});

it("never says Ready or everyone is set up beside recording off, and lists every phone", async () => {
  await mount([off]);
  expect(host.textContent).toContain("1 of 1 not set up");
  expect(host.textContent).not.toContain("Everyone is set up");
  expect(host.querySelector("li > [data-state]")?.textContent).toBe(
    "Recording off",
  );
  expect(host.querySelector("li")?.textContent).toContain(
    "Redmi 13 · Nord CE 2 5G · since 29 Oct",
  );
  expect(host.querySelector('small[data-state="off"]')?.textContent).toBe(
    "Nord CE 2 5G: Call recording off · Turn on call recording",
  );
});

it("makes the fix a button: on another seller's row, what they do on their phone", async () => {
  await mount([off], 200, 0, "id-someone-else");
  const fix = host.querySelector<HTMLButtonElement>(
    'small[data-state="off"] button',
  );
  expect(fix?.textContent).toBe("Turn on call recording");
  await act(async () => fix?.click());
  expect(document.body.textContent).toContain(
    "On Nord CE 2 5G, open Sales X-Ray.",
  );
  expect(document.body.textContent).toContain(
    "Settings, Selling, Phone setup, then Set up.",
  );
});

it("makes the fix a button: on your own row, the recording check on this phone", async () => {
  await mount([off], 200, 0, "id-Karan Fictional");
  const asked: unknown[] = [];
  const listen = (event: Event) =>
    asked.push((event as CustomEvent<unknown>).detail);
  window.addEventListener("sx-capture-setup-open", listen);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('small[data-state="off"] button')
      ?.click(),
  );
  window.removeEventListener("sx-capture-setup-open", listen);
  expect(asked).toEqual(["recordings"]);
});
