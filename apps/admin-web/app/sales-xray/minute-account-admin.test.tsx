// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAdminSession } from "../lib/admin-session";
import { MinuteAccountAdminPanel } from "./minute-account-admin";

vi.mock("../lib/admin-session", () => ({ useAdminSession: vi.fn() }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const target = {
  tenant_id: "6cfe0195-99f9-43e7-880d-abc92c5d2c70",
  person_id: "cb9c6c8e-e130-4daa-91f4-4fce8e27383f",
  display_name: "Asha Learner",
  username: "asha_learner",
  masked_email: "a***@example.test",
};
const adminSession = {
  status: "ready" as const,
  error: null,
  session: {
    tenantId: "2f9020be-fcc3-4a9f-ad46-1e7df4fc4c60",
    personId: "6ba96a48-6518-48cf-a512-0a8af1409d28",
    sessionId: "6c6b6c36-29bf-4dda-944f-305c18e60c6f",
    email: "admin@example.test",
    displayName: "Admin User",
    emailVerifiedAt: "2026-01-01T00:00:00Z",
    membershipRole: "admin" as const,
    permissions: ["platform_access_manage"],
    studioCapabilities: [],
  },
};

function account(overrides: Record<string, unknown> = {}) {
  return {
    tenant_id: target.tenant_id,
    person_id: target.person_id,
    revision: 4,
    stored_unlimited: false,
    effective_unlimited: false,
    granted_seconds: 1_200,
    committed_seconds: 300,
    available_seconds: 4_500,
    available_minutes: 75,
    shared_upload_allowance_seconds: 6_000,
    shared_upload_committed_seconds: 1_500,
    shared_upload_available_seconds: 4_500,
    grants: [],
    ...overrides,
  };
}

function jsonResponse(value: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => value,
  } as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

let host: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn>;

async function renderPanel() {
  await act(async () => {
    root.render(createElement(MinuteAccountAdminPanel));
    await Promise.resolve();
  });
}

async function remountPanel() {
  await act(async () => root.unmount());
  root = createRoot(host);
  await renderPanel();
}

function changeValue(
  element: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function button(label: string) {
  const found = [...host.querySelectorAll("button")].find(
    (element) => element.textContent?.trim() === label,
  );
  if (!found) throw new Error(`Missing button: ${label}`);
  return found;
}

async function click(label: string) {
  await act(async () => {
    button(label).click();
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  });
}

async function lookup(query = "asha_learner") {
  const input = host.querySelector<HTMLInputElement>("#minute-account-query")!;
  changeValue(input, query);
  await click("Find learner");
}

async function loadTargetAccount(fetcher = fetchMock) {
  fetcher
    .mockResolvedValueOnce(jsonResponse({ target }))
    .mockResolvedValueOnce(jsonResponse(account()));
  await lookup();
}

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(useAdminSession).mockReturnValue(adminSession);
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("grant-key-1");
  }
});

describe("minute account administration", () => {
  it("rejects UUID and phone-shaped searches locally without sending an audit lookup", async () => {
    await renderPanel();
    await lookup("6cfe0195-99f9-43e7-880d-abc92c5d2c70");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(host.textContent).toContain(
      "Partial names, phone numbers, and IDs are not searched.",
    );
  });

  it("keeps no-match and permission failures explicit without exposing response details", async () => {
    await renderPanel();
    fetchMock.mockResolvedValueOnce(jsonResponse({ target: null }));
    await lookup("missing_learner");
    expect(host.textContent).toContain(
      "No eligible learner matched that exact email or public username.",
    );

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "internal payload" }, 403),
    );
    await lookup("asha_learner");
    expect(host.textContent).toContain(
      "Your current account cannot manage platform access.",
    );
    expect(host.textContent).not.toContain("internal payload");
  });

  it("resolves one exact learner and renders the server balance and separate upload ledger", async () => {
    await renderPanel();
    await loadTargetAccount();

    expect(host.textContent).toContain("Asha Learner");
    expect(host.textContent).toContain("75");
    expect(host.textContent).toContain("25 min committed of 100 min total");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [resolvePath, resolveInit] = fetchMock.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(resolvePath).toBe(
      "/v1/admin/conversation-minute-accounts/resolve-target",
    );
    expect(resolveInit.method).toBe("POST");
    expect(JSON.parse(String(resolveInit.body))).toEqual({
      query: "asha_learner",
    });
    expect(new Headers(resolveInit.headers).get("cache-control")).toBeNull();
    expect(resolveInit.cache).toBe("no-store");
  });

  it("adds a confirmed finite grant and adopts the canonical returned balance", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "15",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved support adjustment",
    );
    const updated = account({
      revision: 5,
      granted_seconds: 2_100,
      available_seconds: 5_400,
      available_minutes: 90,
      grants: [
        {
          grant_id: "d15d82fa-3b32-4d3d-9df6-c8f8a8c8b21e",
          seconds: 900,
          authorization_ref: "ref:conversation-minute-grant/grant-2",
          granted_by: "admin-1",
          reason: "Approved support adjustment",
          created_at: "2026-09-25T10:00:00Z",
          audit_sequence: 17,
        },
      ],
    });
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        grant_id: "d15d82fa-3b32-4d3d-9df6-c8f8a8c8b21e",
        minutes: 15,
        replayed: false,
        account: updated,
      }),
    );

    await click("Grant minutes");

    expect(host.textContent).toContain(
      "Minute grant confirmed in the canonical account ledger.",
    );
    expect(host.textContent).toContain("90");
    expect(host.textContent).toContain("Approved support adjustment");
    const [path, init] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(path).toBe(
      "/v1/admin/conversation-minute-accounts/6cfe0195-99f9-43e7-880d-abc92c5d2c70/cb9c6c8e-e130-4daa-91f4-4fce8e27383f/grants",
    );
    expect(JSON.parse(String(init.body))).toEqual({
      minutes: 15,
      reason: "Approved support adjustment",
    });
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe(
      "grant-key-1",
    );
    expect(sessionStorage.length).toBe(0);
  });

  it("guards rapid duplicate submits while the first grant response is pending", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "3",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved correction",
    );
    const response = deferred<Response>();
    fetchMock.mockReturnValueOnce(response.promise);
    const submitButton = button("Grant minutes");

    await act(async () => {
      submitButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      submitButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(host.textContent).toContain("Submitting this audited minute grant…");

    response.resolve(
      jsonResponse({
        grant_id: "4b7f9793-f1cf-4cf6-a46e-32e29e26e5df",
        minutes: 3,
        replayed: false,
        account: account({
          revision: 5,
          granted_seconds: 1_380,
          available_seconds: 4_680,
          available_minutes: 78,
        }),
      }),
    );
    await act(async () => {
      await response.promise;
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(host.textContent).toContain(
      "Minute grant confirmed in the canonical account ledger.",
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not submit a grant when a secure idempotency key cannot be created", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "3",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved correction",
    );
    vi.spyOn(crypto, "randomUUID").mockImplementation(() => {
      throw new Error("secure random unavailable");
    });

    await click("Grant minutes");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(host.textContent).toContain(
      "A secure request key could not be created in this browser.",
    );
    expect(host.textContent).not.toContain("secure random unavailable");
  });

  it("retries an unknown grant with the identical body and idempotency key, accepting replay as confirmation", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "8",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved correction",
    );
    fetchMock.mockRejectedValueOnce(
      new TypeError("network detail must not render"),
    );
    await click("Grant minutes");
    expect(host.textContent).toContain("The result is not confirmed.");
    expect(host.textContent).not.toContain("network detail");
    expect(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!.disabled,
    ).toBe(true);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        grant_id: "355002e1-9102-4dd4-9e5a-9f81926677ea",
        minutes: 8,
        replayed: true,
        account: account({
          revision: 5,
          granted_seconds: 1_680,
          available_seconds: 4_980,
          available_minutes: 83,
        }),
      }),
    );
    await click("Retry same grant");

    const first = fetchMock.mock.calls[2] as [string, RequestInit];
    const second = fetchMock.mock.calls[3] as [string, RequestInit];
    expect(JSON.stringify(first[1].body)).toBe(JSON.stringify(second[1].body));
    expect(new Headers(first[1].headers).get("Idempotency-Key")).toBe(
      "grant-key-1",
    );
    expect(new Headers(second[1].headers).get("Idempotency-Key")).toBe(
      "grant-key-1",
    );
    expect(host.textContent).toContain(
      "The original grant was confirmed; no duplicate grant was added.",
    );
    expect(host.textContent).toContain("83");
  });

  it("recovers the exact grant payload and key after navigation or reload", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "8",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved correction",
    );
    fetchMock.mockRejectedValueOnce(new TypeError("connection lost"));
    await click("Grant minutes");

    const storageEntries = Object.entries(sessionStorage);
    expect(storageEntries).toHaveLength(1);
    const [storageKey, storedValue] = storageEntries[0]!;
    expect(storageKey).toContain(target.tenant_id);
    expect(storageKey).toContain(target.person_id);
    expect(storageKey).not.toContain("asha");
    const stored = JSON.parse(storedValue!) as Record<string, unknown>;
    expect(stored).toMatchObject({
      key: "grant-key-1",
      actorTenantId: adminSession.session.tenantId,
      actorPersonId: adminSession.session.personId,
      tenantId: target.tenant_id,
      personId: target.person_id,
      minutes: 8,
      reason: "Approved correction",
    });
    expect(JSON.stringify(stored)).not.toContain("email");
    expect(JSON.stringify(stored)).not.toContain("display_name");

    await remountPanel();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ target }))
      .mockResolvedValueOnce(jsonResponse(account()));
    await lookup();
    expect(host.textContent).toContain("original request was recovered");
    expect(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!.value,
    ).toBe("8");
    expect(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!.value,
    ).toBe("Approved correction");
    expect(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!.disabled,
    ).toBe(true);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        grant_id: "355002e1-9102-4dd4-9e5a-9f81926677ea",
        minutes: 8,
        replayed: true,
        account: account({ available_minutes: 83 }),
      }),
    );
    await click("Retry same grant");
    const first = fetchMock.mock.calls[2] as [string, RequestInit];
    const retry = fetchMock.mock.calls[5] as [string, RequestInit];
    expect(JSON.stringify(first[1].body)).toBe(JSON.stringify(retry[1].body));
    expect(new Headers(retry[1].headers).get("Idempotency-Key")).toBe(
      "grant-key-1",
    );
    expect(sessionStorage.length).toBe(0);
    expect(host.textContent).toContain(
      "The original grant was confirmed; no duplicate grant was added.",
    );
  });

  it("keeps the unresolved marker quarantined from a different admin identity", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "2",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Private audit reason",
    );
    fetchMock.mockRejectedValueOnce(new TypeError("connection lost"));
    await click("Grant minutes");
    const before = sessionStorage.getItem(
      `ac.admin.sales-xray.minute-grant.v1:${target.tenant_id}:${target.person_id}`,
    );
    expect(before).not.toBeNull();

    await remountPanel();
    vi.mocked(useAdminSession).mockReturnValue({
      ...adminSession,
      session: {
        ...adminSession.session,
        personId: "9d0d6f48-0ef8-41f7-a0c7-9e1632325bbc",
      },
    });
    await renderPanel();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ target }))
      .mockResolvedValueOnce(jsonResponse(account()));
    await lookup();

    expect(host.textContent).toContain(
      "unresolved under another administrator",
    );
    expect(host.textContent).not.toContain("Private audit reason");
    expect(button("Grant minutes").disabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(
      sessionStorage.getItem(
        `ac.admin.sales-xray.minute-grant.v1:${target.tenant_id}:${target.person_id}`,
      ),
    ).toBe(before);
  });

  it("does not send a grant if tab storage cannot retain the idempotent request", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "5",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved correction",
    );
    const setItemMock = vi
      .spyOn(window.sessionStorage, "setItem")
      .mockImplementation(() => {
        throw new DOMException("storage disabled", "QuotaExceededError");
      });

    await click("Grant minutes");
    setItemMock.mockRestore();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(host.textContent).toContain(
      "This browser could not safely retain the grant request. No grant was sent.",
    );
  });

  it("preserves an unknown original grant after a same-key retry is denied", async () => {
    await renderPanel();
    await loadTargetAccount();
    changeValue(
      host.querySelector<HTMLInputElement>("#minute-grant-amount")!,
      "6",
    );
    changeValue(
      host.querySelector<HTMLTextAreaElement>("#minute-grant-reason")!,
      "Approved correction",
    );
    fetchMock.mockRejectedValueOnce(new TypeError("connection lost"));
    await click("Grant minutes");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "forbidden" }, 403));
    await click("Retry same grant");

    expect(sessionStorage.length).toBe(1);
    expect(host.textContent).toContain(
      "Your current account cannot grant learner minutes.",
    );
    expect(button("Retry same grant").disabled).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(
      new Headers(
        (fetchMock.mock.calls[3] as [string, RequestInit])[1].headers,
      ).get("Idempotency-Key"),
    ).toBe("grant-key-1");
  });

  it("does not let an older lookup overwrite the newer exact account result", async () => {
    await renderPanel();
    const oldResolution = deferred<Response>();
    fetchMock.mockReturnValueOnce(oldResolution.promise);
    const input = host.querySelector<HTMLInputElement>(
      "#minute-account-query",
    )!;
    changeValue(input, "old_learner");
    await act(async () => {
      button("Find learner").click();
      await Promise.resolve();
    });

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          target: {
            ...target,
            person_id: "fe203924-2bb7-4b0d-b484-adb2ff1f9b3b",
            display_name: "New Learner",
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          account({ person_id: "fe203924-2bb7-4b0d-b484-adb2ff1f9b3b" }),
        ),
      );
    changeValue(input, "new_learner");
    await click("Find learner");
    await act(async () => {
      oldResolution.resolve(
        jsonResponse({ target: { ...target, display_name: "Old Learner" } }),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(host.textContent).toContain("New Learner");
    expect(host.textContent).not.toContain("Old Learner");
  });
});
