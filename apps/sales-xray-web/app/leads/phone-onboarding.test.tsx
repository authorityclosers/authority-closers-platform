import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseSetup } from "./native-phone";
import {
  ONBOARDED_KEY,
  onboardingSteps,
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

const setup = (checks: Record<string, boolean>, recorderProfile?: unknown) => ({
  checks,
  family: "xiaomi",
  model: "Redmi Note 8 Pro",
  autostartNeeded: true,
  version: "0.3.65",
  device: "5c0de5a7-0000-4000-8000-00000000d5c5",
  recorderProfile,
});

const folderOff = {
  kind: "folder",
  maker: "xiaomi",
  dialerLabel: "Xiaomi Phone",
  recording: "off",
  folders: [],
};

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

describe("onboardingSteps", () => {
  it("asks only for what is missing, in order, the recorder last", () => {
    const status = parseSetup(setup(NONE, folderOff))!;
    expect(
      onboardingSteps(status, { available: true, enabled: false }),
    ).toEqual(["calls", "notifications", "recordings", "recorder"]);
    const done = parseSetup(
      setup({ ...NONE, calls: true, notifications: true, recordings: true }),
    )!;
    expect(onboardingSteps(done, { available: true, enabled: true })).toEqual(
      [],
    );
  });

  it("offers the dialer's own recorder only when it saves to a folder and is off (Play build)", () => {
    const off = parseSetup(setup(NONE, folderOff))!;
    expect(
      onboardingSteps(off, { available: false, enabled: false }),
    ).toContain("recorder");
    const google = parseSetup(
      setup(NONE, { ...folderOff, kind: "private", recording: "private" }),
    )!;
    expect(
      onboardingSteps(google, { available: false, enabled: false }),
    ).not.toContain("recorder");
  });
});

describe("PhoneOnboarding", () => {
  it("walks one permission at a time, then marks the phone onboarded", async () => {
    const sent = fakePhone(({ method }) => {
      if (method === "setupStatus") return setup(NONE, folderOff);
      if (method === "callRecorderStatus")
        return { available: true, enabled: false };
      if (method === "requestCallAccess") return { callAccess: true };
      if (method === "callRecorderOpen") return { opened: true };
      return {};
    });
    await act(async () => root.render(<PhoneOnboarding />));
    await settle();
    expect(host.textContent).toContain("Step 1 of 4");
    expect(host.textContent).toContain("Calls and call history");

    await act(async () => button("Allow calls").click());
    await settle();
    expect(sent.map((item) => item.method)).toContain("requestCallAccess");
    expect(host.textContent).toContain("Step 2 of 4");

    await act(async () => button("Not now").click());
    await settle();
    expect(host.textContent).toContain("Step 3 of 4");
    expect(sent.map((item) => item.method)).not.toContain(
      "requestNotifications",
    );

    await act(async () => button("Not now").click());
    await settle();
    expect(host.textContent).toContain("Record your calls (optional)");
    await act(async () => button("Open Accessibility").click());
    await settle();
    const methods = sent.map((item) => item.method);
    expect(methods).toEqual(
      expect.arrayContaining([
        "callRecorderConsent",
        "callRecorderSet",
        "callRecorderOpen",
      ]),
    );

    expect(host.textContent).toContain("Your phone is ready");
    expect(localStorage.getItem(ONBOARDED_KEY)).toBeNull();
    await act(async () => button("Open Sales Xray").click());
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
        ? setup({ ...NONE, calls: true, notifications: true, recordings: true })
        : { available: false, enabled: false },
    );
    await act(async () => root.render(<PhoneOnboarding />));
    await settle();
    expect(host.textContent).toBe("");
    expect(localStorage.getItem(ONBOARDED_KEY)).not.toBeNull();
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
