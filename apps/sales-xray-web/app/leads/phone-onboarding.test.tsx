import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ONBOARDED_KEY,
  openPhoneSetup,
  PhoneOnboarding,
} from "./phone-onboarding";
import { PhoneSetupBar } from "./phone-setup";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const consent = vi.hoisted(() => ({ status: "current" }));
vi.mock("../consent-renewal-client", () => ({
  readConsent: async () => ({ status: consent.status }),
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => ({ authenticated: true }),
}));
vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

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

const NONE = {
  calls: false,
  recordings: false,
  notifications: false,
  recorder: false,
  folder: false,
  battery: false,
  autostart: false,
  testCall: false,
  callLog: false,
};

const ALL = Object.fromEntries(Object.keys(NONE).map((key) => [key, true]));

const setup = (checks: Record<string, boolean>, recorderProfile?: unknown) => ({
  checks,
  family: "xiaomi",
  model: "Redmi Note 8 Pro",
  autostartNeeded: true,
  version: "0.3.65",
  device: "5c0de5a7-0000-4000-8000-00000000d5c5",
  recorderProfile,
});

let root: Root;
let host: HTMLDivElement;

async function settle() {
  for (let i = 0; i < 8; i++) await act(async () => await Promise.resolve());
}

function button(name: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === name,
  );
  if (!found) throw new Error(`no button ${name}: ${host.textContent}`);
  return found;
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  consent.status = "current";
  document.documentElement.removeAttribute("data-sx-consent");
  window.history.replaceState(null, "", "/leads");
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
  };
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("PhoneOnboarding", () => {
  it("opens Set up this phone after the Terms, then marks the phone onboarded", async () => {
    let checks = { ...ALL, calls: false };
    const sent = fakePhone(({ method }) => {
      if (method === "requestCallAccess") {
        checks = { ...checks, calls: true };
        return { callAccess: true };
      }
      if (method === "callRecorderStatus")
        return { available: false, enabled: false };
      return setup(checks);
    });
    await act(async () => root.render(<PhoneOnboarding />));
    await settle();
    expect(host.querySelector("h1")?.textContent).toBe(
      "Calls and call history",
    );
    expect(localStorage.getItem(ONBOARDED_KEY)).toBeNull();

    await act(async () => button("Allow calls").click());
    await settle();
    expect(sent.map((item) => item.method)).toContain("requestCallAccess");
    // Nothing else to do: the flow closes by itself, no "ready" screen to tap.
    expect(localStorage.getItem(ONBOARDED_KEY)).not.toBeNull();
    expect(host.textContent).toBe("");
  });

  it("waits while the Terms are not accepted, and shows nothing in a browser", async () => {
    consent.status = "renewal_required";
    fakePhone(({ method }) =>
      method === "setupStatus" ? setup(NONE) : { available: false },
    );
    await act(async () => root.render(<PhoneOnboarding />));
    await settle();
    expect(host.textContent).toBe("");

    vi.unstubAllGlobals();
    consent.status = "current";
    await act(async () => root.render(<PhoneOnboarding key="browser" />));
    await settle();
    expect(host.textContent).toBe("");
  });

  it("skips straight in when the phone already allows everything", async () => {
    fakePhone(({ method }) =>
      method === "setupStatus"
        ? setup(ALL)
        : { available: false, enabled: false },
    );
    await act(async () => root.render(<PhoneOnboarding />));
    await settle();
    expect(host.textContent).toBe("");
    expect(localStorage.getItem(ONBOARDED_KEY)).not.toBeNull();
  });
});

describe("Phone setup from anywhere", () => {
  it("opens over the page that is showing, already onboarded or not (Redmi #2)", async () => {
    localStorage.setItem(ONBOARDED_KEY, "2026-10-19T08:00:00.000Z");
    fakePhone(({ method }) =>
      method === "callRecorderStatus"
        ? { available: false, enabled: false }
        : setup({ ...ALL, calls: false }),
    );
    await act(async () => root.render(<PhoneOnboarding />));
    await settle();
    expect(host.textContent).toBe("");
    await act(async () => openPhoneSetup());
    await settle();
    expect(host.querySelector("h1")?.textContent).toBe(
      "Calls and call history",
    );
  });
});

describe("PhoneSetupBar after the first run", () => {
  it("leaves Leads, and More's #phone-setup still opens the checklist", async () => {
    localStorage.setItem(ONBOARDED_KEY, "2026-10-19T08:00:00.000Z");
    fakePhone(({ method }) =>
      method === "setupStatus" ? setup({ ...NONE, calls: true }) : {},
    );
    await act(async () => root.render(<PhoneSetupBar />));
    await settle();
    expect(host.textContent).not.toContain("Phone setup");

    act(() => root.unmount());
    root = createRoot(host);
    window.history.replaceState(null, "", "/leads#phone-setup");
    await act(async () => root.render(<PhoneSetupBar />));
    await settle();
    expect(document.body.textContent).toContain("Calls and call history");
  });
});
