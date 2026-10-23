import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LeadEvent } from "./leads-client";
import { parseCallLog } from "./native-phone";
import { clockTime, phoneCallText } from "./phone-call-text";
import { PhoneLogCard, phoneLogLine } from "./phone-log-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

type Listener = (event: { data: unknown }) => void;
type Sent = { method: string; args: Record<string, unknown> };

/** A stand-in for the phone app's SXPhone channel. */
function fakePhone(answer: (message: Sent) => unknown) {
  const listeners: Listener[] = [];
  const sent: Sent[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as Sent & { id: string };
      sent.push({ method: message.method, args: message.args });
      const result = answer(message);
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  });
  return sent;
}

const SIMS = [
  { id: "8991-1", label: "Jio" },
  { id: "8991-2", label: "Airtel" },
];

const status = (extra: Record<string, unknown> = {}) => ({
  on: false,
  access: true,
  sims: SIMS,
  sim: "",
  lastSyncMs: null,
  lastLogged: 0,
  state: "never",
  ...extra,
});

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent === label,
  )!;

describe("logging work calls on the phone", () => {
  it("shows nothing in a browser", async () => {
    await act(async () => root.render(<PhoneLogCard />));
    expect(host.innerHTML).toBe("");
  });

  it("offers it once, for the work SIM the seller picks", async () => {
    const sent = fakePhone((message) =>
      message.method === "callLogSetup"
        ? status({ on: true, sim: message.args.sim })
        : status(),
    );
    await act(async () => root.render(<PhoneLogCard />));
    expect(host.textContent).toContain("Log work calls by themselves");
    expect(host.textContent).toContain("Other numbers stay on your phone.");
    expect(button("Jio").getAttribute("aria-pressed")).toBe("true");

    await act(async () => button("Airtel").click());
    await act(async () => button("Turn on").click());
    expect(sent.filter((item) => item.method === "callLogSetup")).toEqual([
      { method: "callLogSetup", args: { on: true, sim: "8991-2" } },
    ]);
    const toggle = host.querySelector('button[role="switch"]')!;
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(host.textContent).toContain("Logging work calls");
    expect(host.textContent).toContain("Airtel · checks when you open the app");
  });

  it("asks for call history access when the phone says no", async () => {
    fakePhone((message) =>
      message.method === "callLogSetup"
        ? status({ access: false })
        : status({ sims: [] }),
    );
    await act(async () => root.render(<PhoneLogCard />));
    expect(host.querySelector('[role="group"]')).toBeNull();
    await act(async () => button("Turn on").click());
    expect(host.textContent).toContain("Allow call history for Sales X-Ray");
    expect(host.querySelector('button[role="switch"]')).toBeNull();
  });

  it("waits for the work SIM once access is given on a two-SIM phone", async () => {
    const sent = fakePhone((message) =>
      message.method === "callLogSetup"
        ? status({ access: true })
        : status({ access: false, sims: [] }),
    );
    await act(async () => root.render(<PhoneLogCard />));
    await act(async () => button("Turn on").click());
    expect(host.textContent).toContain("Pick your work SIM, then turn it on.");
    expect(button("Jio").getAttribute("aria-pressed")).toBe("true");
    await act(async () => button("Turn on").click());
    expect(
      sent.filter((item) => item.method === "callLogSetup").at(-1),
    ).toEqual({ method: "callLogSetup", args: { on: true, sim: "8991-1" } });
  });

  it("asks before switching off from the slim row", async () => {
    const sent = fakePhone((message) =>
      message.method === "callLogSetup"
        ? status({ on: false })
        : status({ on: true, sim: "8991-1", lastSyncMs: Date.now() - 120_000 }),
    );
    await act(async () => root.render(<PhoneLogCard />));
    expect(host.textContent).toContain("Jio · checked 2 min ago");
    await act(async () =>
      host.querySelector<HTMLButtonElement>('button[role="switch"]')!.click(),
    );
    // Owner, 23 Oct 2026: stopping asks first.
    expect(sent.some((item) => item.method === "callLogSetup")).toBe(false);
    expect(document.querySelector("dialog")?.textContent).toContain(
      "Calls already logged stay on their leads.",
    );
    const stop = [
      ...document.querySelectorAll<HTMLButtonElement>("dialog button"),
    ].find((item) => item.textContent === "Stop logging")!;
    await act(async () => stop.click());
    expect(sent.at(-1)).toEqual({
      method: "callLogSetup",
      args: { on: false, sim: "8991-1" },
    });
    expect(host.textContent).toContain("Log work calls by themselves");
  });

  it("stays hidden after Not now until it is on", async () => {
    localStorage.setItem("sx-leads-phone-log-card", "hidden");
    fakePhone(() => status());
    await act(async () => root.render(<PhoneLogCard />));
    expect(host.innerHTML).toBe("");
  });
});

describe("what the phone says", () => {
  it("keeps only a well-formed answer", () => {
    expect(parseCallLog(null)).toBeNull();
    expect(parseCallLog({ sims: [] })).toBeNull();
    expect(
      parseCallLog({ on: true, sims: [{ id: "" }, { id: "1" }, 4] }),
    ).toEqual({
      on: true,
      access: false,
      sims: [{ id: "1", label: "" }],
      sim: "",
      lastSyncMs: null,
      lastLogged: 0,
      state: "never",
    });
  });

  it("puts the problem first in the slim row", () => {
    const parsed = parseCallLog(status({ on: true, access: false }))!;
    expect(phoneLogLine(parsed)).toContain("Allow call history");
    expect(phoneLogLine({ ...parsed, access: true, state: "signed_out" })).toBe(
      "Sign in again to keep logging.",
    );
  });
});

describe("a phone-logged call in the lead's History", () => {
  const event = (extra: Partial<LeadEvent>): LeadEvent => ({
    kind: "call",
    at: "2026-10-18T05:30:00Z",
    actor_name: "Asha",
    stage: null,
    stage_label: null,
    reason: null,
    reason_label: null,
    connected: null,
    note: null,
    next_action_at: null,
    owner_name: null,
    previous_owner_name: null,
    allocation_reason: null,
    source_label: null,
    submission_id: null,
    simulated: null,
    duration_seconds: null,
    via: "phone",
    ...extra,
  });

  it("reads like the phone's own call log", () => {
    expect(clockTime(192)).toBe("3:12");
    expect(clockTime(5)).toBe("0:05");
    expect(
      phoneCallText(
        event({ direction: "outgoing", duration_seconds: 192 }),
        "Asha",
      ),
    ).toEqual({ title: "Asha called · 3:12", detail: "From the phone dialer" });
    expect(phoneCallText(event({ direction: "outgoing" }), "Asha").title).toBe(
      "Asha called · not connected",
    );
    expect(
      phoneCallText(
        event({ direction: "incoming", duration_seconds: 65 }),
        "Asha",
      ).title,
    ).toBe("They called Asha · 1:05");
    expect(phoneCallText(event({ direction: "missed" }), "Asha")).toEqual({
      title: "Missed call from them",
      detail: "On Asha's phone. Call them back.",
    });
    expect(phoneCallText(event({ direction: "rejected" }), "Asha").title).toBe(
      "Asha cut their call",
    );
  });
});
