// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { dismissNotice, NoticeCenter, NoticeDock } from "../notice-center";
import { WorkspaceAccessContext } from "../workspace-access";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";
import { PermissionsGate } from "./permissions-gate";
import { PERMISSIONS_ATTRIBUTE } from "./permissions-rules";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The reminder with the real notice center (Redmi, v1.35 staging, 3 Nov 2026:
// after Not now, "Finish setting up" left by itself after 5 s). The consent is
// on, so only call history waits; fictional data throughout.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));
vi.mock("../settings/auto-analysis-client", async (original) => ({
  ...(await original<object>()),
  readAutoAnalysis: vi.fn(async () => ({
    schema: "sales-xray-auto-analysis/1",
    state: "on",
    can_start: true,
    notice: {
      version: "auto-analysis-v1",
      language: "en",
      title: "Analyse my calls automatically",
      text: "When I record a sales call with Sales X-Ray in Fictional Homes, the customer knows the call is recorded.",
      policy_sha256: "a".repeat(64),
    },
  })),
}));
vi.mock("../acquisition-client", async (original) => ({
  ...(await original<object>()),
  acquisition: vi.fn(async () => ({})),
  parsePolicy: () => ({ policy_sha256: "b".repeat(64) }),
}));
vi.mock("./capture-setup-client", async (original) => ({
  ...(await original<object>()),
  recordCaptureSetup: vi.fn(async () => ({})),
}));

type Listener = (event: { data: string }) => void;
const ALL = { calls: true, notifications: true, callLog: true, contacts: true };
let root: Root;
let host: HTMLDivElement;

function fakePhone(checks: () => Record<string, boolean>) {
  const listeners: Listener[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as { id: string; method: string };
      const result =
        message.method === "callLogStatus"
          ? { on: false, sims: [{ id: "sim-1", label: "SIM 1" }] }
          : {
              checks: checks(),
              family: "xiaomi",
              model: "Phone",
              version: "1.0.60",
              device: "install-fictional-1",
              folderPickSupported: true,
              folderPicked: true,
              callLogSupported: true,
            };
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  });
}

async function settle() {
  for (let i = 0; i < 12; i++) await act(async () => await Promise.resolve());
}

async function mount({ dock = false } = {}) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: "t" },
          workspaces: [
            {
              tenant_id: "t",
              kind: "organisation",
              name: "Fictional Homes",
              role: "member",
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        {dock ? <NoticeDock /> : null}
        <PermissionsGate />
        <NoticeCenter />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
}

/** Closed and opened again: a fresh page, as at the next app open. */
async function reopenApp() {
  await act(async () => root.unmount());
  await act(async () => dismissNotice("permissions-later"));
  window.sessionStorage.clear();
  root = createRoot(host);
  await mount();
}

async function resume() {
  await act(async () =>
    window.dispatchEvent(
      new CustomEvent("sx-phone", { detail: { event: "resume" } }),
    ),
  );
  await settle();
}

const byLabel = (label: string) => {
  const found = host.querySelector<HTMLButtonElement>(
    `button[aria-label="${label}"]`,
  );
  if (!found) throw new Error(`no button ${label}: ${host.textContent}`);
  return found;
};
const finish = () => {
  const found = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Finish",
  );
  if (!found) throw new Error(`no Finish: ${host.textContent}`);
  return found;
};
const reminder = () => host.textContent?.includes("Finish setting up");

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  window.localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  await act(async () => dismissNotice("permissions-later"));
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.sessionStorage.clear();
  document.documentElement.removeAttribute(PERMISSIONS_ATTRIBUTE);
  document.documentElement.removeAttribute(CAPTURE_SETUP_ATTRIBUTE);
});

it("keeps the reminder after Not now until Finish or its X, once per app open", async () => {
  let notifications = true;
  fakePhone(() => ({ ...ALL, callLog: false, notifications }));
  await mount();
  // It never leaves by itself: the clock runs from before it arrives.
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  await act(async () => byLabel("Not now: Call log").click());
  await settle();
  expect(reminder()).toBe(true);
  await act(async () => vi.advanceTimersByTime(60_000));
  vi.useRealTimers();
  expect(reminder()).toBe(true);
  // Finish: the checklist again with the put-off row; put off again, no second reminder.
  await act(async () => finish().click());
  await settle();
  expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
  expect(reminder()).toBe(false);
  await act(async () => byLabel("Not now: Call log").click());
  await settle();
  expect(host.querySelector("dialog")).toBeNull();
  expect(reminder()).toBe(false);
  // The next app open shows it again.
  await reopenApp();
  expect(host.querySelector("dialog")).toBeNull();
  expect(reminder()).toBe(true);
  // Its X closes it for this open, even when the checklist comes back for a
  // permission taken away and closes again.
  await act(async () => byLabel("Dismiss").click());
  await settle();
  expect(reminder()).toBe(false);
  notifications = false;
  await resume();
  expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
  notifications = true;
  await act(async () => byLabel("Allow Notifications").click());
  await settle();
  expect(host.querySelector("dialog")).toBeNull();
  expect(reminder()).toBe(false);
});

it("leaves once the put-off row is done", async () => {
  let callLog = false;
  fakePhone(() => ({ ...ALL, callLog }));
  await mount();
  await act(async () => byLabel("Not now: Call log").click());
  await settle();
  expect(reminder()).toBe(true);
  callLog = true;
  await resume();
  expect(reminder()).toBe(false);
});

it("waits while a first-run screen fills the page, so it never covers its buttons", async () => {
  fakePhone(() => ({ ...ALL, callLog: false }));
  await mount();
  document.documentElement.setAttribute(CAPTURE_SETUP_ATTRIBUTE, "");
  await act(async () => byLabel("Not now: Call log").click());
  await settle();
  expect(host.querySelector("dialog")).toBeNull();
  expect(reminder()).toBe(false);
  await act(async () =>
    document.documentElement.removeAttribute(CAPTURE_SETUP_ATTRIBUTE),
  );
  await settle();
  expect(reminder()).toBe(true);
});

it("is the line above the rows on a phone page with a dock, not a corner card over them", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  fakePhone(() => ({ ...ALL, callLog: false }));
  await mount({ dock: true });
  await act(async () => byLabel("Not now: Call log").click());
  await settle();
  const dock = host.querySelector("[data-notice-dock]");
  expect(dock?.textContent).toContain("Finish setting up");
  expect(dock?.textContent).toContain("Finish");
});

it("waits while a sheet is up, so it never covers the sheet's buttons", async () => {
  // Redmi QA on production (10 Nov 2026): "Finish setting up" sat over the
  // account menu's Appearance, Add lead's footer, Notes, Remind me and Move.
  fakePhone(() => ({ ...ALL, callLog: false }));
  await mount();
  await act(async () => byLabel("Not now: Call log").click());
  await settle();
  expect(reminder()).toBe(true);
  const sheet = document.createElement("dialog");
  document.body.append(sheet);
  await act(async () => sheet.setAttribute("open", ""));
  await settle();
  expect(reminder()).toBe(false);
  await act(async () => sheet.removeAttribute("open"));
  await settle();
  expect(reminder()).toBe(true);
  sheet.remove();
});
