// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StandaloneStudio } from "./standalone-studio";
import { usePendingAnalysis } from "./pending-analysis";
import { useWorkspaceAccess } from "./workspace-access";

let authSelectedFile: { name: string; size: number } | null = null;
let authPending: ReturnType<typeof usePendingAnalysis> = null;
vi.mock("./account-auth", () => ({
  AccountAuth: ({
    selectedFile,
    onAuthenticated,
    onCancel,
  }: {
    selectedFile: { name: string; size: number } | null;
    onAuthenticated: () => void;
    onCancel?: (selectedFile: { name: string; size: number }) => void;
  }) => {
    authPending = usePendingAnalysis();
    authSelectedFile = selectedFile;
    return (
      <section data-testid="inline-account-auth">
        <span>{selectedFile?.name ?? "No selected file"}</span>
        <button type="button" onClick={onAuthenticated}>
          Complete sign in
        </button>
        {selectedFile && onCancel && (
          <button type="button" onClick={() => onCancel(selectedFile)}>
            Back to your call
          </button>
        )}
      </section>
    );
  },
}));
vi.mock("./profile-menu", () => ({
  PROFILE_UPDATED_EVENT: "sales-xray:profile-updated",
  ProfileMenu: () => null,
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const personId = "person-1";
const sessionId = "session-1";
const firstTenantId = "tenant-1";
const secondTenantId = "tenant-2";

function workspaceChoices(selected_tenant_id: string | null = null) {
  return {
    person_id: personId,
    session_id: sessionId,
    selected_tenant_id,
    workspaces: [
      { tenant_id: firstTenantId, name: "Synthetic Sales Academy" },
      { tenant_id: secondTenantId, name: "Second Synthetic Academy" },
    ],
  };
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

let root: Root;
let container: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function mount(openingExistingCall = false) {
  await act(async () =>
    root.render(
      <StandaloneStudio openingExistingCall={openingExistingCall}>
        <div data-testid="call-studio">Conversation studio</div>
      </StandaloneStudio>,
    ),
  );
  await flush();
}

beforeEach(() => {
  authSelectedFile = null;
  authPending = null;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

function profileRecord(complete = true) {
  return {
    name: complete ? "Synthetic Person" : null,
    email: "person@example.invalid",
    phone_number_e164: complete ? "+12025550123" : null,
    phone_verified: complete,
    profile_complete: complete,
    revision: 1,
  };
}

function noContent() {
  return new Response(null, { status: 204 });
}

function stubObjectUrls() {
  const revokeUrl = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:synthetic-auth-flow"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeUrl,
  });
  return revokeUrl;
}

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("passes through unauthenticated sessions and selected sessions without context activation", async () => {
  fetchMock.mockResolvedValueOnce(response({}, 401));
  await mount();
  expect(container.querySelector('[data-testid="call-studio"]')).not.toBeNull();
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/me/workspaces",
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
  expect(fetchMock).toHaveBeenCalledOnce();

  await act(async () => root.unmount());
  container.innerHTML = "";
  root = createRoot(container);
  fetchMock.mockClear();
  fetchMock.mockResolvedValueOnce(response(workspaceChoices(firstTenantId)));
  await mount();
  expect(container.querySelector('[data-testid="call-studio"]')).not.toBeNull();
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("does not announce a confirmed session while access is still pending", async () => {
  const pending = deferred<Response>();
  fetchMock.mockReturnValueOnce(pending.promise);
  await mount();
  expect(container.querySelector("ac-preloader")?.getAttribute("phase")).toBe(
    "session",
  );
  expect(container.textContent).not.toContain("Session found");
  expect(
    container.querySelector("ac-preloader")?.getAttribute("environment"),
  ).toBe("production");
  pending.resolve(response({}, 401));
  await flush();
  expect(container.querySelector('[data-testid="call-studio"]')).not.toBeNull();
});

it("keeps a requested saved call on a neutral access-check surface", async () => {
  const pending = deferred<Response>();
  fetchMock.mockReturnValueOnce(pending.promise);
  await mount(true);
  expect(container.textContent).toContain("Opening your saved call");
  expect(container.textContent).toContain("Checking workspace access");
  expect(container.textContent).not.toContain("Getting Sales Xray ready");
  expect(container.querySelector('[data-testid="call-studio"]')).toBeNull();
  pending.resolve(response(workspaceChoices(firstTenantId)));
  await flush();
  expect(container.querySelector('[data-testid="call-studio"]')).not.toBeNull();
});

it("never auto-selects a sole workspace and posts only a listed tenant on explicit choice", async () => {
  const choices = {
    ...workspaceChoices(),
    workspaces: [{ tenant_id: firstTenantId, name: "Only Synthetic Academy" }],
  };
  fetchMock.mockResolvedValueOnce(response(choices));
  await mount();
  expect(container.querySelector('[data-testid="call-studio"]')).toBeNull();
  const button = container.querySelector<HTMLButtonElement>(
    `button[data-tenant-id="${firstTenantId}"]`,
  );
  expect(button?.textContent).toContain("Only Synthetic Academy");
  expect(fetchMock).toHaveBeenCalledOnce();

  fetchMock.mockResolvedValueOnce(response({ tenant_id: firstTenantId }));
  await act(async () => button?.click());
  await flush();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const [path, init] = fetchMock.mock.calls[1] as [string, RequestInit];
  expect(path).toBe("/v1/context");
  expect(init.method).toBe("POST");
  expect(init.credentials).toBe("same-origin");
  expect(JSON.parse(String(init.body))).toEqual({ tenant_id: firstTenantId });
  expect(container.querySelector('[data-testid="call-studio"]')).not.toBeNull();
});

it("dismisses a late context response after unmount", async () => {
  const contextRequest = deferred<Response>();
  fetchMock.mockResolvedValueOnce(response(workspaceChoices()));
  await mount();
  fetchMock.mockReturnValueOnce(contextRequest.promise);
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        `button[data-tenant-id="${firstTenantId}"]`,
      )
      ?.click(),
  );
  expect(container.querySelector('[data-testid="call-studio"]')).toBeNull();
  await act(async () => root.unmount());
  contextRequest.resolve(response({ tenant_id: firstTenantId }));
  await flush();
  expect(container.querySelector('[data-testid="call-studio"]')).toBeNull();
  const contextInit = fetchMock.mock.calls[1]?.[1] as RequestInit;
  expect(contextInit.signal).toBeInstanceOf(AbortSignal);
  expect(contextInit.signal?.aborted).toBe(true);
});

it("keeps the studio closed after a forbidden context selection", async () => {
  fetchMock.mockResolvedValueOnce(response(workspaceChoices()));
  await mount();
  fetchMock.mockResolvedValueOnce(
    response({ detail: "sensitive denial" }, 403),
  );
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(
        `button[data-tenant-id="${secondTenantId}"]`,
      )
      ?.click(),
  );
  await flush();
  expect(container.querySelector('[data-testid="call-studio"]')).toBeNull();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be selected",
  );
  expect(container.textContent).not.toContain("sensitive denial");
  expect(
    fetchMock.mock.calls.some(([path]) =>
      String(path).startsWith("/v1/conversation"),
    ),
  ).toBe(false);
});

it("retains the same selected File through sign-in refresh and workspace choice", async () => {
  const createUrl = vi.fn(() => "blob:synthetic-selected-file");
  const revokeUrl = vi.fn();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createUrl,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeUrl,
  });
  const observed: {
    pending: ReturnType<typeof usePendingAnalysis>;
    access: ReturnType<typeof useWorkspaceAccess>;
  } = { pending: null, access: null };
  function StudioProbe() {
    const pending = usePendingAnalysis();
    const access = useWorkspaceAccess();
    useEffect(() => {
      observed.pending = pending;
      observed.access = access;
    }, [pending, access]);
    return <p data-testid="file-name">{pending?.selection?.file.name ?? "No file"}</p>;
  }
  fetchMock.mockResolvedValueOnce(response({}, 401));
  await act(async () => root.render(<StandaloneStudio><StudioProbe /></StandaloneStudio>));
  await flush();
  const file = new File([new Uint8Array([1, 2, 3])], "synthetic.wav", {
    type: "audio/wav",
  });
  const queued = new File([new Uint8Array([4, 5, 6])], "queued.wav", {
    type: "audio/wav",
  });
  await act(async () => observed.pending?.addFiles([file, queued]));
  const intentId = authPending?.selection?.intentId;
  expect(authPending?.selection?.file).toBe(file);
  expect(authPending?.stagedFiles[1]).toBe(queued);

  fetchMock.mockResolvedValueOnce(response({}, 503));
  await act(async () => observed.access?.retry());
  await flush();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Workspace access could not be checked",
  );
  expect(authPending?.selection?.file).toBe(file);
  expect(authPending?.stagedFiles[1]).toBe(queued);
  expect(revokeUrl).not.toHaveBeenCalled();

  fetchMock.mockResolvedValueOnce(response(workspaceChoices()));
  await act(async () =>
    [...container.querySelectorAll("button")]
      .find((button) => button.textContent?.includes("Try again"))
      ?.click(),
  );
  await flush();
  expect(container.querySelector('[data-testid="file-name"]')).toBeNull();
  expect(revokeUrl).not.toHaveBeenCalled();

  fetchMock.mockResolvedValueOnce(response({ tenant_id: firstTenantId }));
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(`button[data-tenant-id="${firstTenantId}"]`)
      ?.click(),
  );
  await flush();
  expect(observed.pending?.selection?.file).toBe(file);
  expect(observed.pending?.stagedFiles[1]).toBe(queued);
  expect(observed.pending?.selection?.intentId).toBe(intentId);
  expect(observed.access?.context).toEqual({
    personId,
    sessionId,
    tenantId: firstTenantId,
  });
  expect(createUrl).toHaveBeenCalledOnce();
  expect(revokeUrl).not.toHaveBeenCalled();
});

it("requires account access before analysis and carries the original File through sign-in, profile, and workspace choice", async () => {
  const revokeUrl = stubObjectUrls();
  const observed: {
    pending: ReturnType<typeof usePendingAnalysis>;
    access: ReturnType<typeof useWorkspaceAccess>;
  } = { pending: null, access: null };
  function StudioProbe() {
    const pending = usePendingAnalysis();
    const access = useWorkspaceAccess();
    useEffect(() => {
      observed.pending = pending;
      observed.access = access;
    }, [pending, access]);
    return <p data-testid="studio-probe">{pending?.selection?.file.name}</p>;
  }

  fetchMock.mockResolvedValueOnce(response({}, 401));
  await act(async () =>
    root.render(<StandaloneStudio><StudioProbe /></StandaloneStudio>),
  );
  await flush();
  const file = new File(["synthetic-audio"], "private-call.wav", {
    type: "audio/wav",
  });
  const queued = new File(["queued-audio"], "next-call.wav", {
    type: "audio/wav",
  });
  await act(async () => observed.pending?.addFiles([file, queued]));
  const intentId = authPending?.selection?.intentId;
  expect(authPending?.selection?.file).toBe(file);
  expect(container.querySelector('[data-testid="studio-probe"]')).toBeNull();
  expect(container.querySelector('[data-testid="inline-account-auth"]')).not.toBeNull();
  expect(authSelectedFile).toBe(file);
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(revokeUrl).not.toHaveBeenCalled();

  await act(async () =>
    [...container.querySelectorAll<HTMLButtonElement>('[data-testid="inline-account-auth"] button')]
      .find((button) => button.textContent === "Back to your call")
      ?.click(),
  );
  expect(container.querySelector('[data-testid="inline-account-auth"]')).toBeNull();
  expect(container.querySelector('[data-testid="studio-probe"]')).not.toBeNull();
  expect(observed.pending?.selection?.file).toBe(file);
  expect(observed.pending?.stagedFiles[1]).toBe(queued);
  expect(revokeUrl).not.toHaveBeenCalled();

  await act(async () => {
    expect(observed.access?.requestAnalysisAccess?.()).toBe(false);
  });
  expect(container.querySelector('[data-testid="inline-account-auth"]')).not.toBeNull();
  expect(authSelectedFile).toBe(file);

  const eligibility = deferred<Response>();
  fetchMock.mockResolvedValueOnce(response(workspaceChoices()));
  fetchMock.mockResolvedValueOnce(response(profileRecord()));
  fetchMock.mockReturnValueOnce(eligibility.promise);
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[data-testid="inline-account-auth"] button')
      ?.click(),
  );
  await flush();
  expect(container.querySelector("#account-profile-heading")).not.toBeNull();
  expect(container.textContent).toContain(file.name);
  expect(container.querySelector('[data-testid="studio-probe"]')).toBeNull();
  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/workspaces",
    "/v1/me/sales-xray-profile",
    "/v1/me/sales-xray-profile/write-eligibility",
  ]);

  eligibility.resolve(noContent());
  await flush();
  expect(container.querySelector(`#account-profile-heading`)).toBeNull();
  expect(container.querySelector(`[data-tenant-id="${firstTenantId}"]`)).not.toBeNull();
  fetchMock.mockResolvedValueOnce(response({ tenant_id: firstTenantId }));
  fetchMock.mockResolvedValueOnce(noContent());
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>(`button[data-tenant-id="${firstTenantId}"]`)
      ?.click(),
  );
  await flush();
  expect(observed.pending?.selection?.file).toBe(file);
  expect(observed.pending?.stagedFiles[1]).toBe(queued);
  expect(observed.pending?.selection?.intentId).toBe(intentId);
  expect(observed.access?.requestAnalysisAccess?.()).toBe(true);
  expect(revokeUrl).not.toHaveBeenCalled();
});

it("waits for canonical profile eligibility before an authenticated upload can continue", async () => {
  const revokeUrl = stubObjectUrls();
  const observed: {
    pending: ReturnType<typeof usePendingAnalysis>;
    access: ReturnType<typeof useWorkspaceAccess>;
  } = { pending: null, access: null };
  function StudioProbe() {
    const pending = usePendingAnalysis();
    const access = useWorkspaceAccess();
    useEffect(() => {
      observed.pending = pending;
      observed.access = access;
    }, [pending, access]);
    return <p data-testid="studio-probe">{pending?.selection?.file.name}</p>;
  }
  fetchMock.mockResolvedValueOnce(response(workspaceChoices(firstTenantId)));
  await act(async () =>
    root.render(<StandaloneStudio><StudioProbe /></StandaloneStudio>),
  );
  await flush();
  const file = new File(["synthetic-audio"], "account-call.wav", {
    type: "audio/wav",
  });
  fetchMock.mockResolvedValueOnce(response({}, 403));
  await act(async () => observed.pending?.selectFile(file));
  await flush();
  const intentId = observed.pending?.selection?.intentId;
  expect(fetchMock.mock.calls.filter(([path]) =>
    path === "/v1/me/sales-xray-profile/write-eligibility",
  )).toHaveLength(1);
  fetchMock.mockResolvedValueOnce(response(profileRecord()));
  fetchMock.mockResolvedValueOnce(response({}, 403));
  await act(async () => {
    expect(observed.access?.requestAnalysisAccess?.()).toBe(false);
  });
  await flush();
  expect(container.querySelector("#account-profile-heading")).not.toBeNull();
  expect(container.textContent).toContain("has not confirmed call review access");
  expect(container.querySelector('[data-testid="studio-probe"]')).toBeNull();
  expect(revokeUrl).not.toHaveBeenCalled();

  fetchMock.mockResolvedValueOnce(response(profileRecord()));
  fetchMock.mockResolvedValueOnce(noContent());
  await act(async () =>
    [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.includes("Check access again"))
      ?.click(),
  );
  await flush();
  expect(container.querySelector('[data-testid="studio-probe"]')).not.toBeNull();
  expect(observed.pending?.selection?.file).toBe(file);
  expect(observed.pending?.selection?.intentId).toBe(intentId);
  expect(observed.access?.requestAnalysisAccess?.()).toBe(true);
  expect(revokeUrl).not.toHaveBeenCalled();
  expect(
    fetchMock.mock.calls.some(([path]) =>
      String(path).startsWith("/v1/conversation"),
    ),
  ).toBe(false);
});

it("uses a settled canonical 204 preflight for the first authenticated Analyze click", async () => {
  const revokeUrl = stubObjectUrls();
  const observed: {
    pending: ReturnType<typeof usePendingAnalysis>;
    access: ReturnType<typeof useWorkspaceAccess>;
  } = { pending: null, access: null };
  function StudioProbe() {
    const pending = usePendingAnalysis();
    const access = useWorkspaceAccess();
    useEffect(() => {
      observed.pending = pending;
      observed.access = access;
    }, [pending, access]);
    return <p data-testid="studio-probe">{pending?.selection?.file.name}</p>;
  }
  fetchMock.mockResolvedValueOnce(response(workspaceChoices(firstTenantId)));
  await act(async () =>
    root.render(<StandaloneStudio><StudioProbe /></StandaloneStudio>),
  );
  await flush();
  const file = new File(["synthetic-audio"], "eligible-call.wav", {
    type: "audio/wav",
  });
  fetchMock.mockResolvedValueOnce(noContent());
  await act(async () => observed.pending?.selectFile(file));
  await flush();
  expect(observed.access?.requestAnalysisAccess?.()).toBe(true);
  expect(container.querySelector('[data-testid="studio-probe"]')).not.toBeNull();
  expect(container.querySelector("#account-profile-heading")).toBeNull();
  expect(observed.pending?.selection?.file).toBe(file);
  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-profile/write-eligibility",
  ]);
  expect(revokeUrl).not.toHaveBeenCalled();
});

it("does not reuse a 204 for another File or accept a late preflight after the profile gate opens", async () => {
  stubObjectUrls();
  const observed: {
    pending: ReturnType<typeof usePendingAnalysis>;
    access: ReturnType<typeof useWorkspaceAccess>;
  } = { pending: null, access: null };
  function StudioProbe() {
    const pending = usePendingAnalysis();
    const access = useWorkspaceAccess();
    useEffect(() => {
      observed.pending = pending;
      observed.access = access;
    }, [pending, access]);
    return <p data-testid="studio-probe">{pending?.selection?.file.name}</p>;
  }
  fetchMock.mockResolvedValueOnce(response(workspaceChoices(firstTenantId)));
  await act(async () =>
    root.render(<StandaloneStudio><StudioProbe /></StandaloneStudio>),
  );
  await flush();
  const first = new File(["one"], "first-call.wav", { type: "audio/wav" });
  const second = new File(["two"], "second-call.wav", { type: "audio/wav" });
  fetchMock.mockResolvedValueOnce(noContent());
  await act(async () => observed.pending?.selectFile(first));
  await flush();
  expect(observed.access?.requestAnalysisAccess?.()).toBe(true);

  const late = deferred<Response>();
  fetchMock.mockReturnValueOnce(late.promise);
  await act(async () => observed.pending?.selectFile(second));
  await flush();
  fetchMock.mockResolvedValueOnce(response(profileRecord()));
  fetchMock.mockResolvedValueOnce(response({}, 403));
  let allowed = true;
  await act(async () => {
    allowed = observed.access?.requestAnalysisAccess?.() ?? true;
  });
  expect(allowed).toBe(false);
  await flush();
  expect(container.querySelector("#account-profile-heading")).not.toBeNull();
  expect(container.textContent).toContain(second.name);
  late.resolve(noContent());
  await flush();
  expect(container.querySelector("#account-profile-heading")).not.toBeNull();
  expect(container.querySelector('[data-testid="studio-probe"]')).toBeNull();
  expect(fetchMock.mock.calls.filter(([path]) =>
    path === "/v1/me/sales-xray-profile/write-eligibility",
  )).toHaveLength(3);
});
