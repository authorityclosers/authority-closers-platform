// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { openSelectedCall } = vi.hoisted(() => ({ openSelectedCall: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: openSelectedCall }),
}));
// The shell's profile widgets load their own account summary. Keep these
// library requests isolated from that unrelated fetch sequence.
vi.mock("./profile-menu", () => ({ ProfileMenu: () => null }));

import { AccountNavigation } from "./account-navigation";
import { CallsLibrary } from "./calls-library";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const cursor = "33333333-3333-4333-8333-333333333333";

function row(id: string, hasReport = false) {
  return {
    submission_id: id,
    created_at: "2026-09-14T06:30:00Z",
    duration_seconds: 61,
    state: hasReport ? "completed" : "processing",
    has_report: hasReport,
  };
}

const page = (submissions: unknown[], next_cursor: string | null = null) => ({
  submissions,
  next_cursor,
});

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
let navigate: ReturnType<typeof vi.spyOn>;

async function flush() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });
}

function renderLibrary() {
  return root.render(
    <WorkspaceAccessProvider
      value={{ status: "ready", authenticated: true, context: null, retry: () => {} }}
    >
      <CallsLibrary />
    </WorkspaceAccessProvider>,
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi.fn();
  openSelectedCall.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  navigate = vi.spyOn(window.location, "assign").mockImplementation(() => {});
  localStorage.clear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("loads every server listed state without auto claiming or processing", async () => {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(page([row(firstId), row(secondId, true)])), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  await act(async () => renderLibrary());
  await flush();
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(2);
  expect(host.querySelectorAll("main")).toHaveLength(1);
  expect(
    host.querySelector('a[href="/calls"][aria-current="page"]'),
  ).not.toBeNull();
  expect(host.querySelector('[aria-current="page"]')?.textContent).toContain(
    "Saved calls",
  );
  expect(host.textContent).toContain("Analysis in progress");
  expect(host.textContent).toContain("Report ready");
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(fetchMock.mock.calls[0][0]).toBe(
    "/v1/conversation/acquisition/submissions",
  );
  expect(fetchMock.mock.calls[0][1]).toEqual(
    expect.objectContaining({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
});

it("only remembers and navigates on explicit row activation, then paginates by cursor", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)], cursor)), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(secondId, true)])), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  await act(async () => renderLibrary());
  await flush();
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
  await act(async () =>
    (host.querySelector(".calls-library-more") as HTMLButtonElement).click(),
  );
  await flush();
  expect(fetchMock.mock.calls[1][0]).toBe(
    `/v1/conversation/acquisition/submissions?before=${cursor}`,
  );
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(2);
  await act(async () =>
    (
      host.querySelector(
        `[data-submission-id="${secondId}"]`,
      ) as HTMLButtonElement
    ).click(),
  );
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(secondId);
  expect(openSelectedCall).toHaveBeenCalledWith(`/?call=${secondId}`);
  expect(fetchMock.mock.calls).toHaveLength(2);
});

it("keeps pagination available when concurrent erasure empties a page", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([], cursor)), { status: 200 }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(secondId, true)])), {
        status: 200,
      }),
    );
  await act(async () => renderLibrary());
  await flush();
  expect(host.textContent).not.toContain("No saved calls yet.");
  const more = host.querySelector<HTMLButtonElement>(".calls-library-more");
  expect(more).not.toBeNull();
  await act(async () => more!.click());
  await flush();
  expect(
    host.querySelector(`[data-submission-id="${secondId}"]`),
  ).not.toBeNull();
  expect(fetchMock.mock.calls[1][0]).toBe(
    `/v1/conversation/acquisition/submissions?before=${cursor}`,
  );
});

it("fails closed when a later page repeats an earlier submission", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)], cursor)), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  await act(async () => renderLibrary());
  await flush();
  await act(async () =>
    (host.querySelector(".calls-library-more") as HTMLButtonElement).click(),
  );
  await flush();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "could not be verified",
  );
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
});

it("posts logout once while pending, preserves the selector on failure, and clears it after 204", async () => {
  localStorage.setItem("ac.xray.submission.v1", firstId);
  let resolveFailure!: (response: Response) => void;
  const failure = new Promise<Response>((resolve) => {
    resolveFailure = resolve;
  });
  fetchMock.mockReturnValueOnce(failure);
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{ status: "ready", authenticated: true, context: null, retry: () => {} }}
      >
        <AccountNavigation />
      </WorkspaceAccessProvider>,
    ),
  );
  const button = () =>
    host.querySelector<HTMLButtonElement>(".account-nav-signout")!;
  await act(async () => button().click());
  expect(button().disabled).toBe(true);
  expect(fetchMock).toHaveBeenCalledOnce();
  await act(async () => resolveFailure(new Response("", { status: 503 })));
  await flush();
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(firstId);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "couldn’t confirm",
  );
  expect(button().disabled).toBe(false);

  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
  await act(async () => button().click());
  await flush();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
  expect(navigate).toHaveBeenCalledWith("/");
});
