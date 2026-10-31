// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const route = vi.hoisted(() => ({ path: "/leads" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.path }));

import { resetBackCloseForTests } from "../ui/back-close";
import { WorkspaceAccessContext } from "../workspace-access";
import type { CaptureSetup } from "./capture-setup-client";
import { CaptureSetupFlow } from "./capture-setup-flow";
import { CaptureSetupGate } from "./capture-setup-gate";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 30 Oct 2026: "simple clicks and disclosure one by one, so that all
// our old as well as new users have to agree".

const SHA = "b".repeat(64);
const DEVICE = "install-fictional-1";
const WORDS =
  "When I record a sales call with Sales X-Ray in Fictional Homes, the customer knows the call is recorded.";

type Sent = { method: string; args: Record<string, unknown> };
type Listener = (event: { data: unknown }) => void;

const setup = (extra: Partial<CaptureSetup> = {}): CaptureSetup => ({
  schema: "sales-xray-capture-setup/1",
  workspace: "organisation",
  required: true,
  profile_complete: true,
  consent: "ask",
  declined_at: null,
  ask_again_at: null,
  phones: [],
  ...extra,
});

/** The phone app: a Redmi with everything allowed, uploads on. */
function fakePhone(overrides: Record<string, unknown> = {}) {
  const listeners: Listener[] = [];
  const sent: Sent[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as Sent & { id: string };
      sent.push({ method: message.method, args: message.args });
      const result =
        message.method === "autoCaptureStatus"
          ? { supported: true, on: true, wifiOnly: false }
          : {
              checks: {
                calls: true,
                notifications: true,
                recordings: true,
                recorder: true,
                battery: true,
                autostart: true,
              },
              family: "xiaomi",
              model: "Redmi 13",
              autostartNeeded: true,
              version: "1.0.50",
              device: DEVICE,
              folderPickSupported: true,
              folderPicked: true,
              recorderProfile: {
                kind: "folder",
                maker: "xiaomi",
                dialerLabel: "Phone",
                recording: "on",
                folders: [],
                newestMs: Date.now() - 4 * 60_000,
              },
              ...overrides,
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

type Call = { url: string; method: string; body: unknown };

/** The server: answers the steps' reads and keeps every write. */
function fakeServer(view: CaptureSetup, consent: "on" | "ask" = "ask") {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      // Like fetch: a read whose time limit already passed never reaches the server.
      if (init.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const url = String(input);
      const method = init.method ?? "GET";
      const body = init.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });
      const json = (value: unknown, status = 200) =>
        new Response(JSON.stringify(value), {
          status,
          headers: { "content-type": "application/json" },
        });
      if (url.includes("/capture-setup"))
        return method === "POST"
          ? json({
              ...view,
              consent: body?.outcome === "declined" ? "ask" : "on",
              declined_at:
                body?.outcome === "declined" ? new Date().toISOString() : null,
              phones:
                body?.outcome === "completed"
                  ? [{ ...body.phone, at: new Date().toISOString() }]
                  : [],
            })
          : json(view);
      if (url.includes("/auto-analysis"))
        return json({
          schema: "sales-xray-auto-analysis/1",
          state: method === "POST" ? "on" : consent,
          can_start: method === "POST" || consent === "on",
          notice: {
            version: "auto-analysis-2026-10-26",
            language: "en",
            title: "Analyse my calls automatically",
            text: WORDS,
            policy_sha256: SHA,
          },
        });
      if (url.includes("/upload-policy"))
        return json({
          schema: "ac.sales-xray.private-upload-consent/1",
          max_cost_paise: 0,
          policy_sha256: SHA,
          title: "Upload terms",
          description: "Fictional terms.",
          privacy_details: "Fictional privacy details.",
          maximum_file_bytes: 1_000_000,
          maximum_call_seconds: 7200,
          retention_days: 30,
        });
      if (url.includes("/v1/me/sales-xray-profile"))
        return method === "PUT"
          ? new Response(null, { status: 200 })
          : json({
              name: null,
              email: "asha@example.test",
              phone_number_e164: null,
              phone_verified: false,
              profile_complete: false,
              revision: 3,
            });
      return json({ detail: "not in this test" }, 404);
    }),
  );
  return calls;
}

let root: Root;
let host: HTMLDivElement;

async function settle() {
  for (let i = 0; i < 12; i++) {
    await act(async () => await Promise.resolve());
    // The flow's own code arrives with next/dynamic.
    await act(async () => await new Promise((done) => setTimeout(done, 0)));
  }
}

const button = (label: string) => {
  const found = [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );
  if (!found) throw new Error(`no button ${label}: ${host.textContent}`);
  return found;
};
const title = () => host.querySelector("h1")?.textContent;
const posts = (calls: Call[], part: string) =>
  calls.filter((call) => call.method !== "GET" && call.url.includes(part));

beforeEach(() => {
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
    "00000000-0000-4000-8000-0000000000aa",
  );
});

afterEach(async () => {
  vi.useRealTimers();
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetBackCloseForTests();
  document.documentElement.removeAttribute(CAPTURE_SETUP_ATTRIBUTE);
  document.documentElement.removeAttribute("data-sx-consent");
  route.path = "/leads";
});

async function flow(
  view: CaptureSetup,
  {
    inApp = true,
    required = true,
  }: { inApp?: boolean; required?: boolean } = {},
) {
  const finished = vi.fn();
  const declined = vi.fn();
  await act(async () =>
    root.render(
      <CaptureSetupFlow
        setup={view}
        phone={inApp ? { status: null } : null}
        inApp={inApp}
        required={required}
        organisation="Fictional Homes"
        onFinish={finished}
        onDeclined={declined}
        onClose={() => undefined}
      />,
    ),
  );
  await settle();
  return { finished, declined };
}

describe("CaptureSetupFlow", () => {
  it("asks name and phone first, and saves an Indian number with +91", async () => {
    const calls = fakeServer(setup({ profile_complete: false }));
    await flow(setup({ profile_complete: false }), { inApp: false });
    expect(title()).toBe("Your name and phone");
    expect(host.querySelector("ol")?.getAttribute("aria-label")).toBe(
      "Step 1 of 3",
    );
    const [name, phone] = [...host.querySelectorAll("input")];
    await act(async () => {
      for (const [input, value] of [
        [name, "Asha Fictional"],
        [phone, "98765 43210"],
      ] as const) {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )!.set!.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    await act(async () => button("Save and continue").click());
    await settle();
    expect(posts(calls, "/sales-xray-profile")[0].body).toEqual({
      full_name: "Asha Fictional",
      phone_number_e164: "+919876543210",
      expected_revision: 3,
    });
    expect(title()).toBe("What Sales X-Ray captures");
  });

  it("shows what is captured and the owner's words, with nothing ticked", async () => {
    const calls = fakeServer(setup());
    await flow(setup(), { inApp: false });
    expect(title()).toBe("What Sales X-Ray captures");
    expect(host.textContent).toContain(WORDS);
    expect(host.textContent).toContain(
      "Other calls and files stay on your phone",
    );
    expect(host.querySelectorAll("input[type=checkbox]")).toHaveLength(0);
    await act(async () => button("I agree").click());
    await settle();
    // Agreeing is the standing consent, for the words and terms shown.
    expect(posts(calls, "/auto-analysis")[0].body).toEqual({
      decision: "granted",
      policy_sha256: SHA,
      upload_policy_sha256: SHA,
      language: "en",
    });
    expect(posts(calls, "/capture-setup")).toEqual([]);
    // The web's last step: finish on the phone.
    expect(title()).toBe("Now finish on your phone");
  });

  it("records Not now as a no, asked again, and lets the seller in", async () => {
    const calls = fakeServer(setup());
    const { declined } = await flow(setup(), { inApp: false });
    await act(async () => button("Not now").click());
    await settle();
    expect(posts(calls, "/capture-setup")[0].body).toEqual({
      outcome: "declined",
    });
    expect(posts(calls, "/auto-analysis")).toEqual([]);
    expect(declined).toHaveBeenCalledOnce();
  });

  it("lets someone who agreed before go on, and records the finished phone", async () => {
    const sent = fakePhone();
    const calls = fakeServer(setup({ consent: "on" }), "on");
    const { finished } = await flow(setup({ consent: "on" }));
    expect(title()).toBe("What Sales X-Ray captures");
    expect(host.textContent).toContain("You agreed");
    await act(async () => button("Continue").click());
    await settle();
    expect(title()).toBe("You're set");
    expect(host.textContent).toContain(
      "Last call recording found 4 minutes ago.",
    );
    const done = posts(calls, "/capture-setup")[0];
    expect(done.body).toEqual({
      outcome: "completed",
      phone: {
        device: DEVICE,
        model: "Redmi 13",
        family: "xiaomi",
        app_version: "1.0.50",
        recordings: true,
        background: true,
        uploads: true,
      },
    });
    expect(JSON.stringify(done.body)).not.toMatch(/\+91|\d{10}/);
    expect(sent.some((message) => message.method === "autoCaptureSetup")).toBe(
      false,
    );
    await act(async () => button("Start working").click());
    expect(finished).toHaveBeenCalledOnce();
  });

  it("opens Android's folder picker for the recordings step", async () => {
    const sent = fakePhone({ folderPicked: false });
    fakeServer(setup({ consent: "on" }), "on");
    await flow(setup({ consent: "on" }));
    await act(async () => button("Continue").click());
    await settle();
    expect(title()).toBe("Pick your call recordings folder");
    await act(async () => button("Choose the folder").click());
    await settle();
    expect(sent.map((message) => message.method)).toContain(
      "pickRecordingsFolder",
    );
  });

  it("tells a Xiaomi phone to choose No restrictions on the battery step", async () => {
    // HyperOS opens its own Battery saver list, set to "Battery saver" (Redmi, 31 Oct 2026).
    fakePhone({
      checks: {
        calls: true,
        notifications: true,
        recordings: true,
        recorder: true,
        battery: false,
        autostart: true,
      },
    });
    fakeServer(setup({ consent: "on" }), "on");
    await flow(setup({ consent: "on" }));
    await act(async () => button("Continue").click());
    await settle();
    expect(title()).toBe("Let Sales X-Ray run in the background");
    expect(host.textContent).toContain(
      "On the next screen, choose No restrictions.",
    );
  });

  it("has no close button while required, and Skip when it isn't", async () => {
    fakeServer(setup());
    await flow(setup(), { inApp: false });
    expect(
      host.querySelector('button[aria-label="Close call capture setup"]'),
    ).toBeNull();
    expect(host.textContent).toContain("Fictional Homes");
    await act(async () => root.unmount());
    root = createRoot(host);
    await flow(setup(), { inApp: false, required: false });
    expect(
      host.querySelector('button[aria-label="Close call capture setup"]'),
    ).not.toBeNull();
    expect(button("Skip")).toBeTruthy();
  });
});

async function gate(view: CaptureSetup | Error) {
  if (view instanceof Error)
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw view;
      }),
    );
  else fakeServer(view);
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
        <CaptureSetupGate />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  await settle();
}

describe("CaptureSetupGate", () => {
  it("opens over Leads for a seller who hasn't agreed, and holds Set up this phone", async () => {
    await gate(setup());
    expect(title()).toBe("What Sales X-Ray captures");
    expect(document.documentElement.hasAttribute(CAPTURE_SETUP_ATTRIBUTE)).toBe(
      true,
    );
  });

  it("leaves Settings open", async () => {
    route.path = "/settings/privacy";
    await gate(setup());
    expect(host.querySelector("dialog")).toBeNull();
    expect(document.documentElement.hasAttribute(CAPTURE_SETUP_ATTRIBUTE)).toBe(
      false,
    );
  });

  it("waits for the Terms card first", async () => {
    document.documentElement.setAttribute("data-sx-consent", "");
    await gate(setup());
    expect(host.querySelector("dialog")).toBeNull();
    await act(async () =>
      document.documentElement.removeAttribute("data-sx-consent"),
    );
    await settle();
    expect(title()).toBe("What Sales X-Ray captures");
  });

  it("still opens when the screens before it took longer than the read's time limit", async () => {
    // Redmi, 31 Oct 2026: the permissions checklist took a minute on a fresh
    // install, and the setup never opened after it.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    document.documentElement.setAttribute("data-sx-consent", "");
    await gate(setup());
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    await act(async () =>
      document.documentElement.removeAttribute("data-sx-consent"),
    );
    await settle();
    expect(title()).toBe("What Sales X-Ray captures");
    vi.useRealTimers();
  });

  it("stays shut while a no stands, and never locks anyone out on a failed read", async () => {
    await gate(
      setup({
        declined_at: new Date().toISOString(),
        ask_again_at: new Date(Date.now() + 3_600_000).toISOString(),
      }),
    );
    expect(host.querySelector("dialog")).toBeNull();
    await act(async () => root.unmount());
    root = createRoot(host);
    await gate(new Error("offline"));
    expect(host.querySelector("dialog")).toBeNull();
    expect(document.documentElement.hasAttribute(CAPTURE_SETUP_ATTRIBUTE)).toBe(
      false,
    );
  });
});
