// @vitest-environment happy-dom
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OperationsLogin } from "@ac/operations-web/login";
import * as workspaces from "@ac/operations-web/workspaces";
import * as api from "@ac/operations-web/api";
import * as localLogin from "@ac/operations-web/local-login";
import * as platform from "@ac/operations-web/platform-identity";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const person = "11111111-1111-4111-8111-111111111111";
const sessionId = "22222222-2222-4222-8222-222222222222";
const tenant = "33333333-3333-4333-8333-333333333333";
const other = "44444444-4444-4444-8444-444444444444";
const choices: workspaces.OperationsWorkspaces = {
  person_id: person,
  session_id: sessionId,
  selected_tenant_id: null,
  workspaces: [
    { tenant_id: tenant, name: "Synthetic Academy" },
    { tenant_id: other, name: "Second Academy" },
  ],
};
const admin: api.AdminSession = {
  personId: person,
  sessionId,
  tenantId: tenant,
  email: "synthetic@example.test",
  displayName: "Synthetic",
  emailVerifiedAt: "2026-09-08T00:00:00Z",
  membershipRole: "admin",
  permissions: ["admin_surface"],
  studioCapabilities: [],
};
const platformAdmin: platform.PlatformIdentity = {
  personId: person,
  sessionId,
  selectedTenantId: null,
  email: admin.email,
  displayName: admin.displayName,
  permissions: ["platform_tenants_read"],
};
let container: HTMLDivElement;
let root: Root;
let disposed: boolean;
let navigate: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  disposed = false;
  navigate = vi.spyOn(window.location, "assign").mockImplementation(() => {});
  vi.spyOn(workspaces, "loadOperationsWorkspaces").mockResolvedValue(choices);
  vi.spyOn(workspaces, "selectOperationsWorkspace").mockResolvedValue(admin);
  vi.spyOn(api, "loadAdminSession").mockResolvedValue(admin);
  vi.spyOn(platform, "loadPlatformIdentity").mockResolvedValue(null);
  vi.stubGlobal(
    "fetch",
    vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ authenticated: true })),
  );
});
afterEach(async () => {
  if (!disposed) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function mount(
  props: ComponentProps<typeof OperationsLogin> = { surface: "admin" },
) {
  await act(async () => {
    root.render(<OperationsLogin {...props} />);
  });
}
async function choose(value = tenant) {
  await act(async () => {
    const select = container.querySelector("select")!;
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => {
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

it("renders POST-only SSR forms with every credential field disabled until hydration", () => {
  const html = renderToString(<OperationsLogin surface="coach" local />);
  const host = document.createElement("div");
  host.innerHTML = html;
  expect(host.querySelector("form")?.getAttribute("method")).toBe("post");
  expect(
    [...host.querySelectorAll("input")].every((input) => input.disabled),
  ).toBe(true);
  expect(host.querySelector("button")?.disabled).toBe(true);
  expect(fetch).not.toHaveBeenCalled();
});
it("recovers OAuth-returned memberships with reads only and requires an explicit named selection", async () => {
  await mount();
  expect(container.textContent).toContain("Choose your workspace");
  expect(container.textContent).toContain("Synthetic Academy");
  expect(container.querySelector("select")?.value).toBe("");
  expect(container.querySelector('input[name="tenant_id"]')).toBeNull();
  expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
  await choose(other);
  await submit();
  expect(workspaces.selectOperationsWorkspace).toHaveBeenCalledWith(
    choices,
    other,
    "admin",
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
  expect(navigate).toHaveBeenCalledWith("/");
});

it("offers explicit Platform Admin navigation without inventing an academy assignment", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces).mockResolvedValue({
    ...choices,
    workspaces: [],
  });
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(platformAdmin);
  await mount();
  expect(navigate).not.toHaveBeenCalled();
  expect(container.querySelector("select")).toBeNull();
  expect(container.textContent).toContain("Your account has platform access");
  const platformButton = [...container.querySelectorAll("button")].find(
    (button) => button.textContent === "Open Platform Admin",
  )!;
  await act(async () => platformButton.click());
  expect(navigate).toHaveBeenCalledWith("/platform");
  expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
  expect(api.loadAdminSession).not.toHaveBeenCalled();
});

it.each([null, tenant])(
  "lets a returning platform admin choose an academy even with selected context %s",
  async (selectedTenantId) => {
    const selected = { ...choices, selected_tenant_id: selectedTenantId };
    vi.mocked(workspaces.loadOperationsWorkspaces).mockResolvedValue(selected);
    vi.mocked(platform.loadPlatformIdentity).mockResolvedValue({
      ...platformAdmin,
      selectedTenantId,
    });
    await mount();
    expect(navigate).not.toHaveBeenCalled();
    expect(container.querySelector("select")?.value).toBe("");
    expect(container.textContent).toContain("Open Platform Admin");
    expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
    expect(api.loadAdminSession).not.toHaveBeenCalled();
    await choose(other);
    await submit();
    expect(workspaces.selectOperationsWorkspace).toHaveBeenCalledWith(
      selected,
      other,
      "admin",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
  },
);

it.each([
  { personId: other },
  { sessionId: other },
  { selectedTenantId: other },
])(
  "does not combine platform and workspace reads from different scopes %j",
  async (change) => {
    vi.mocked(platform.loadPlatformIdentity).mockResolvedValue({
      ...platformAdmin,
      ...change,
    });
    await mount();
    expect(navigate).not.toHaveBeenCalled();
    expect(container.querySelector("select")).toBeNull();
    expect(container.textContent).not.toContain("Open Platform Admin");
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
  },
);

it("never consults Platform Admin admission for a Coach login", async () => {
  await mount({ surface: "coach" });
  expect(platform.loadPlatformIdentity).not.toHaveBeenCalled();
});
it("lands an explicitly selected Coach workspace on the dashboard", async () => {
  await mount({ surface: "coach" });
  await choose();
  await submit();
  expect(navigate).toHaveBeenCalledWith("/studio");
});

it("does not navigate from late platform admission after unmount", async () => {
  const late = deferred<platform.PlatformIdentity | null>();
  vi.mocked(platform.loadPlatformIdentity).mockReturnValue(late.promise);
  await mount();
  await act(async () => root.unmount());
  disposed = true;
  await act(async () =>
    late.resolve({
      personId: person,
      sessionId,
      selectedTenantId: null,
      email: admin.email,
      displayName: null,
      permissions: ["platform_access_manage"],
    }),
  );
  expect(navigate).not.toHaveBeenCalled();
});
it("keeps an anonymous401 quiet and makes Google return through the selector", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces).mockResolvedValue(null);
  await mount({ surface: "coach" });
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(container.querySelector("a")?.getAttribute("href")).toContain(
    "surface=coach&return_path=%2Flogin",
  );
  expect(
    container.querySelector('input[name="password"]')?.hasAttribute("disabled"),
  ).toBe(false);
});
it("retains the sole selected authorized fast path without a context mutation", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces).mockResolvedValue({
    ...choices,
    selected_tenant_id: tenant,
  });
  await mount();
  expect(api.loadAdminSession).toHaveBeenCalledOnce();
  expect(navigate).toHaveBeenCalledWith("/");
  expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});
it("offers selection when the selected context is inappropriate for Coach", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces).mockResolvedValue({
    ...choices,
    selected_tenant_id: tenant,
  });
  await mount({ surface: "coach" });
  expect(navigate).not.toHaveBeenCalled();
  expect(container.querySelector("select")).not.toBeNull();
});
it("finishes password authentication before reading memberships and never posts an inferred context", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces)
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce(choices);
  await mount();
  (container.querySelector('input[name="email"]') as HTMLInputElement).value =
    "synthetic@example.test";
  (
    container.querySelector('input[name="password"]') as HTMLInputElement
  ).value = "synthetic-password-not-real";
  await submit();
  expect(fetch).toHaveBeenCalledOnce();
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/v1/auth/password/login");
  expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBe("POST");
  expect(container.textContent).toContain("Choose your workspace");
  expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
  expect(container.innerHTML).not.toContain("synthetic-password-not-real");
});
it("offers both destinations after password sign-in instead of redirecting a platform admin", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces)
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce(choices);
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(platformAdmin);
  await mount();
  expect(platform.loadPlatformIdentity).not.toHaveBeenCalled();
  (container.querySelector('input[name="email"]') as HTMLInputElement).value =
    "synthetic@example.test";
  (
    container.querySelector('input[name="password"]') as HTMLInputElement
  ).value = "synthetic-password-not-real";
  await submit();
  expect(navigate).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Choose your workspace");
  expect(container.textContent).toContain("Open Platform Admin");
  expect(workspaces.selectOperationsWorkspace).not.toHaveBeenCalled();
  await choose();
  await submit();
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/");
});

it("disables platform navigation during context selection and clears it after confirmed sign-out", async () => {
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(platformAdmin);
  const request = deferred<api.AdminSession>();
  vi.mocked(workspaces.selectOperationsWorkspace).mockReturnValue(
    request.promise,
  );
  await mount();
  await choose();
  await submit();
  const buttons = [...container.querySelectorAll("button")];
  const platformButton = buttons.find(
    (button) => button.textContent === "Open Platform Admin",
  )!;
  expect(platformButton.disabled).toBe(true);
  await act(async () => platformButton.click());
  expect(navigate).not.toHaveBeenCalled();
  await act(async () => request.resolve(admin));
  navigate.mockClear();
  await act(async () =>
    buttons
      .find((button) => button.textContent === "Use another account")!
      .click(),
  );
  expect(container.textContent).not.toContain("Open Platform Admin");
  expect(container.querySelector('input[name="email"]')).not.toBeNull();
  expect(navigate).not.toHaveBeenCalled();
});
it("displays only a safe selection failure and keeps the selector available", async () => {
  vi.mocked(workspaces.selectOperationsWorkspace).mockRejectedValue(
    new Error("synthetic-sensitive-server-body"),
  );
  await mount();
  await choose();
  await submit();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be verified",
  );
  expect(container.textContent).not.toContain(
    "synthetic-sensitive-server-body",
  );
  expect(navigate).not.toHaveBeenCalled();
  expect(container.querySelector("select")?.disabled).toBe(false);
});
it("disables and deduplicates selection while an authoritative request is pending", async () => {
  const request = deferred<api.AdminSession>();
  vi.mocked(workspaces.selectOperationsWorkspace).mockReturnValue(
    request.promise,
  );
  await mount();
  await choose();
  await submit();
  await submit();
  expect(workspaces.selectOperationsWorkspace).toHaveBeenCalledOnce();
  expect(container.querySelector("select")?.disabled).toBe(true);
  await act(async () => request.resolve(admin));
  expect(navigate).toHaveBeenCalledOnce();
});
it("aborts pending reads and ignores late completion after unmount", async () => {
  const read = deferred<workspaces.OperationsWorkspaces>();
  vi.mocked(workspaces.loadOperationsWorkspaces).mockReturnValue(read.promise);
  await mount();
  const signal = vi.mocked(workspaces.loadOperationsWorkspaces).mock.calls[0][0]
    ?.signal;
  await act(async () => root.unmount());
  disposed = true;
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    read.resolve({ ...choices, selected_tenant_id: tenant }),
  );
  expect(navigate).not.toHaveBeenCalled();
  expect(api.loadAdminSession).not.toHaveBeenCalled();
});
it("aborts pending selection on a surface change and never admits its late result", async () => {
  const request = deferred<api.AdminSession>();
  vi.mocked(workspaces.selectOperationsWorkspace).mockReturnValue(
    request.promise,
  );
  await mount();
  await choose();
  await submit();
  const signal = vi.mocked(workspaces.selectOperationsWorkspace).mock
    .calls[0][3]?.signal;
  await mount({ surface: "coach" });
  expect(signal?.aborted).toBe(true);
  await act(async () => request.resolve(admin));
  expect(navigate).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Academy Studio");
});
it("shows a truthful empty workspace state with confirmed sign-out recovery", async () => {
  vi.mocked(workspaces.loadOperationsWorkspaces).mockResolvedValue({
    ...choices,
    workspaces: [],
  });
  await mount();
  expect(container.textContent).toContain("No active workspace");
  expect(container.querySelector("select")).toBeNull();
  await act(async () => container.querySelector("button")!.click());
  expect(fetch).toHaveBeenCalledWith(
    "/v1/auth/logout",
    expect.objectContaining({ method: "POST", credentials: "same-origin" }),
  );
  expect(container.querySelector('input[name="email"]')).not.toBeNull();
});
it("preserves the explicit synthetic local tenant workflow without production workspace reads", async () => {
  vi.spyOn(localLogin, "loginLocalAdmin").mockResolvedValue();
  await mount({ surface: "admin", local: true });
  for (const [name, value] of [
    ["email", "synthetic@example.test"],
    ["password", "synthetic-local-only"],
    ["tenant_id", tenant],
  ])
    (
      container.querySelector('input[name="' + name + '"]') as HTMLInputElement
    ).value = value;
  await submit();
  expect(localLogin.loginLocalAdmin).toHaveBeenCalledWith(
    "synthetic@example.test",
    "synthetic-local-only",
    tenant,
    expect.any(Function),
  );
  expect(workspaces.loadOperationsWorkspaces).not.toHaveBeenCalled();
  expect(navigate).toHaveBeenCalledWith("/");
});
