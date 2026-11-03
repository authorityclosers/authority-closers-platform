// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseSetup, type SetupStatus } from "../leads/native-phone";
import { WorkspaceAccessContext } from "../workspace-access";
import { askConsent, PermissionsGate } from "./permissions-gate";
import {
  PERMISSIONS_ATTRIBUTE,
  batterySaidDone,
  checklistOpen,
  permissionItems,
  permissionsMissing,
  putOffKey,
  reminders,
  type ConsentFact,
} from "./permissions-rules";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The standing consent as the server has it; fictional words and hashes.
const mocks = vi.hoisted(() => {
  const consent = { state: "on", version: "auto-analysis-v1" };
  const words =
    "When I record a sales call with Sales X-Ray in Fictional Homes, the customer knows the call is recorded.";
  const view = () => ({
    schema: "sales-xray-auto-analysis/1",
    state: consent.state,
    can_start: true,
    notice: {
      version: consent.version,
      language: "en",
      title: "Analyse my calls automatically",
      text: words,
      policy_sha256: "a".repeat(64),
    },
  });
  return {
    consent,
    words,
    readAutoAnalysis: vi.fn(async () => view()),
    chooseAutoAnalysis: vi.fn(async () => {
      consent.state = "on";
      return view();
    }),
    recordCaptureSetup: vi.fn(async () => ({})),
    notify: vi.fn(),
    dismissNotice: vi.fn(),
  };
});
vi.mock("../settings/auto-analysis-client", async (original) => ({
  ...(await original<object>()),
  readAutoAnalysis: mocks.readAutoAnalysis,
  chooseAutoAnalysis: mocks.chooseAutoAnalysis,
}));
vi.mock("../acquisition-client", async (original) => ({
  ...(await original<object>()),
  acquisition: vi.fn(async () => ({})),
  parsePolicy: () => ({ policy_sha256: "b".repeat(64) }),
}));
vi.mock("./capture-setup-client", async (original) => ({
  ...(await original<object>()),
  recordCaptureSetup: mocks.recordCaptureSetup,
}));
vi.mock("../notice-center", async (original) => ({
  ...(await original<object>()),
  notify: mocks.notify,
  dismissNotice: mocks.dismissNotice,
}));

// Owner, 30 Oct 2026 (fix 5): "call log, phone, contacts, notifications, and
// access to the recordings folder ... the app cannot be used until all are
// granted", without locking anyone out on a build that can't ask. Owner, 3 Nov
// 2026: in an organisation's workspace, stricter, at every open and return.

const ALL = {
  calls: true,
  notifications: true,
  callLog: true,
  contacts: true,
};

const status = (checks: Record<string, boolean>, extra = {}) =>
  parseSetup({
    checks,
    family: "xiaomi",
    model: "Redmi 13",
    version: "1.0.60",
    device: "install-fictional-1",
    folderPickSupported: true,
    folderPicked: true,
    callLogSupported: true,
    ...extra,
  }) as SetupStatus;

const ORG = { organisation: true };
const PERSONAL = { organisation: false };
const states = (
  value: SetupStatus,
  where: { organisation: boolean; consent?: ConsentFact } = ORG,
) =>
  Object.fromEntries(
    permissionItems(value, where).map((item) => [item.key, item.state]),
  );
const consentIs = (
  state: "on" | "off" | "ask" | "unavailable",
  version = "v1",
) => ({ state, words: mocks.words, version }) as const;

describe("permissionItems", () => {
  it("lists the rows in the owner's order; Personal keeps its five", () => {
    // A build that declares contacts (apps PR #18); without it there's no row.
    const none = status({ contacts: false }, { folderPicked: false });
    expect(
      permissionItems(status({}), ORG).some((item) => item.key === "contacts"),
    ).toBe(false);
    expect(
      permissionItems(none, { ...ORG, consent: consentIs("off") }).map(
        (item) => item.key,
      ),
    ).toEqual([
      "callLog",
      "phone",
      "contacts",
      "notifications",
      "recordings",
      "battery",
      "autoAnalysis",
    ]);
    expect(permissionItems(none, PERSONAL).map((item) => item.key)).toEqual([
      "callLog",
      "phone",
      "contacts",
      "notifications",
      "recordings",
    ]);
    expect(permissionsMissing(permissionItems(none, ORG))).toBe(true);
    expect(permissionsMissing(permissionItems(status(ALL), ORG))).toBe(false);
  });

  it("needs phone, contacts, notifications and the folder in an organisation; contacts never hold Personal", () => {
    const noContacts = status({ ...ALL, contacts: false });
    expect(permissionsMissing(permissionItems(noContacts, ORG))).toBe(true);
    expect(permissionsMissing(permissionItems(noContacts, PERSONAL))).toBe(
      false,
    );
    const required = permissionItems(status(ALL), ORG)
      .filter((item) => item.required)
      .map((item) => item.key);
    expect(required).toEqual([
      "phone",
      "contacts",
      "notifications",
      "recordings",
    ]);
  });

  it("offers call history, the battery and the consent with Not now, never holding the app", () => {
    const items = permissionItems(
      status({ ...ALL, callLog: false, battery: false }),
      { ...ORG, consent: consentIs("off") },
    );
    expect(permissionsMissing(items)).toBe(false);
    expect(
      items.filter((item) => item.canWait).map((item) => item.key),
    ).toEqual(["callLog", "battery", "autoAnalysis"]);
    // Not answered yet: the checklist opens for them once.
    expect(checklistOpen(items, new Set())).toBe(true);
    const later = new Set(items.filter((i) => i.canWait).map(putOffKey));
    expect(checklistOpen(items, later)).toBe(false);
    // The battery's Done is final: it never comes back as a reminder.
    expect(reminders(items, later).map((item) => item.key)).toEqual([
      "callLog",
      "autoAnalysis",
    ]);
  });

  it("offers settings once Android won't ask again", () => {
    expect(
      states(
        status(
          { ...ALL, notifications: false },
          { blocked: { notifications: true } },
        ),
      ).notifications,
    ).toBe("blocked");
  });

  it("names Autostart beside the battery on Xiaomi only", () => {
    const battery = (family: string) =>
      permissionItems(status({ ...ALL, battery: false }, { family }), ORG).find(
        (item) => item.key === "battery",
      );
    expect(battery("xiaomi")?.why).toContain("Autostart");
    expect(battery("xiaomi")?.why).toContain("No restrictions");
    expect(battery("oneplus")?.why).not.toContain("Autostart");
    expect(battery("oneplus")?.state).toBe("needed");
    expect(states(status({ ...ALL, battery: true })).battery).toBe("granted");
  });

  it("asks for the consent once, shows its sealed words, and asks again only for new words", () => {
    const row = (consent: ConsentFact) =>
      permissionItems(status(ALL), { ...ORG, consent }).find(
        (item) => item.key === "autoAnalysis",
      );
    expect(row(consentIs("off"))?.why).toBe(mocks.words);
    expect(row(consentIs("off"))?.state).toBe("needed");
    expect(row(consentIs("on"))?.state).toBe("granted");
    expect(row(consentIs("ask", "v2"))?.state).toBe("needed");
    expect(row(consentIs("unavailable"))).toBeUndefined();
    expect(row(null)).toBeUndefined();
    // Not now on the first words doesn't put off the next ones.
    const first = row(consentIs("off", "v1"));
    const next = row(consentIs("ask", "v2"));
    expect(first && next && putOffKey(first) !== putOffKey(next)).toBe(true);
    expect(
      checklistOpen(
        permissionItems(status(ALL), {
          ...ORG,
          consent: consentIs("ask", "v2"),
        }),
        new Set(first ? [putOffKey(first)] : []),
      ),
    ).toBe(true);
    // Never in a personal workspace.
    expect(
      permissionItems(status(ALL), {
        ...PERSONAL,
        consent: consentIs("off"),
      }).map((item) => item.key),
    ).not.toContain("autoAnalysis");
  });

  it("never locks anyone out over what this build can't ask for", () => {
    // Today's Google Play build: no call history yet, no contacts, older apps no folder picker.
    const play = status(
      { calls: true, notifications: true },
      { callLogSupported: false, folderPickSupported: false, store: "play" },
    );
    // Contacts, which no released build declares yet, isn't shown (phone QA on v1.36).
    expect(states(play)).toEqual({
      callLog: "later",
      phone: "granted",
      notifications: "granted",
      recordings: "update",
      battery: "update",
    });
    expect(permissionsMissing(permissionItems(play, ORG))).toBe(false);
  });

  it("never asks for call logging outside an organisation, where the phone refuses it", () => {
    const personal = status({ ...ALL, callLog: false });
    expect(states(personal, PERSONAL).callLog).toBe("elsewhere");
    expect(permissionsMissing(permissionItems(personal, PERSONAL))).toBe(false);
  });
});

type Sent = { method: string; args: Record<string, unknown> };
type Listener = (event: { data: unknown }) => void;

let root: Root;
let host: HTMLDivElement;

function fakePhone(checks: () => Record<string, boolean>, family = "xiaomi") {
  const listeners: Listener[] = [];
  const sent: Sent[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as Sent & { id: string };
      sent.push({ method: message.method, args: message.args });
      const result =
        message.method === "callLogStatus"
          ? { on: false, sims: [{ id: "sim-1", label: "SIM 1" }] }
          : {
              checks: checks(),
              family,
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
  return sent;
}

async function settle() {
  for (let i = 0; i < 12; i++) await act(async () => await Promise.resolve());
}

async function mount(kind: "organisation" | "personal" = "organisation") {
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
              kind,
              name: "Fictional Homes",
              role: "member",
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <PermissionsGate />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
}

async function resume() {
  await act(async () =>
    window.dispatchEvent(
      new CustomEvent("sx-phone", { detail: { event: "resume" } }),
    ),
  );
  await settle();
}

const button = (label: string) => {
  const found = host.querySelector<HTMLButtonElement>(
    `button[aria-label="${label}"]`,
  );
  if (!found) throw new Error(`no button ${label}: ${host.textContent}`);
  return found;
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  mocks.consent.state = "on";
  mocks.consent.version = "auto-analysis-v1";
  window.localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  document.documentElement.removeAttribute(PERMISSIONS_ATTRIBUTE);
});

describe("PermissionsGate", () => {
  it("shows the battery On, or Check with Done for when Android can't see it, never holding the app", async () => {
    fakePhone(() => ({ ...ALL, battery: false }));
    await mount();
    expect(host.textContent).toContain("Battery");
    expect(host.textContent).toContain("No restrictions, then allow Autostart");
    await act(async () => button("Done: Battery").click());
    await settle();
    // Done is the seller's word: no reminder, and the checklist closes.
    expect(host.querySelector("dialog")).toBeNull();
    expect(mocks.notify).not.toHaveBeenCalledWith(
      expect.objectContaining({ id: "permissions-later" }),
    );
    await act(async () => root.unmount());
    root = createRoot(host);
    fakePhone(() => ({ ...ALL, battery: true }));
    mocks.consent.state = "off";
    await mount();
    const battery = [...host.querySelectorAll("li")].find((row) =>
      row.textContent?.includes("Battery"),
    );
    expect(battery?.textContent).toContain("On");
  });

  it("opens the consent row again from the Calls line's Turn on", async () => {
    mocks.consent.state = "off";
    fakePhone(() => ALL);
    await mount();
    await act(async () =>
      button("Not now: Analyse my calls automatically").click(),
    );
    await settle();
    expect(host.querySelector("dialog")).toBeNull();
    await act(async () => askConsent());
    await settle();
    expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
    expect(host.textContent).toContain(mocks.words);
    expect(button("Turn on Analyse my calls automatically")).toBeTruthy();
  });

  it("covers the app until contacts and notifications are allowed, then lets it be used", async () => {
    let notifications = false;
    let contacts = false;
    const sent = fakePhone(() => ({ ...ALL, notifications, contacts }));
    await mount();
    expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
    expect(host.textContent).toContain("2 left.");
    expect(document.documentElement.hasAttribute(PERMISSIONS_ATTRIBUTE)).toBe(
      true,
    );
    contacts = true;
    await act(async () => button("Allow Contacts").click());
    await settle();
    expect(sent.map((message) => message.method)).toContain("requestContacts");
    expect(host.textContent).toContain("1 left.");
    notifications = true;
    await act(async () => button("Allow Notifications").click());
    await settle();
    expect(sent.map((message) => message.method)).toContain(
      "requestNotifications",
    );
    expect(host.querySelector("dialog")).toBeNull();
    expect(document.documentElement.hasAttribute(PERMISSIONS_ATTRIBUTE)).toBe(
      false,
    );
  });

  it("comes back at the next return when a permission is taken away in Android's settings", async () => {
    let notifications = true;
    fakePhone(() => ({ ...ALL, notifications }));
    await mount();
    expect(host.querySelector("dialog")).toBeNull();
    notifications = false;
    await resume();
    expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
    expect(button("Allow Notifications")).toBeTruthy();
  });

  it("keeps Personal as it was: contacts don't wait, no battery or consent row, no Not now", async () => {
    let calls = true;
    const sent = fakePhone(() => ({ ...ALL, contacts: false, calls }));
    await mount("personal");
    expect(host.querySelector("dialog")).toBeNull();
    expect(mocks.readAutoAnalysis).not.toHaveBeenCalled();
    // A return without a visit to Android's settings reads nothing here.
    calls = false;
    const before = sent.length;
    await resume();
    expect(sent.length).toBe(before);
    expect(host.querySelector("dialog")).toBeNull();
  });

  it("offers Open settings after a refusal, and has no way past what is needed", async () => {
    const sent = fakePhone(() => ({ ...ALL, calls: false }));
    await mount();
    expect(host.textContent).not.toContain("Not now");
    await act(async () => button("Allow Phone").click());
    await settle();
    expect(sent.map((message) => message.method)).toContain(
      "requestCallAccess",
    );
    await act(async () => button("Open settings for Phone").click());
    await settle();
    expect(sent.at(-1)).toEqual({
      method: "setupOpen",
      args: { what: "appSettings" },
    });
    expect(host.querySelector("dialog")).not.toBeNull();
  });

  it("turns call logging on for the first SIM", async () => {
    let callLog = false;
    const sent = fakePhone(() => ({ ...ALL, callLog }));
    await mount();
    callLog = true;
    await act(async () => button("Allow Call log").click());
    await settle();
    expect(sent.find((message) => message.method === "callLogSetup")).toEqual({
      method: "callLogSetup",
      args: { on: true, sim: "sim-1" },
    });
  });

  it("puts call history off with Not now, and keeps one slim reminder instead", async () => {
    fakePhone(() => ({ ...ALL, callLog: false }));
    await mount();
    expect(host.querySelector("dialog")).not.toBeNull();
    await act(async () => button("Not now: Call log").click());
    await settle();
    expect(host.querySelector("dialog")).toBeNull();
    expect(mocks.notify).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "permissions-later",
        message: "Call log",
        slim: true,
      }),
    );
    // Not asked again at the next return.
    await resume();
    expect(host.querySelector("dialog")).toBeNull();
  });

  it("opens the battery page from its row", async () => {
    const sent = fakePhone(() => ({ ...ALL, battery: false }), "oneplus");
    await mount();
    await act(async () => button("Check Battery").click());
    await settle();
    expect(sent).toContainEqual({
      method: "setupOpen",
      args: { what: "battery" },
    });
  });

  it("asks for the consent once with its sealed words, then uploads follow, and never asks again", async () => {
    mocks.consent.state = "off";
    const sent = fakePhone(() => ALL);
    await mount();
    expect(host.textContent).toContain(mocks.words);
    // Never pre-ticked: a button to tap, not a box already ticked.
    expect(host.querySelector('input[type="checkbox"]')).toBeNull();
    await act(async () =>
      button("Turn on Analyse my calls automatically").click(),
    );
    await settle();
    expect(mocks.chooseAutoAnalysis).toHaveBeenCalledTimes(1);
    expect(mocks.chooseAutoAnalysis).toHaveBeenCalledWith({
      decision: "granted",
      notice: expect.objectContaining({ version: "auto-analysis-v1" }),
      uploadPolicySha256: "b".repeat(64),
    });
    expect(sent).toContainEqual({
      method: "autoCaptureSetup",
      args: { on: true, wifiOnly: false },
    });
    expect(host.querySelector("dialog")).toBeNull();
    // A later open: it is on, so nothing asks.
    await act(async () => root.unmount());
    root = createRoot(host);
    await mount();
    expect(host.querySelector("dialog")).toBeNull();
    expect(mocks.chooseAutoAnalysis).toHaveBeenCalledTimes(1);
  });

  it("asks again after new consent words, even after Not now on the old ones", async () => {
    mocks.consent.state = "off";
    fakePhone(() => ALL);
    await mount();
    await act(async () =>
      button("Not now: Analyse my calls automatically").click(),
    );
    await settle();
    expect(host.querySelector("dialog")).toBeNull();
    expect(mocks.recordCaptureSetup).toHaveBeenCalledWith({
      outcome: "declined",
    });
    // The same words: still put off.
    await resume();
    expect(host.querySelector("dialog")).toBeNull();
    // New words (a notice version bump): asked again.
    mocks.consent.state = "ask";
    mocks.consent.version = "auto-analysis-v2";
    await resume();
    expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
    expect(button("Turn on Analyse my calls automatically")).toBeTruthy();
  });

  it("shows nothing in a browser", async () => {
    await mount();
    expect(host.querySelector("dialog")).toBeNull();
    expect(document.documentElement.hasAttribute(PERMISSIONS_ATTRIBUTE)).toBe(
      false,
    );
  });

  // Phone QA on v1.36 (3 Nov 2026): "choose Not now" over the battery alone, and
  // Done, then Battery and Autostart again in Set up this phone.
  it("names only the buttons on screen, and the battery's Done counts for Set up this phone", async () => {
    const sent = fakePhone(() => ({ ...ALL, battery: false }));
    await mount();
    expect(host.textContent).toContain(
      "This helps too. Check it, or tap Done once it's set.",
    );
    expect(host.textContent).not.toContain("choose Not now");
    expect(batterySaidDone()).toBe(false);
    await act(async () => button("Done: Battery").click());
    await settle();
    expect(batterySaidDone()).toBe(true);
    expect(sent).toContainEqual({
      method: "setupMark",
      args: { what: "autostart", done: true },
    });
  });

  it("says Not now while a row has it", async () => {
    fakePhone(() => ({ ...ALL, battery: false, callLog: false }));
    await mount();
    expect(host.textContent).toContain(
      "These help too. Allow them, or choose Not now.",
    );
  });
});
