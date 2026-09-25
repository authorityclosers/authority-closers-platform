// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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
  // No profile-photo contract exists: no upload control is offered.
  expect(page.querySelector('input[type="file"]')).toBeNull();
  expect(calls.every(({ init }) => (init.method ?? "GET") === "GET")).toBe(
    true,
  );
});

it("shows Unlimited without inventing a percentage", async () => {
  respond({
    "GET /v1/me/sales-xray-profile": () => json(PROFILE),
    "GET /v1/conversation/acquisition/session": () =>
      json({
        allowance: {
          allowance_seconds: 0,
          committed_seconds: 1_200,
          available_seconds: 0,
          unlimited: true,
        },
      }),
  });
  await renderAccount();
  const allowance = host.querySelector("[data-allowance]")!;
  expect(allowance.getAttribute("data-allowance")).toBe("unlimited");
  expect(allowance.textContent).toContain("Unlimited");
  expect(allowance.textContent).toContain("20 min used or reserved by analyses.");
  expect(allowance.querySelector('[role="meter"]')).toBeNull();
  expect(allowance.textContent).not.toMatch(/%/);
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
  expect(host.querySelector<HTMLInputElement>('input[autocomplete="name"]')?.value).toBe(
    "Asha R. Rao",
  );
  const saveButton = host.querySelector<HTMLButtonElement>('button[type="submit"]')!;
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
