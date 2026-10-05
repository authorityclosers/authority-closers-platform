// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));
// The shell's own profile menu makes a separate read; keep it out of these counts.
vi.mock("./profile-menu", () => ({
  ProfileMenu: () => null,
  PROFILE_UPDATED_EVENT: "ac:sales-xray-profile-updated",
}));

import { AccountView } from "./account-view";
import { UploadSessionProvider } from "./hooks/upload-session";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
type Call = { path: string; init: RequestInit };
let calls: Call[];

const PROFILE = {
  name: "Asha Rao",
  email: "asha@example.invalid",
  phone_number_e164: "+919812345678",
  phone_verified: true,
  profile_complete: true,
  revision: 3,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function respond(
  handlers: Partial<Record<string, (init: RequestInit) => Response>>,
) {
  fetchMock.mockImplementation(async (input: RequestInfo, init = {}) => {
    const path = String(input).split("?")[0];
    calls.push({ path, init });
    const handler = handlers[`${init.method ?? "GET"} ${path}`];
    if (!handler) return json({}, 404);
    return handler(init);
  });
}

async function flush() {
  await act(async () => {
    for (let index = 0; index < 10; index += 1) await Promise.resolve();
  });
}

async function renderAccount(authenticated = true) {
  await act(async () =>
    root.render(
      <UploadSessionProvider>
        <WorkspaceAccessProvider
          value={{
            status: authenticated ? "ready" : "unauthenticated",
            authenticated,
            context: authenticated
              ? {
                  personId: "person-a",
                  sessionId: "session-a",
                  tenantId: "tenant-a",
                }
              : null,
            retry: () => {},
          }}
        >
          <AccountView />
        </WorkspaceAccessProvider>
      </UploadSessionProvider>,
    ),
  );
  await flush();
}

const finiteSession = () =>
  json({
    allowance: {
      allowance_seconds: 3_600,
      committed_seconds: 900,
      available_seconds: 2_700,
    },
  });

function billingReads() {
  const allowance = {
    allowance_seconds: 3_600,
    committed_seconds: 900,
    available_seconds: 2_700,
  };
  return {
    "GET /v1/me/sales-xray-profile": () => json(PROFILE),
    "GET /v1/conversation/acquisition/session": finiteSession,
    "GET /v1/me/plan": () =>
      json({
        plan: { key: "trial", name: "Trial" },
        allowance,
        longest_call_seconds: 3600,
      }),
    "GET /v1/me/usage": () =>
      json({ allowance, calls: [], earlier_seconds: 0, truncated: false }),
    "GET /v1/subscriptions": () => json({ current: null, past: [] }),
    "GET /v1/invoices": () => json({ invoices: [], next_before: null }),
  };
}

async function openBilling() {
  await renderAccount();
  await act(async () =>
    host.querySelector<HTMLButtonElement>("#account-tab-billing")!.click(),
  );
  await flush();
  return host.querySelector("#account-pane-billing")!;
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  calls = [];
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shows a confirmed empty subscription with the server plan and invoices", async () => {
  respond(billingReads());
  const pane = await openBilling();
  expect(pane.textContent).toContain("Trial");
  expect(pane.textContent).toContain("No subscription yet.");
  expect(pane.textContent).toContain("No renewal scheduled");
  expect(pane.textContent).toContain("No invoices or receipts yet.");
  expect(pane.textContent).not.toMatch(/Billing (is )?unavailable|Unavailable/);
  const cancel = [...pane.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.trim() === "Cancel renewal",
  );
  expect(cancel).toBeUndefined();
  expect(calls.every(({ init }) => (init.method ?? "GET") === "GET")).toBe(
    true,
  );
});

it("keeps billing failures distinct from an empty account and retries the live reads", async () => {
  let failed = true;
  const reads = billingReads();
  respond({
    ...reads,
    "GET /v1/me/plan": () =>
      failed ? json({}, 503) : reads["GET /v1/me/plan"](),
  });
  const pane = await openBilling();
  expect(pane.querySelector('[role="alert"]')?.textContent).toContain(
    "Billing details could not be loaded",
  );
  expect(pane.textContent).not.toContain("No subscription yet.");
  expect(pane.textContent).not.toMatch(/Billing (is )?unavailable|Unavailable/);
  const retry = [...pane.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.includes("Reload billing details"),
  )!;
  failed = false;
  await act(async () => retry.click());
  await flush();
  expect(pane.querySelector('[role="alert"]')).toBeNull();
  expect(pane.textContent).toContain("No subscription yet.");
  expect(calls.filter(({ path }) => path === "/v1/me/plan")).toHaveLength(2);
  expect(calls.every(({ init }) => (init.method ?? "GET") === "GET")).toBe(
    true,
  );
});

it("keeps loading billing distinct from an empty account", async () => {
  respond(billingReads());
  fetchMock.mockImplementation((input: RequestInfo, init = {}) => {
    const path = String(input).split("?")[0];
    calls.push({ path, init });
    if (path === "/v1/me/plan") return new Promise<Response>(() => {});
    const reads = billingReads();
    return Promise.resolve(
      reads[`GET ${path}` as keyof typeof reads]?.() ?? json({}, 404),
    );
  });
  const pane = await openBilling();
  expect(pane.querySelector('[role="status"]')?.textContent).toContain(
    "Loading billing details",
  );
  expect(pane.textContent).not.toContain("No subscription yet.");
  expect(pane.querySelector('[role="alert"]')).toBeNull();
});

it("retries failed invoice reads without changing billing state", async () => {
  let retryInvoices: ((response: Response) => void) | undefined;
  const reads = billingReads();
  respond(reads);
  fetchMock.mockImplementation((input: RequestInfo, init = {}) => {
    const path = String(input).split("?")[0];
    calls.push({ path, init });
    if (path === "/v1/invoices") {
      const attempts = calls.filter((call) => call.path === path).length;
      return attempts === 1
        ? Promise.resolve(json({}, 503))
        : new Promise<Response>((resolve) => (retryInvoices = resolve));
    }
    return Promise.resolve(
      reads[`GET ${path}` as keyof typeof reads]?.() ?? json({}, 404),
    );
  });
  const pane = await openBilling();
  expect(pane.querySelector('[role="alert"]')?.textContent).toContain(
    "Invoices and receipts could not be loaded",
  );
  expect(pane.textContent).toContain("No subscription yet.");
  expect(pane.textContent).not.toContain("No invoices or receipts yet.");
  const retry = [...pane.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.includes("Reload invoices"),
  )!;
  await act(async () => retry.click());
  await flush();
  expect(pane.querySelector('[role="alert"]')).toBeNull();
  expect(pane.textContent).toContain("Loading invoices…");
  expect(pane.textContent).not.toContain("No invoices or receipts yet.");
  await act(async () => retryInvoices!(reads["GET /v1/invoices"]()));
  await flush();
  expect(pane.textContent).toContain("No invoices or receipts yet.");
  expect(pane.textContent).not.toMatch(/unavailable/i);
  expect(calls.filter(({ path }) => path === "/v1/invoices")).toHaveLength(2);
  expect(calls.every(({ init }) => (init.method ?? "GET") === "GET")).toBe(
    true,
  );
});

it("shows the verified profile and real allowance as its own destination", async () => {
  respond({
    "GET /v1/me/sales-xray-profile": () => json(PROFILE),
    "GET /v1/conversation/acquisition/session": finiteSession,
  });
  await renderAccount();
  const page = host.querySelector("[data-account-view]")!;
  expect(page.querySelector("h1")?.textContent).toBe("Account");
  expect(
    host.querySelector('a[href="/account"][aria-current="page"]'),
  ).not.toBeNull();
  expect(page.textContent).toContain("Asha Rao");
  expect(page.textContent).toContain("asha@example.invalid");
  expect(page.textContent).toContain("Verified");
  expect(page.textContent).toContain("45 of 60 min available");
  expect(
    page.querySelector('[role="meter"]')?.getAttribute("aria-valuenow"),
  ).toBe("2700");
  expect(page.querySelector("#account-pane-general")?.textContent).toContain(
    "App language",
  );
  expect(page.querySelector("#account-pane-general")?.textContent).toContain(
    "Choose the report language when you start an analysis.",
  );
  // The profile photo read exists; photo uploads have no write contract yet.
  expect(page.querySelector('input[type="file"]')).toBeNull();
  expect(calls.every(({ init }) => (init.method ?? "GET") === "GET")).toBe(
    true,
  );
});

it.each([0, 2_700])(
  "shows Unlimited with a finite ledger balance of %i seconds",
  async (available) => {
    respond({
      "GET /v1/me/sales-xray-profile": () => json(PROFILE),
      "GET /v1/conversation/acquisition/session": () =>
        json({
          allowance: {
            allowance_seconds: 0,
            committed_seconds: 1_200,
            available_seconds: available,
            unlimited: true,
          },
        }),
    });
    await renderAccount();
    const allowance = host.querySelector("[data-allowance]")!;
    expect(allowance.getAttribute("data-allowance")).toBe("unlimited");
    expect(allowance.textContent).toContain("Unlimited");
    expect(allowance.textContent).toContain("20 min used or reserved");
    expect(allowance.textContent).not.toMatch(
      /No analysis time|Ask the AC team|available/,
    );
    expect(allowance.querySelector('[role="meter"]')).toBeNull();
    expect(allowance.textContent).not.toMatch(/%/);
  },
);

it("shows exhausted balance with 0 available minutes and empty meter", async () => {
  respond({
    "GET /v1/me/sales-xray-profile": () => json(PROFILE),
    "GET /v1/conversation/acquisition/session": () =>
      json({
        allowance: {
          allowance_seconds: 3_600,
          committed_seconds: 3_600,
          available_seconds: 0,
          unlimited: false,
        },
      }),
  });
  await renderAccount();
  const allowance = host.querySelector("[data-allowance]")!;
  expect(allowance.getAttribute("data-allowance")).toBe("finite");
  expect(allowance.textContent).toContain("0 of 60 min available");
  expect(
    allowance.querySelector('[role="meter"]')?.getAttribute("aria-valuenow"),
  ).toBe("0");
});

it("keeps the profile readable when the allowance read fails", async () => {
  respond({
    "GET /v1/me/sales-xray-profile": () => json(PROFILE),
    "GET /v1/conversation/acquisition/session": () => json({}, 503),
  });
  await renderAccount();
  expect(host.textContent).toContain("Asha Rao");
  expect(host.textContent).toContain(
    "Your analysis time is unavailable right now.",
  );
  expect(host.querySelector("[data-allowance]")).toBeNull();
});

it("saves details only after the server reread confirms them", async () => {
  let saved = PROFILE;
  respond({
    "GET /v1/me/sales-xray-profile": () => json(saved),
    "GET /v1/conversation/acquisition/session": finiteSession,
    "PUT /v1/me/sales-xray-profile": (init) => {
      const body = JSON.parse(String(init.body));
      saved = {
        ...PROFILE,
        name: body.full_name,
        phone_number_e164: body.phone_number_e164,
        phone_verified: false,
        revision: 4,
      };
      return new Response(null, { status: 204 });
    },
  });
  await renderAccount();
  const edit = [...host.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === "Edit details",
  )!;
  await act(async () => edit.click());
  const [nameInput, phoneInput] = [
    ...host.querySelectorAll<HTMLInputElement>("form input"),
  ];
  const setValue = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  await act(async () => setValue(nameInput, "Asha R. Rao"));
  await act(async () => setValue(phoneInput, "98765 43210"));
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await flush();
  const put = calls.find(({ init }) => init.method === "PUT")!;
  expect(JSON.parse(String(put.init.body))).toEqual({
    full_name: "Asha R. Rao",
    phone_number_e164: "+919876543210",
    expected_revision: 3,
  });
  // The shown values are the reread server values, including verification.
  expect(host.querySelector("form")).toBeNull();
  expect(host.textContent).toContain("Asha R. Rao");
  expect(host.textContent).toContain("+919876543210");
  expect(host.textContent).toContain("Not verified");
});

it("refreshes a conflicting profile before allowing another revision-bound save", async () => {
  const latest = { ...PROFILE, name: "Asha R. Rao", revision: 4 };
  let reads = 0;
  let saved = latest;
  const writes: unknown[] = [];
  respond({
    "GET /v1/me/sales-xray-profile": () =>
      json(reads++ === 0 ? PROFILE : saved),
    "GET /v1/conversation/acquisition/session": finiteSession,
    "PUT /v1/me/sales-xray-profile": (init) => {
      const body = JSON.parse(String(init.body));
      writes.push(body);
      if (writes.length === 1) return json({}, 409);
      saved = {
        ...latest,
        name: body.full_name,
        phone_number_e164: body.phone_number_e164,
        revision: 5,
      };
      return new Response(null, { status: 204 });
    },
  });
  await renderAccount();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.trim() === "Edit details")!
      .click(),
  );
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await flush();
  expect(host.querySelector("form")).not.toBeNull();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Your details changed elsewhere",
  );
  expect(
    host.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled,
  ).toBe(true);
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.trim() === "Cancel")!
      .click(),
  );
  await flush();
  expect(host.querySelector("form")).toBeNull();
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent?.trim() === "Edit details",
    ),
  ).toBe(false);
  expect(host.textContent).toContain("Refresh it before editing again");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.trim() === "Refresh profile")!
      .click(),
  );
  await flush();
  expect(host.textContent).toContain("Asha R. Rao");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.trim() === "Edit details")!
      .click(),
  );
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await flush();
  expect(writes).toHaveLength(2);
  expect(writes[1]).toMatchObject({ expected_revision: 4 });
  expect(host.querySelector("form")).toBeNull();
  expect(
    calls.filter(
      ({ path, init }) =>
        path === "/v1/me/sales-xray-profile" &&
        (init.method ?? "GET") === "GET",
    ),
  ).toHaveLength(3);
});

it("preserves an accepted save draft and blocks resubmission until a reread", async () => {
  const saved = {
    ...PROFILE,
    name: "Asha R. Rao",
    phone_number_e164: "+919876543210",
    phone_verified: false,
    revision: 4,
  };
  let reads = 0;
  respond({
    "GET /v1/me/sales-xray-profile": () => {
      reads += 1;
      if (reads === 2) return json({}, 503);
      return json(reads === 1 ? PROFILE : saved);
    },
    "GET /v1/conversation/acquisition/session": finiteSession,
    "PUT /v1/me/sales-xray-profile": () => new Response(null, { status: 204 }),
  });
  await renderAccount();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.trim() === "Edit details")!
      .click(),
  );
  const [nameInput, phoneInput] = [
    ...host.querySelectorAll<HTMLInputElement>("form input"),
  ];
  const setValue = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  await act(async () => setValue(nameInput, "Asha R. Rao"));
  await act(async () => setValue(phoneInput, "98765 43210"));
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await flush();
  expect(host.querySelector("form")).not.toBeNull();
  expect(host.textContent).toContain("Your update was accepted");
  expect(
    host.querySelector<HTMLInputElement>('input[autocomplete="name"]')?.value,
  ).toBe("Asha R. Rao");
  const saveButton = host.querySelector<HTMLButtonElement>(
    'button[type="submit"]',
  )!;
  expect(saveButton.disabled).toBe(true);
  await act(async () => saveButton.click());
  expect(calls.filter(({ init }) => init.method === "PUT")).toHaveLength(1);

  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.trim() === "Load latest profile")!
      .click(),
  );
  await flush();
  expect(host.querySelector("form")).toBeNull();
  expect(host.textContent).toContain("Asha R. Rao");
  expect(host.textContent).toContain("Not verified");
  expect(calls.filter(({ init }) => init.method === "PUT")).toHaveLength(1);
});

it("asks a signed-out visitor to sign in and reads nothing", async () => {
  respond({});
  await renderAccount(false);
  expect(host.textContent).toContain("Sign in to see your account");
  expect(host.querySelector('a[href="/login"]')).not.toBeNull();
  expect(calls).toHaveLength(0);
});

it("shows the grant empty state only for a finite zero allowance", async () => {
  respond({
    "GET /v1/me/sales-xray-profile": () => json(PROFILE),
    "GET /v1/conversation/acquisition/session": () =>
      json({
        allowance: {
          allowance_seconds: 0,
          committed_seconds: 0,
          available_seconds: 0,
          unlimited: false,
        },
      }),
  });
  await renderAccount();
  const allowance = host.querySelector('[data-allowance="none"]')!;
  expect(allowance.textContent).toContain("No analysis time yet");
  expect(allowance.textContent).toContain("Ask the AC team");
});
