import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { buzz } from "../leads/native-phone";
import { resetBackCloseForTests } from "../ui/back-close";
import { PhoneSetupPanel, VibrationPanel } from "./phone-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Settings → Phone & alerts (owner, 24 Oct 2026: "simpler least steps
// workflows"): each line one tap from its fix; vibration in one tap.

type Listener = (event: { data: unknown }) => void;
type Sent = { method: string; args: Record<string, unknown> };

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

const CHECKS = {
  calls: true,
  recordings: true,
  notifications: true,
  recorder: false,
  folder: false,
  battery: false,
  autostart: true,
  testCall: false,
  callLog: true,
};

const setup = {
  checks: CHECKS,
  family: "xiaomi",
  model: "Redmi Note 8 Pro",
  autostartNeeded: true,
  version: "0.3.100",
  device: "5c0de5a7-0000-4000-8000-00000000d5c5",
};

let root: Root;
let host: HTMLDivElement;

async function settle() {
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
}

const buttons = (label: string) =>
  [...host.querySelectorAll("button")].filter(
    (item) => item.textContent?.trim() === label,
  );

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => new Response("{}")),
  );
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

it("shows what the phone still needs, each line one tap from its fix", async () => {
  fakePhone(({ method }) =>
    method === "callRecorderStatus"
      ? { available: false, enabled: false }
      : setup,
  );
  await act(async () => root.render(<PhoneSetupPanel />));
  await settle();
  expect(host.textContent).toContain("5 of 9 done");
  // Only what is left is listed; what is done is one line under it.
  const lines = [...host.querySelectorAll('ul[aria-label="Still to do"] li')];
  expect(lines).toHaveLength(4);
  expect(host.textContent).toContain(
    "Done: Calls and call history, Call recordings, Notifications",
  );
  // The recorder and battery have a Fix; the folder and the test call tick
  // by themselves.
  expect(buttons("Fix")).toHaveLength(2);

  await act(async () => buttons("Fix")[1].click());
  await settle();
  expect(host.querySelector("dialog h1")?.textContent).toBe(
    "Battery unrestricted",
  );
  // Just that line: no steps to count.
  expect(host.querySelector('dialog ol[aria-label^="Step"]')).toBeNull();
});

it("walks everything still to do from one button", async () => {
  fakePhone(({ method }) =>
    method === "callRecorderStatus"
      ? { available: false, enabled: false }
      : {
          ...setup,
          checks: { ...CHECKS, notifications: false },
        },
  );
  await act(async () => root.render(<PhoneSetupPanel />));
  await settle();
  await act(async () => buttons("Set up this phone")[0].click());
  await settle();
  expect(host.querySelector("dialog h1")?.textContent).toBe("Notifications");
  expect(
    host
      .querySelector('dialog ol[aria-label^="Step"]')
      ?.getAttribute("aria-label"),
  ).toBe("Step 1 of 2");
});

it("shows no phone setup, and no vibration, on a computer", async () => {
  await act(async () =>
    root.render(
      <>
        <PhoneSetupPanel />
        <VibrationPanel />
      </>,
    ),
  );
  await settle();
  expect(host.innerHTML).toBe("");
});

it("turns vibration off in one tap, and then nothing buzzes", async () => {
  const vibrate = vi.fn(() => true);
  vi.stubGlobal("navigator", { ...navigator, vibrate });
  // A phone's browser: a touch screen that vibrates.
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("coarse"),
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  await act(async () => root.render(<VibrationPanel />));
  const toggle = host.querySelector<HTMLButtonElement>(
    '[role="switch"][aria-label="Vibration"]',
  )!;
  expect(toggle.getAttribute("aria-checked")).toBe("true");
  buzz("tick");
  expect(vibrate).toHaveBeenCalledTimes(1);

  await act(async () => toggle.click());
  await settle();
  // No "are you sure" for a switch like this one.
  expect(host.querySelector("dialog[open]")).toBeNull();
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  buzz("tick");
  expect(vibrate).toHaveBeenCalledTimes(1);
});
