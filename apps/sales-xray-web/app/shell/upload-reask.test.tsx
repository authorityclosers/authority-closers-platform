import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { UploadReask } from "./upload-reask";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const phone = vi.hoisted(() => ({
  inApp: true,
  uploadsOn: false,
  notifications: false,
  folderPicked: false,
  asked: [] as string[],
  consentNeeded: false,
  missing: [] as unknown[],
  setupOpened: [] as (string | undefined)[],
  tracked: [] as string[],
  setupDuringRead: false,
}));

vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  autoCaptureStatus: async () =>
    phone.inApp
      ? { supported: true, on: phone.uploadsOn, wifiOnly: false }
      : null,
  setupStatus: async () => ({
    checks: { notifications: phone.notifications },
    blocked: { notifications: false },
    folderPicked: phone.folderPicked,
  }),
  askNotifications: async () => {
    phone.asked.push("notices");
    phone.notifications = true;
    return null;
  },
  pickRecordingsFolder: async () => {
    phone.asked.push("folder");
    phone.folderPicked = true;
    return null;
  },
  autoCaptureSetup: async (on: boolean) => {
    phone.asked.push(`uploads:${on}`);
    if (phone.consentNeeded) throw new Error("standing_consent_required");
    // The seller tapped Turn on in Android's own consent dialog.
    phone.uploadsOn = on;
    return { supported: true, on, wifiOnly: false };
  },
  setupOpen: async () => false,
}));
vi.mock("../capture-setup/capture-setup-client", () => ({
  readMissingRecordings: async () => {
    if (phone.setupDuringRead)
      document.documentElement.setAttribute("data-sx-capture-setup", "");
    return {
      calls: phone.missing.length,
      tried: phone.missing.length,
      latest_at: null,
      items: phone.missing,
    };
  },
}));
vi.mock("../capture-setup/capture-setup-gate", () => ({
  openCaptureSetup: (step?: string) => phone.setupOpened.push(step),
}));
vi.mock("../telemetry", () => ({
  track: (_name: string, payload: { feature: string }) =>
    phone.tracked.push(payload.feature),
}));

const NOW = Date.parse("2026-11-18T10:30:00Z");
const CALL = {
  event_id: "call-fictional-1",
  lead_id: "lead-fictional-1",
  lead_name: "Asha Patil",
  at: "2026-11-18T10:10:00Z",
  seconds: 120,
};

let root: Root;
let host: HTMLDivElement;
const opened: string[] = [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  window.localStorage.clear();
  Object.assign(phone, {
    inApp: true,
    uploadsOn: false,
    notifications: false,
    folderPicked: false,
    asked: [],
    consentNeeded: false,
    missing: [CALL],
    setupOpened: [],
    tracked: [],
    setupDuringRead: false,
  });
  opened.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.documentElement.removeAttribute("data-sx-capture-setup");
  vi.useRealTimers();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 12; i += 1) await Promise.resolve();
  });
}

async function show() {
  await act(async () => {
    root.render(
      <UploadReask
        accountKey="acct-fictional"
        openLead={(href) => opened.push(href)}
      />,
    );
  });
  await settle();
}

async function remount() {
  act(() => root.unmount());
  root = createRoot(host);
  await show();
}

async function tap(label: string) {
  const found = [...host.querySelectorAll("button")].find(
    (b) =>
      (b.textContent ?? "").includes(label) ||
      b.getAttribute("aria-label") === label,
  );
  if (!found) throw new Error(`no button ${label}: ${host.textContent}`);
  await act(async () => found.click());
  await settle();
}

it("names the call, turns uploads on step by step, then opens the lead", async () => {
  await show();
  expect(host.textContent).toContain(
    "Your call with Asha Patil at 3:40 PM wasn't checked",
  );
  expect(host.textContent).toContain("2 min call");
  await tap("Turn uploads on");
  expect(host.textContent).toContain("Step 1 of 3");
  await tap("Allow notices");
  await tap("Choose the folder");
  expect(host.textContent).toContain(
    "Calls saved while uploads were off: you choose next",
  );
  await tap("Turn uploads on");
  expect(phone.asked).toEqual(["notices", "folder", "uploads:true"]);
  expect(host.textContent).toContain("Uploads are on");
  expect(phone.tracked).toEqual([
    "upload_reask_shown",
    "upload_reask_started",
    "upload_reask_on",
  ]);
  await tap("Open Asha");
  expect(opened).toEqual(["/leads?lead=lead-fictional-1"]);
  expect(host.querySelector("[data-upload-reask]")).toBeNull();
});

it("never agrees for the seller: without their agreement the setup asks afresh", async () => {
  phone.notifications = true;
  phone.folderPicked = true;
  phone.consentNeeded = true;
  await show();
  await tap("Turn uploads on");
  expect(host.textContent).toContain("Step 1 of 1");
  await tap("Turn uploads on");
  expect(phone.uploadsOn).toBe(false);
  expect(phone.setupOpened).toEqual(["uploads"]);
  expect(host.querySelector("[data-upload-reask]")).toBeNull();
});

it("skipping leaves uploads off and says so", async () => {
  phone.notifications = true;
  phone.folderPicked = true;
  await show();
  await tap("Turn uploads on");
  await tap("Skip for now");
  expect(host.textContent).toContain("Uploads are still off");
  expect(phone.asked).toEqual([]);
});

it("never with uploads on, outside the app, over the setup, or twice for the same call", async () => {
  phone.uploadsOn = true;
  await show();
  expect(host.querySelector("[data-upload-reask]")).toBeNull();

  phone.uploadsOn = false;
  phone.inApp = false;
  await remount();
  expect(host.querySelector("[data-upload-reask]")).toBeNull();

  phone.inApp = true;
  document.documentElement.setAttribute("data-sx-capture-setup", "");
  await remount();
  expect(host.querySelector("[data-upload-reask]")).toBeNull();
  // Once the setup is gone, the card looks again at once.
  document.documentElement.removeAttribute("data-sx-capture-setup");
  await settle();
  expect(host.querySelector("[data-upload-reask]")).not.toBeNull();
  await tap("Close");
  await remount();
  expect(host.querySelector("[data-upload-reask]")).toBeNull();
});

it("a setup that opens while it looks puts the card off until the setup is gone", async () => {
  // The setup starts deciding while the server answers.
  phone.setupDuringRead = true;
  await show();
  expect(host.querySelector("[data-upload-reask]")).toBeNull();
  phone.setupDuringRead = false;
  document.documentElement.removeAttribute("data-sx-capture-setup");
  await settle();
  expect(host.querySelector("[data-upload-reask]")).not.toBeNull();
});
