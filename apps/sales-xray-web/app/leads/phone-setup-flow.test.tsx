import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import { parseSetup } from "./native-phone";
import { flowScreen, flowSteps, PhoneSetupFlow } from "./phone-setup-flow";
import { explainerFor, FOLDER_EXPLAINER } from "./phone-setup-words";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// "Set up this phone" (owner, 24 Oct 2026: "simpler least steps workflows"):
// one screen per thing still to do, one button, on to the next by itself.

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

const setup = (checks: Record<string, boolean>, extra = {}) => ({
  checks,
  family: "xiaomi",
  model: "Redmi Note 8 Pro",
  autostartNeeded: true,
  version: "0.3.100",
  device: "5c0de5a7-0000-4000-8000-00000000d5c5",
  ...extra,
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
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
}

const button = (label: string) => {
  const found = [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.trim().startsWith(label),
  );
  if (!found) throw new Error(`no button ${label}: ${host.textContent}`);
  return found;
};
const title = () => host.querySelector("h1")?.textContent;
const dots = () => host.querySelector("ol")?.getAttribute("aria-label");
const resume = () =>
  act(async () => {
    window.dispatchEvent(
      new CustomEvent("sx-phone", { detail: { event: "resume" } }),
    );
  });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
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
  resetBackCloseForTests();
});

describe("flowSteps", () => {
  it("asks only for what is missing, in order, and offers logging work calls", () => {
    expect(flowSteps(parseSetup(setup(NONE))!, null)).toEqual([
      "calls",
      "notifications",
      "recordings",
      "battery",
      "autostart",
      "callLog",
    ]);
    const play = parseSetup(
      setup(
        { ...NONE, calls: true },
        { autostartNeeded: false, callLogSupported: false, store: "play" },
      ),
    )!;
    expect(flowSteps(play, null)).toEqual([
      "notifications",
      "recordings",
      "battery",
    ]);
    const ready = parseSetup(
      setup(Object.fromEntries(Object.keys(NONE).map((key) => [key, true]))),
    )!;
    expect(flowSteps(ready, { available: true, enabled: true })).toEqual([]);
  });

  it("offers the recorder last, and only where it helps", () => {
    const off = parseSetup(setup(NONE, { recorderProfile: folderOff }))!;
    expect(flowSteps(off, { available: false, enabled: false }).at(-1)).toBe(
      "recorder",
    );
    const google = parseSetup(
      setup(NONE, {
        recorderProfile: {
          ...folderOff,
          kind: "private",
          recording: "private",
        },
      }),
    )!;
    expect(
      flowSteps(google, { available: false, enabled: false }),
    ).not.toContain("recorder");
  });
});

describe("flowScreen", () => {
  it("keeps Google Play's words on what is read and what leaves the phone", () => {
    const play = parseSetup(setup(NONE, { store: "play" }))!;
    const calls = flowScreen("calls", play, null);
    expect(calls.reads).toBe(explainerFor("calls", "play")?.reads);
    expect(calls.sends).toBe(explainerFor("calls", "play")?.sends);
    // Notifications read and send nothing: no fine print.
    expect(flowScreen("notifications", play, null).reads).toBeUndefined();
    const picks = parseSetup(
      setup(NONE, {
        store: "play",
        needsAllFiles: true,
        allFilesSupported: false,
        folderPickSupported: true,
      }),
    )!;
    expect(flowScreen("recordings", picks, null).action).toBe(
      FOLDER_EXPLAINER.allow,
    );
  });
});

describe("PhoneSetupFlow", () => {
  it("asks one thing at a time and moves on by itself, never turning call logging on", async () => {
    let checks = { ...NONE };
    const sent = fakePhone(({ method }) => {
      if (method === "requestCallAccess") {
        checks = { ...checks, calls: true };
        return { callAccess: true };
      }
      if (method === "setupOpen") return { opened: true };
      if (method === "setupMark") {
        checks = { ...checks, autostart: true };
        return setup(checks);
      }
      if (method === "callRecorderStatus")
        return { available: false, enabled: false };
      return setup(checks);
    });
    const closed = vi.fn();
    await act(async () => root.render(<PhoneSetupFlow onClose={closed} />));
    await settle();
    expect(dots()).toBe("Step 1 of 6");
    expect(title()).toBe("Calls and call history");
    // Why, and what is read, before Android asks.
    expect(host.textContent).toContain(explainerFor("calls", "direct")?.reads);
    expect(sent.map((item) => item.method)).not.toContain("requestCallAccess");

    await act(async () => button("Allow calls").click());
    await settle();
    expect(sent.map((item) => item.method)).toContain("requestCallAccess");
    expect(title()).toBe("Notifications");
    expect(dots()).toBe("Step 2 of 6");

    await act(async () => button("Later").click());
    await settle();
    expect(title()).toBe("Call recordings");
    await act(async () => button("Later").click());
    await settle();

    // Android's battery screen: the flow waits for the way back.
    expect(title()).toBe("Battery unrestricted");
    await act(async () => button("Open battery settings").click());
    await settle();
    expect(sent).toContainEqual({
      method: "setupOpen",
      args: { what: "battery" },
    });
    expect(button("Waiting").disabled).toBe(true);
    await resume();
    await settle();

    // Autostart: coming back counts, as Android can't say.
    expect(title()).toBe("Autostart");
    await act(async () => button("Open Autostart").click());
    await settle();
    await resume();
    await settle();
    expect(sent).toContainEqual({
      method: "setupMark",
      args: { what: "autostart", done: true },
    });

    expect(title()).toBe("Log work calls");
    await act(async () => button("Later").click());
    await settle();
    // The page that opened it takes it away.
    expect(closed).toHaveBeenCalledTimes(1);
    expect(sent.map((item) => item.method)).not.toContain("callLogSetup");
  });

  it("sets up one line only, for Settings' Fix, and Close keeps the rest for later", async () => {
    fakePhone(({ method }) =>
      method === "callRecorderStatus"
        ? { available: false, enabled: false }
        : setup(NONE),
    );
    const closed = vi.fn();
    await act(async () =>
      root.render(<PhoneSetupFlow only="battery" onClose={closed} />),
    );
    await settle();
    expect(title()).toBe("Battery unrestricted");
    expect(dots()).toBeUndefined();
    await act(async () =>
      (
        host.querySelector(
          '[aria-label="Close phone setup"]',
        ) as HTMLButtonElement
      ).click(),
    );
    await settle();
    expect(closed).toHaveBeenCalledTimes(1);
    expect(closed.mock.calls[0][0]?.checks.battery).toBe(false);
  });
});
