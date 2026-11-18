import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { MissedAlert } from "./missed-alert";
import type { UpdateNotification } from "./updates-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const phone = vi.hoisted(() => ({
  inApp: true,
  checks: { notifications: false, battery: true } as Record<string, boolean>,
  callAccess: true,
  audio: false,
  asked: [] as string[],
  refuseCallAccess: false,
}));

vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.inApp,
  setupStatus: async () =>
    phone.inApp ? { checks: { ...phone.checks } } : null,
  phoneStatus: async () =>
    phone.inApp ? { callAccess: phone.callAccess, audio: phone.audio } : null,
  askNotifications: async () => {
    phone.asked.push("notifications");
    phone.checks.notifications = true;
    return null;
  },
  askCallAccess: async () => {
    phone.asked.push("phone");
    if (phone.refuseCallAccess) throw new Error("phone_timeout");
    phone.callAccess = true;
    return true;
  },
  askRecordingAccess: async () => {
    phone.asked.push("audio");
    phone.audio = true;
    return true;
  },
  setupOpen: async (what: string) => {
    phone.asked.push(`open:${what}`);
    return false;
  },
}));
vi.mock("./push-keeper", () => ({ keepPushAddress: async () => undefined }));

const NOW = Date.parse("2026-11-18T06:00:00Z");

function line(over: Partial<UpdateNotification> = {}): UpdateNotification {
  return {
    id: "line-1",
    kind: "lead_new",
    title: "New lead: Rohan Deshmukh",
    href: "/leads?lead=lead-fictional-1",
    urgent: true,
    created_at: "2026-11-18T05:50:00Z",
    read: false,
    body: "Meta ad · Home loan",
    ...over,
  };
}

let root: Root;
let host: HTMLDivElement;
const opened: string[] = [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  window.localStorage.clear();
  phone.inApp = true;
  phone.checks = { notifications: false, battery: true };
  phone.callAccess = true;
  phone.audio = false;
  phone.asked = [];
  phone.refuseCallAccess = false;
  opened.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

async function show(lines: UpdateNotification[]) {
  await act(async () => {
    root.render(
      <MissedAlert
        lines={lines}
        ready
        accountKey="acct-fictional"
        openLead={(href) => opened.push(href)}
      />,
    );
  });
  await settle();
}

function button(label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll("button")].find(
    (b) =>
      (b.textContent ?? "").includes(label) ||
      b.getAttribute("aria-label") === label,
  );
  if (!found) throw new Error(`no button ${label}: ${host.textContent}`);
  return found;
}

async function tap(label: string) {
  await act(async () => button(label).click());
  await settle();
}

it("names the missed lead and walks only the steps still needed to All set, then opens the lead", async () => {
  await show([line()]);
  expect(host.textContent).toContain("Missed alert");
  expect(host.textContent).toContain("Rohan Deshmukh");
  expect(host.textContent).toContain("Meta ad");
  await tap("Turn on alerts");
  expect(host.textContent).toContain("Step 1 of 2");
  await tap("Allow notifications");
  expect(host.textContent).toContain("Step 2 of 2");
  expect(host.textContent).toContain("Music and audio");
  await tap("Allow music and audio");
  expect(phone.asked).toEqual(["notifications", "audio"]);
  expect(host.textContent).toContain("All set");
  await tap("Open Rohan");
  expect(opened).toEqual(["/leads?lead=lead-fictional-1"]);
  expect(host.querySelector("[data-missed-alert]")).toBeNull();
});

it("a refused ask moves on instead of sticking, and the end says alerts are still off when they are", async () => {
  phone.callAccess = false;
  phone.refuseCallAccess = true;
  await show([line()]);
  await tap("Turn on alerts");
  await tap("Skip for now");
  expect(host.textContent).toContain("Phone and call log");
  await tap("Allow phone and calls");
  expect(host.textContent).toContain("Music and audio");
  await tap("Skip for now");
  expect(host.textContent).toContain("Alerts are still off");
  expect(host.textContent).not.toContain("All set");
});

it("never shows when notifications are on, outside the app, for a read line, or twice for the same line", async () => {
  phone.checks.notifications = true;
  await show([line()]);
  expect(host.querySelector("[data-missed-alert]")).toBeNull();

  phone.checks.notifications = false;
  phone.inApp = false;
  await show([line({ id: "line-2" })]);
  expect(host.querySelector("[data-missed-alert]")).toBeNull();

  phone.inApp = true;
  await show([line({ id: "line-3", read: true })]);
  expect(host.querySelector("[data-missed-alert]")).toBeNull();

  await show([line({ id: "line-4" })]);
  expect(host.querySelector("[data-missed-alert]")).not.toBeNull();
  await tap("Close");
  act(() => root.unmount());
  root = createRoot(host);
  await show([line({ id: "line-4" })]);
  expect(host.querySelector("[data-missed-alert]")).toBeNull();
});

it("shows over the permissions page, which stays up while notifications are off", async () => {
  document.documentElement.setAttribute("data-sx-permissions", "");
  await show([line({ id: "line-perm" })]);
  const card = host.querySelector("dialog[data-missed-alert]");
  expect(card).not.toBeNull();
  expect(card?.hasAttribute("open")).toBe(true);
  document.documentElement.removeAttribute("data-sx-permissions");
});
