// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { StandaloneStudio } from "./standalone-studio";

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

async function mount() {
  await act(async () =>
    root.render(
      <StandaloneStudio>
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

it("never auto-selects a sole workspace and posts only a listed tenant on explicit choice", async () => {
  const choices = {
    ...workspaceChoices(),
    workspaces: [{ tenant_id: firstTenantId, name: "Only Synthetic Academy" }],
  };
  fetchMock.mockResolvedValueOnce(response(choices));
  await mount();
  expect(container.querySelector('[data-testid="call-studio"]')).toBeNull();
  const button = container.querySelector<HTMLButtonElement>("button");
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
