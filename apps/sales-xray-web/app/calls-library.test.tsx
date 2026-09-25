// @vitest-environment happy-dom
import { act, useEffect } from "react";
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
import {
  UploadSessionProvider,
  useUploadSession,
  type UploadSessionStore,
} from "./hooks/upload-session";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const cursor = "33333333-3333-4333-8333-333333333333";
const thirdId = "44444444-4444-4444-8444-444444444444";
const fourthId = "55555555-5555-4555-8555-555555555555";

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

function StoreCapture({
  capture,
}: {
  capture: (store: UploadSessionStore | null) => void;
}) {
  const store = useUploadSession();
  useEffect(() => capture(store), [capture, store]);
  return null;
}

function renderLibrary(
  options: {
    authenticated?: boolean;
    context?: { personId: string; sessionId: string; tenantId: string } | null;
    preview?: boolean;
    capture?: (store: UploadSessionStore | null) => void;
  } = {},
) {
  const authenticated = options.authenticated ?? true;
  const context = options.context === undefined ? null : options.context;
  return root.render(
    <UploadSessionProvider>
      {options.capture ? <StoreCapture capture={options.capture} /> : null}
      <WorkspaceAccessProvider
        value={{
          status: authenticated ? "ready" : "unauthenticated",
          authenticated,
          context,
          retry: () => {},
        }}
      >
        <CallsLibrary preview={options.preview} />
      </WorkspaceAccessProvider>
    </UploadSessionProvider>,
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
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function routeFetch(
  routes: Record<string, (init: RequestInit) => Response | Promise<Response>>,
) {
  fetchMock.mockImplementation(
    async (input: RequestInfo, init: RequestInit = {}) => {
      const key = `${init.method ?? "GET"} ${String(input)}`;
      const handler = routes[key];
      if (!handler) throw new Error(`Unexpected request ${key}`);
      return handler(init);
    },
  );
}
const ok = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
const LIST = "GET /v1/conversation/acquisition/submissions";
const labelPath = (id: string) =>
  `/v1/conversation/acquisition/submissions/${id}/label`;
const setInput = (input: HTMLInputElement, value: string) => {
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
};
const renameButton = () =>
  host.querySelector<HTMLButtonElement>('button[aria-label^="Rename call"]');
const editorInput = () =>
  host.querySelector<HTMLInputElement>("[data-call-label-editor] input")!;
const submitEditor = () =>
  act(async () =>
    host
      .querySelector<HTMLFormElement>("[data-call-label-editor]")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );

it("renames a call only after the server confirms it (C1)", async () => {
  const patches: RequestInit[] = [];
  routeFetch({
    [LIST]: () =>
      ok(
        page([
          {
            ...row(firstId, true),
            display_name: null,
            display_name_revision: 2,
          },
        ]),
      ),
    [`PATCH ${labelPath(firstId)}`]: (init) => {
      patches.push(init);
      return ok({
        display_name: "Harbolite discovery",
        display_name_revision: 3,
      });
    },
  });
  await act(async () => renderLibrary());
  await flush();
  // Unnamed: an honest date fallback, never an invented name.
  expect(host.querySelector(".calls-library-copy strong")?.textContent).toMatch(
    /^Sales call · /,
  );
  await act(async () => renameButton()!.click());
  await act(async () => setInput(editorInput(), "  Harbolite discovery  "));
  await submitEditor();
  await flush();

  expect(patches).toHaveLength(1);
  expect(new Headers(patches[0].headers).get("If-Match")).toBe(
    '"call-label-2"',
  );
  expect(JSON.parse(String(patches[0].body))).toEqual({
    display_name: "Harbolite discovery",
  });
  expect(host.querySelector("[data-call-label-editor]")).toBeNull();
  expect(host.querySelector(".calls-library-copy strong")?.textContent).toBe(
    "Harbolite discovery",
  );
});

it("keeps the draft on a conflict and saves against the refreshed revision", async () => {
  let patchCount = 0;
  const ifMatch: (string | null)[] = [];
  routeFetch({
    [LIST]: () =>
      ok(
        page([
          {
            ...row(firstId, true),
            display_name: "Old",
            display_name_revision: 1,
          },
        ]),
      ),
    [`PATCH ${labelPath(firstId)}`]: (init) => {
      patchCount += 1;
      ifMatch.push(new Headers(init.headers).get("If-Match"));
      return patchCount === 1
        ? ok({ detail: "The call name changed." }, 409)
        : ok({ display_name: "Mine", display_name_revision: 3 });
    },
    [`GET /v1/conversation/acquisition/submissions/${firstId}`]: () =>
      ok({ display_name: "Theirs", display_name_revision: 2 }),
  });
  await act(async () => renderLibrary());
  await flush();
  await act(async () => renameButton()!.click());
  await act(async () => setInput(editorInput(), "Mine"));
  await submitEditor();
  await flush();

  // Not saved: the editor stays open with the reader's text intact.
  const alert = host.querySelector("[data-call-label-editor] [role='alert']");
  expect(alert?.textContent).toContain("renamed elsewhere");
  expect(editorInput().value).toBe("Mine");
  expect(host.textContent).not.toContain("Harbolite");

  const refresh = [...host.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === "Refresh name",
  )!;
  await act(async () => refresh.click());
  await flush();
  expect(editorInput().value).toBe("Mine");
  expect(host.textContent).toContain("Current name: Theirs");

  await submitEditor();
  await flush();
  expect(ifMatch).toEqual(['"call-label-1"', '"call-label-2"']);
  expect(host.querySelector(".calls-library-copy strong")?.textContent).toBe(
    "Mine",
  );
});

it("confirms an accepted rename with a malformed response only through a GET", async () => {
  let patches = 0;
  routeFetch({
    [LIST]: () =>
      ok(
        page([
          {
            ...row(firstId, true),
            display_name: "Old",
            display_name_revision: 1,
          },
        ]),
      ),
    // Committed on the server, but the confirmation body is unusable.
    [`PATCH ${labelPath(firstId)}`]: () => {
      patches += 1;
      return ok({ display_name: "Renewal" });
    },
    [`GET /v1/conversation/acquisition/submissions/${firstId}`]: () =>
      ok({ display_name: "Renewal", display_name_revision: 2 }),
  });
  await act(async () => renderLibrary());
  await flush();
  await act(async () => renameButton()!.click());
  await act(async () => setInput(editorInput(), "Renewal"));
  await submitEditor();
  await flush();

  expect(host.textContent).toContain(
    "We couldn't confirm whether the name was saved",
  );
  // The draft is kept and nothing reads as saved from an unverified response.
  expect(editorInput().value).toBe("Renewal");
  expect(
    host.querySelector("[data-call-label-editor] [role='alert']")?.textContent,
  ).not.toContain("Current name");
  await submitEditor();
  await flush();
  expect(patches).toBe(1);

  const check = [...host.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === "Check saved name",
  )!;
  await act(async () => check.click());
  await flush();
  expect(patches).toBe(1);
  expect(host.querySelector("[data-call-label-editor]")).toBeNull();
  expect(host.querySelector(".calls-library-copy strong")?.textContent).toBe(
    "Renewal",
  );
});

it("offers no rename on an older server that supplies no labels", async () => {
  routeFetch({ [LIST]: () => ok(page([row(firstId, true)])) });
  await act(async () => renderLibrary());
  await flush();
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(renameButton()).toBeNull();
});

it("reads as one full-width Calls page with estimated lengths and per-row opening", async () => {
  const long = { ...row(firstId, true), duration_seconds: 3_598 };
  const short = { ...row(secondId, true), duration_seconds: 67 };
  // The library contract requires a positive whole-second duration.
  const held = { ...row(thirdId), state: "held", duration_seconds: 1_200 };
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(page([long, short, held])), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  await act(async () => renderLibrary());
  await flush();

  // One page heading; no stacked "Saved calls" / "Your calls" titles.
  expect([...host.querySelectorAll("h1")].map((h) => h.textContent)).toEqual([
    "Calls",
  ]);
  const calls = host.querySelector(".calls-library-app")!;
  expect(calls.querySelectorAll("h2")).toHaveLength(0);
  expect(calls.textContent).not.toMatch(/Saved calls|Your calls|PRIVATE CALL/);
  expect(host.textContent).toContain("3 saved calls");
  // The page scrolls as a document rather than inside a fixed-height box.
  expect(
    host
      .querySelector("[data-lightbox-shell]")
      ?.getAttribute("data-mobile-fit"),
  ).toBe("false");

  const items = [...host.querySelectorAll<HTMLElement>(".calls-library-item")];
  const durations = items.map((item) =>
    item.querySelector(".calls-library-duration")?.getAttribute("aria-label"),
  );
  // duration_seconds is the reserved estimate, never presented as measured.
  expect(durations).toEqual([
    "Estimated length: About 59:58",
    "Estimated length: About 01:07",
    "Estimated length: About 20:00",
  ]);
  expect(
    items[0].querySelector(".calls-library-duration-clock")?.textContent,
  ).toBe("About 59:58");
  expect(calls.textContent).not.toMatch(/measured/i);
  // Bars compare against the longest loaded estimate; very short calls stay visible.
  const widths = items.map((item) =>
    parseFloat(
      item.querySelector<HTMLElement>(".calls-library-duration-fill")?.style
        .width ?? "NaN",
    ),
  );
  expect(widths[0]).toBe(100);
  expect(widths[1]).toBe(4);
  expect(widths[2]).toBeCloseTo((1_200 / 3_598) * 100, 3);
  expect(items.map((item) => item.dataset.tone)).toEqual([
    "ready",
    "ready",
    "attention",
  ]);
  expect(items[0].textContent).toContain("Open report");

  await act(async () => items[1].click());
  expect(openSelectedCall).toHaveBeenCalledWith(`/?call=${secondId}`);
  const openingLabels = items.map((item) =>
    item.querySelector(".calls-library-open")?.textContent?.trim(),
  );
  // Only the chosen call says it is opening; the rest just wait.
  expect(openingLabels.filter((label) => label === "Opening…")).toHaveLength(1);
  expect(items[1].getAttribute("aria-busy")).toBe("true");
  expect(items.every((item) => (item as HTMLButtonElement).disabled)).toBe(
    true,
  );
});

it("starts New analysis as a fresh call without cancelling the remembered one", async () => {
  localStorage.setItem("ac.xray.submission.v1", firstId);
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(page([row(firstId, true)])), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
  await act(async () => renderLibrary());
  await flush();
  const newAnalysis =
    host.querySelector<HTMLAnchorElement>(".calls-library-new");
  // Fresh-call intent: the studio must not reopen the remembered report.
  expect(newAnalysis?.getAttribute("href")).toBe("/?new=1");
  // The saved call stays saved and listed; nothing was deleted or cancelled.
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(firstId);
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init?.method || init.method === "GET",
    ),
  ).toBe(true);
});

it("filters loaded calls by their saved status only", async () => {
  const held = { ...row(thirdId), state: "held" };
  fetchMock.mockResolvedValueOnce(
    new Response(
      JSON.stringify(page([row(firstId), row(secondId, true), held])),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  await act(async () => renderLibrary());
  await flush();
  const filters = [
    ...host.querySelectorAll<HTMLButtonElement>(
      ".calls-library-filters button",
    ),
  ];
  expect(filters.map((button) => button.textContent)).toEqual([
    "All3",
    "Report ready1",
    "In progress1",
    "Needs attention1",
  ]);
  await act(async () => filters[3].click());
  expect(filters[3].getAttribute("aria-pressed")).toBe("true");
  const visible = [
    ...host.querySelectorAll<HTMLElement>(".calls-library-item"),
  ].map((item) => item.dataset.submissionId);
  expect(visible).toEqual([thirdId]);
  await act(async () => filters[0].click());
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(3);
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
    "Calls",
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

it("refreshes the visible library after a background upload and shows its ready report", async () => {
  const capturedStore: { current: UploadSessionStore | null } = {
    current: null,
  };
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify(page([row(secondId, true), row(firstId, true)])),
        { status: 200 },
      ),
    );
  await act(async () =>
    renderLibrary({
      capture: (store) => {
        capturedStore.current = store;
      },
    }),
  );
  await flush();
  expect(host.textContent).toContain("Analysis in progress");

  const store = capturedStore.current;
  if (!store) throw new Error("upload_store_not_mounted");
  await act(async () => {
    await store.run(
      {
        intentId: "upload-intent",
        fileName: "call.wav",
        totalBytes: 4,
        reportLanguage: "en",
        homeHref: "/",
        sourceSha256: null,
      },
      new File(["call"], "call.wav", { type: "audio/wav" }),
      async () => ({ submissionId: secondId }),
    );
  });
  await flush();

  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[1][0]).toBe(
    "/v1/conversation/acquisition/submissions",
  );
  expect(
    host.querySelector(`[data-submission-id="${secondId}"]`)?.textContent,
  ).toContain("Report ready");
  expect(openSelectedCall).not.toHaveBeenCalled();
});

it("cancels stale account reads, ignores late results, and clears rows on logout", async () => {
  let resolveOld!: (response: Response) => void;
  let oldSignal: AbortSignal | undefined;
  fetchMock
    .mockImplementationOnce((_url, init) => {
      oldSignal = init?.signal as AbortSignal | undefined;
      return new Promise<Response>((resolve) => {
        resolveOld = resolve;
      });
    })
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(secondId, true)])), {
        status: 200,
      }),
    );

  await act(async () =>
    renderLibrary({
      context: {
        personId: "person-one",
        sessionId: "session-one",
        tenantId: "tenant-one",
      },
    }),
  );
  await flush();
  await act(async () =>
    renderLibrary({
      context: {
        personId: "person-two",
        sessionId: "session-two",
        tenantId: "tenant-two",
      },
    }),
  );
  await flush();
  expect(oldSignal?.aborted).toBe(true);
  expect(
    host.querySelector(`[data-submission-id="${secondId}"]`),
  ).not.toBeNull();

  await act(async () =>
    resolveOld(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    ),
  );
  await flush();
  expect(host.querySelector(`[data-submission-id="${firstId}"]`)).toBeNull();
  expect(
    host.querySelector(`[data-submission-id="${secondId}"]`),
  ).not.toBeNull();

  await act(async () => renderLibrary({ authenticated: false }));
  await flush();
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(0);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("does not start a queued old-account refresh after the identity view unmounts", async () => {
  const capturedStore: { current: UploadSessionStore | null } = {
    current: null,
  };
  let resolveOld!: (response: Response) => void;
  fetchMock
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(secondId)])), { status: 200 }),
    );
  const firstContext = {
    personId: "person-one",
    sessionId: "session-one",
    tenantId: "tenant-one",
  };
  await act(async () =>
    renderLibrary({
      context: firstContext,
      capture: (store) => {
        capturedStore.current = store;
      },
    }),
  );
  await flush();
  const store = capturedStore.current;
  if (!store) throw new Error("upload_store_not_mounted");
  await act(async () => {
    await store.run(
      {
        intentId: "old-account-upload",
        fileName: "call.wav",
        totalBytes: 4,
        reportLanguage: "en",
        homeHref: "/",
        sourceSha256: null,
      },
      new File(["call"], "call.wav", { type: "audio/wav" }),
      async () => ({ submissionId: thirdId }),
    );
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);

  await act(async () =>
    renderLibrary({
      context: {
        personId: "person-two",
        sessionId: "session-two",
        tenantId: "tenant-two",
      },
    }),
  );
  await flush();
  await act(async () =>
    resolveOld(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    ),
  );
  await flush();

  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(
    host.querySelector(`[data-submission-id="${secondId}"]`),
  ).not.toBeNull();
  expect(host.querySelector(`[data-submission-id="${thirdId}"]`)).toBeNull();
});

it("retains saved rows and reports a bounded error when a status refresh fails", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    )
    .mockRejectedValueOnce(new Error("temporary network failure"));
  await act(async () => renderLibrary());
  await flush();

  await act(async () =>
    (host.querySelector(".calls-library-refresh") as HTMLButtonElement).click(),
  );
  await flush();

  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(
    host.querySelector(
      '[data-submission-id="11111111-1111-4111-8111-111111111111"]',
    ),
  ).not.toBeNull();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Saved calls could not be loaded",
  );
});

it("refreshes processing rows when the user returns to the Calls tab", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId, true)])), { status: 200 }),
    );
  await act(async () => renderLibrary());
  await flush();
  expect(host.textContent).toContain("Analysis in progress");

  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();

  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("Report ready");
  expect(openSelectedCall).not.toHaveBeenCalled();
});

it("removes a call deleted before an explicit first-page refresh", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([])), { status: 200 }),
    );
  await act(async () => renderLibrary());
  await flush();
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);

  await act(async () =>
    (host.querySelector(".calls-library-refresh") as HTMLButtonElement).click(),
  );
  await flush();

  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(0);
  expect(host.textContent).toContain("No saved calls yet.");
});

it("keeps the loaded cursor when a status-only refresh leaves page membership unchanged", async () => {
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)], cursor)), {
        status: 200,
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId, true)], cursor)), {
        status: 200,
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(secondId, true)])), {
        status: 200,
      }),
    );
  await act(async () => renderLibrary());
  await flush();

  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).toContain("Report ready");
  await act(async () =>
    (host.querySelector(".calls-library-more") as HTMLButtonElement).click(),
  );
  await flush();

  expect(fetchMock.mock.calls[2][0]).toBe(
    `/v1/conversation/acquisition/submissions?before=${cursor}`,
  );
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(2);
});

it("finishes pagination before a queued saved-upload refresh resets the newest page", async () => {
  const capturedStore: { current: UploadSessionStore | null } = {
    current: null,
  };
  let resolveMore!: (response: Response) => void;
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)], cursor)), {
        status: 200,
      }),
    )
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolveMore = resolve;
        }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(thirdId), row(firstId)], cursor)), {
        status: 200,
      }),
    );
  await act(async () =>
    renderLibrary({
      capture: (store) => {
        capturedStore.current = store;
      },
    }),
  );
  await flush();

  await act(async () =>
    (host.querySelector(".calls-library-more") as HTMLButtonElement).click(),
  );
  await flush();
  const store = capturedStore.current;
  if (!store) throw new Error("upload_store_not_mounted");
  await act(async () => {
    await store.run(
      {
        intentId: "second-upload-intent",
        fileName: "new-call.wav",
        totalBytes: 8,
        reportLanguage: "en",
        homeHref: "/",
        sourceSha256: null,
      },
      new File(["new call"], "new-call.wav", { type: "audio/wav" }),
      async () => ({ submissionId: thirdId }),
    );
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);

  await act(async () =>
    resolveMore(
      new Response(JSON.stringify(page([row(secondId, true)])), {
        status: 200,
      }),
    ),
  );
  await flush();

  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(
    host.querySelector(`[data-submission-id="${thirdId}"]`),
  ).not.toBeNull();
  expect(
    host.querySelector(`[data-submission-id="${firstId}"]`),
  ).not.toBeNull();
  expect(host.querySelector(`[data-submission-id="${secondId}"]`)).toBeNull();
});

it("polls only while visible rows are processing, then stops at a ready report", async () => {
  vi.useFakeTimers();
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId, true)])), { status: 200 }),
    );
  await act(async () => renderLibrary());
  await flush();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("Report ready");

  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
    await Promise.resolve();
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("settles a timed-out first-page read and lets the user retry", async () => {
  vi.useFakeTimers();
  fetchMock.mockImplementation(
    (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
  );
  await act(async () => renderLibrary());
  await flush();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(12_000);
    await Promise.resolve();
  });
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Saved calls could not be loaded",
  );
  expect(
    (host.querySelector(".calls-library-state button") as HTMLButtonElement)
      .disabled,
  ).toBe(false);
});

it("settles a timed-out status refresh without hiding the existing row", async () => {
  vi.useFakeTimers();
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)])), { status: 200 }),
    )
    .mockImplementationOnce(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
  await act(async () => renderLibrary());
  await flush();

  await act(async () =>
    (host.querySelector(".calls-library-refresh") as HTMLButtonElement).click(),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(12_000);
    await Promise.resolve();
  });

  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(host.querySelector(".calls-library-refresh")).not.toBeNull();
  expect(
    (host.querySelector(".calls-library-refresh") as HTMLButtonElement)
      .disabled,
  ).toBe(false);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Saved calls could not be loaded",
  );
});

it("settles a timed-out next-page read and leaves its cursor retryable", async () => {
  vi.useFakeTimers();
  fetchMock
    .mockResolvedValueOnce(
      new Response(JSON.stringify(page([row(firstId)], cursor)), {
        status: 200,
      }),
    )
    .mockImplementationOnce(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
  await act(async () => renderLibrary());
  await flush();

  await act(async () =>
    (host.querySelector(".calls-library-more") as HTMLButtonElement).click(),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(12_000);
    await Promise.resolve();
  });

  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(1);
  expect(
    (host.querySelector(".calls-library-more") as HTMLButtonElement).disabled,
  ).toBe(false);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Saved calls could not be loaded",
  );
  expect(fetchMock.mock.calls[1][0]).toBe(
    `/v1/conversation/acquisition/submissions?before=${cursor}`,
  );
});

it("keeps the home preview hidden when there are no saved calls", async () => {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(page([])), { status: 200 }),
  );
  await act(async () => renderLibrary({ preview: true }));
  await flush();

  expect(host.querySelector(".calls-library-preview")).toBeNull();
  expect(host.querySelector("h1")).toBeNull();
});

it("keeps a home preview hidden before authentication and after a failed first read", async () => {
  await act(async () => renderLibrary({ authenticated: false, preview: true }));
  await flush();
  expect(host.querySelector(".calls-library-preview")).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();

  fetchMock.mockRejectedValueOnce(new Error("service unavailable"));
  await act(async () => renderLibrary({ preview: true }));
  await flush();
  expect(host.querySelector(".calls-library-preview")).toBeNull();
  expect(fetchMock).toHaveBeenCalledOnce();
});

it("shows at most three live rows in the home preview with a Calls link", async () => {
  fetchMock.mockResolvedValueOnce(
    new Response(
      JSON.stringify(
        page([row(firstId), row(secondId, true), row(thirdId), row(fourthId)]),
      ),
      { status: 200 },
    ),
  );
  await act(async () => renderLibrary({ preview: true }));
  await flush();

  expect(host.querySelector("h2")?.textContent).toBe("Recent calls");
  expect(host.querySelectorAll(".calls-library-item")).toHaveLength(3);
  expect(host.querySelector('a[href="/calls"]')?.textContent).toBe(
    "View all calls",
  );
  expect(host.querySelector("main")).toBeNull();
  expect(host.querySelector("h1")).toBeNull();
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
        value={{
          status: "ready",
          authenticated: true,
          context: null,
          retry: () => {},
        }}
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
