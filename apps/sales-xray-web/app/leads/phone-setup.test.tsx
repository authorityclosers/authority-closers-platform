import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PhoneHealth, RepView } from "./leads-client";
import { parseSetup } from "./native-phone";
import { PhoneSetupBar, setupProgress } from "./phone-setup";
import { phoneDot, recorderSteps } from "./phone-setup-words";
import { PhoneCell } from "./team-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

type Listener = (event: { data: unknown }) => void;
type Sent = { method: string; args: Record<string, unknown> };

const CHECKS = {
  calls: true,
  recordings: true,
  notifications: false,
  recorder: false,
  folder: false,
  battery: false,
  autostart: false,
  testCall: false,
  callLog: true,
};

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

const setup = (checks: Record<string, boolean>, extra = {}) => ({
  checks,
  family: "xiaomi",
  model: "Redmi Note 8 Pro",
  autostartNeeded: true,
  version: "0.3.20",
  device: "5c0de5a7-0000-4000-8000-00000000d5c5",
  ...extra,
});

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
  };
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const button = (label: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.startsWith(label),
  )!;

describe("the phone setup bar (UX study item 7)", () => {
  it("shows nothing in a browser", async () => {
    await act(async () => root.render(<PhoneSetupBar />));
    expect(host.innerHTML).toBe("");
  });

  it("shows progress, reports the checklist once, and explains a permission first", async () => {
    let checks = { ...CHECKS };
    const sent = fakePhone((message) => {
      if (message.method === "requestNotifications")
        checks = { ...checks, notifications: true };
      return setup(checks);
    });
    const fetchMock = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify({ done: 3, total: 9 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    await act(async () => root.render(<PhoneSetupBar />));
    expect(host.textContent).toContain("Phone setup");
    expect(host.textContent).toContain("3 of 9 done");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/me\/phone$/);
    expect(JSON.parse(init?.body as string)).toMatchObject({
      family: "xiaomi",
      app_version: "0.3.20",
      checks: { calls: true, battery: false },
    });

    await act(async () => button("Phone setup").click());
    const lines = [...host.querySelectorAll('ol[aria-label="Phone setup"] li')];
    expect(lines).toHaveLength(9);
    expect(lines[0].hasAttribute("data-done")).toBe(true);

    // Notifications: the explainer comes before Android asks.
    const notifications = lines[2].querySelector("button")!;
    await act(async () => notifications.click());
    expect(host.textContent).toContain("What leaves your phone");
    expect(sent.some((item) => item.method === "requestNotifications")).toBe(
      false,
    );
    await act(async () => button("Allow notifications").click());
    expect(sent.some((item) => item.method === "requestNotifications")).toBe(
      true,
    );
    expect(host.textContent).toContain("4 of 9 done");
  });

  it("walks the call recorder steps for the phone's brand", async () => {
    let checks = { ...CHECKS };
    const sent = fakePhone((message) => {
      if (message.method === "setupMark")
        checks = { ...checks, recorder: true };
      return setup(checks);
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}")),
    );
    await act(async () => root.render(<PhoneSetupBar />));
    await act(async () => button("Phone setup").click());
    const lines = [...host.querySelectorAll('ol[aria-label="Phone setup"] li')];
    await act(async () => lines[3].querySelector("button")!.click());
    expect(host.textContent).toContain("Record calls automatically");
    await act(async () => button("It").click());
    expect(sent.filter((item) => item.method === "setupMark")).toEqual([
      { method: "setupMark", args: { what: "recorder", done: true } },
    ]);
    expect(host.textContent).toContain("4 of 9 done");
  });

  it("hides once the phone is ready, and leaves out Autostart where a brand has none", async () => {
    const all = Object.fromEntries(
      Object.keys(CHECKS).map((key) => [key, true]),
    );
    fakePhone(() => setup(all));
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => new Response("{}")),
    );
    await act(async () => root.render(<PhoneSetupBar />));
    expect(host.innerHTML).toBe("");
    const samsung = parseSetup(
      setup({ ...CHECKS, autostart: true }, { autostartNeeded: false }),
    )!;
    expect(setupProgress(samsung)).toEqual({ done: 3, total: 8 });
    expect(recorderSteps("samsung").join(" ")).toContain("Auto record calls");
    expect(recorderSteps("nokia")).toEqual(recorderSteps("other"));
  });
});

describe("a seller's phone on Team", () => {
  const now = new Date("2026-10-18T06:00:00Z");
  const health = (extra: Partial<PhoneHealth> = {}): PhoneHealth => ({
    reported_at: "2026-10-18T05:00:00Z",
    app_version: "0.3.20",
    family: "xiaomi",
    checks: { ...CHECKS, notifications: true },
    done: 4,
    total: 9,
    call_log_on: true,
    synced_at: "2026-10-18T05:50:00Z",
    ...extra,
  });

  it("gives one dot and a few words", () => {
    expect(phoneDot(null, now)).toEqual({
      tone: "none",
      label: "No phone app",
      missing: [],
    });
    const warn = phoneDot(health(), now);
    expect(warn.tone).toBe("warn");
    expect(warn.label).toBe("4 of 9 set up");
    expect(warn.missing).toContain("Battery unrestricted");
    expect(
      phoneDot(health({ synced_at: "2026-10-18T01:00:00Z" }), now),
    ).toMatchObject({ tone: "bad", label: "Last call check 5 h ago" });
    const ready = Object.fromEntries(
      Object.keys(CHECKS).map((key) => [key, true]),
    );
    expect(phoneDot(health({ checks: ready }), now).tone).toBe("good");
  });

  it("shows the dot in the Phone column", async () => {
    // PhoneCell reads the real clock: the phone reported and checked just now.
    const just = new Date().toISOString();
    const rep = {
      phone: health({ reported_at: just, synced_at: just }),
    } as RepView;
    await act(async () => root.render(<PhoneCell rep={rep} />));
    const cell = host.querySelector("[data-tone]")!;
    expect(cell.getAttribute("data-tone")).toBe("warn");
    expect(cell.getAttribute("title")).toContain("To do: Call recorder on");
  });
});
