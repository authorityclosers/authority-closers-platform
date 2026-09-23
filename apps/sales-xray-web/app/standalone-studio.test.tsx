// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StandaloneStudio } from "./standalone-studio";
import { usePendingAnalysis } from "./pending-analysis";
import { useWorkspaceAccess } from "./workspace-access";

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
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

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
  const intentId = observed.pending?.selection?.intentId;
  expect(observed.pending?.selection?.file).toBe(file);
  expect(observed.pending?.stagedFiles[1]).toBe(queued);

  fetchMock.mockResolvedValueOnce(response({}, 503));
  await act(async () => observed.access?.retry());
  await flush();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Workspace access could not be checked",
  );
  expect(observed.pending?.selection?.file).toBe(file);
  expect(observed.pending?.stagedFiles[1]).toBe(queued);
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
