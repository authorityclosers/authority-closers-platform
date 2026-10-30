// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseSetup, type SetupStatus } from "../leads/native-phone";
import { WorkspaceAccessContext } from "../workspace-access";
import { PermissionsGate } from "./permissions-gate";
import {
  PERMISSIONS_ATTRIBUTE,
  permissionItems,
  permissionsMissing,
} from "./permissions-rules";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 30 Oct 2026 (fix 5): "call log, phone, contacts, notifications, and
// access to the recordings folder ... the app cannot be used until all are
// granted", without locking anyone out on a build that can't ask.

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
const states = (value: SetupStatus, where = ORG) =>
  Object.fromEntries(
    permissionItems(value, where).map((item) => [item.key, item.state]),
  );

describe("permissionItems", () => {
  it("lists the five in the owner's order and waits while any is missing", () => {
    const none = status({}, { folderPicked: false });
    expect(permissionItems(none, ORG).map((item) => item.key)).toEqual([
      "callLog",
      "phone",
      "contacts",
      "notifications",
      "recordings",
    ]);
    expect(permissionsMissing(permissionItems(none, ORG))).toBe(true);
    expect(permissionsMissing(permissionItems(status(ALL), ORG))).toBe(false);
    // Contacts alone never hold the app (orchestrator, 30 Oct 2026).
    expect(
      permissionsMissing(
        permissionItems(status({ ...ALL, contacts: false }), ORG),
      ),
    ).toBe(false);
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

  it("never locks anyone out over what this build can't ask for", () => {
    // Today's Google Play build: no call history yet, no contacts, older apps no folder picker.
    const play = status(
      { calls: true, notifications: true },
      { callLogSupported: false, folderPickSupported: false, store: "play" },
    );
    expect(states(play)).toEqual({
      callLog: "later",
      phone: "granted",
      contacts: "update",
      notifications: "granted",
      recordings: "update",
    });
    expect(permissionsMissing(permissionItems(play, ORG))).toBe(false);
  });

  it("never asks for call logging outside an organisation, where the phone refuses it", () => {
    const personal = status({ ...ALL, callLog: false });
    expect(states(personal, { organisation: false }).callLog).toBe("elsewhere");
    expect(
      permissionsMissing(permissionItems(personal, { organisation: false })),
    ).toBe(false);
  });
});

type Sent = { method: string; args: Record<string, unknown> };
type Listener = (event: { data: unknown }) => void;

let root: Root;
let host: HTMLDivElement;

function fakePhone(checks: () => Record<string, boolean>) {
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
              family: "xiaomi",
              model: "Redmi 13",
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
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
}

async function mount() {
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
        <PermissionsGate />
      </WorkspaceAccessContext.Provider>,
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
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute(PERMISSIONS_ATTRIBUTE);
});

describe("PermissionsGate", () => {
  it("covers the app until notifications are allowed, then lets it be used", async () => {
    let notifications = false;
    const sent = fakePhone(() => ({ ...ALL, notifications, contacts: false }));
    await mount();
    expect(host.querySelector("dialog[data-permissions]")).not.toBeNull();
    // Contacts are offered but not waited on: one left.
    expect(host.textContent).toContain("1 left.");
    expect(document.documentElement.hasAttribute(PERMISSIONS_ATTRIBUTE)).toBe(
      true,
    );
    await act(async () => button("Allow Contacts").click());
    await settle();
    expect(sent.map((message) => message.method)).toContain("requestContacts");
    expect(host.querySelector("dialog")).not.toBeNull();
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

  it("never waits on contacts until the owner says what they are for", async () => {
    fakePhone(() => ({ ...ALL, contacts: false }));
    await mount();
    expect(host.querySelector("dialog")).toBeNull();
  });

  it("offers Open settings after a refusal, and has no way past it", async () => {
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

  it("shows nothing in a browser", async () => {
    await mount();
    expect(host.querySelector("dialog")).toBeNull();
    expect(document.documentElement.hasAttribute(PERMISSIONS_ATTRIBUTE)).toBe(
      false,
    );
  });
});
