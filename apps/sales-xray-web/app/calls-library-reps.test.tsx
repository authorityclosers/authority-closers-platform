// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
// Report fetches are verified by the existing Calls/Drawer suite. Isolate the
// authorised library response and the local rep-filter state here.
vi.mock("./calls-insights", () => ({
  useCallInsights: () => ({
    insightOf: () => null,
    statusOf: () => "unavailable",
    retry: () => {},
  }),
}));

import { CallsLibrary } from "./calls-library";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ids = [1, 2, 3, 4, 5].map(
  (n) => `${n}1111111-1111-4111-8111-111111111111`,
);
const repA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const repB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const repC = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const cursor = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const LIST = "/v1/conversation/acquisition/submissions?include_owners=true";
const context = {
  personId: repA,
  sessionId: "session-one",
  tenantId: "org-one",
};

function row(
  id: string,
  owner: string | null = repA,
  name = "Fictional Rep",
  extra: Record<string, unknown> = {},
) {
  return {
    submission_id: id,
    created_at: "2026-10-04T09:00:00Z",
    duration_seconds: 90,
    display_name: `Fictional call ${id[0]}`,
    display_name_revision: 1,
    state: "processing",
    has_report: false,
    ...(owner ? { owner_person_id: owner, owner_name: name } : {}),
    ...extra,
  };
}
const page = (submissions: unknown[], next_cursor: string | null = null) => ({
  submissions,
  next_cursor,
});
const ok = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200 });

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
}
function render(
  options: {
    context?: typeof context;
    preview?: boolean;
    authenticated?: boolean;
  } = {},
) {
  const authenticated = options.authenticated ?? true;
  root.render(
    <WorkspaceAccessProvider
      value={{
        status: authenticated ? "ready" : "unauthenticated",
        authenticated,
        context: options.context ?? context,
        retry: () => {},
      }}
    >
      <CallsLibrary variant="embedded" insights preview={options.preview} />
    </WorkspaceAccessProvider>,
  );
}
async function mount(options: Parameters<typeof render>[0] = {}) {
  await act(async () => render(options));
  await flush();
}
const select = () => host.querySelector<HTMLSelectElement>("label select")!;
const visibleIds = () =>
  [...host.querySelectorAll<HTMLElement>(".calls-library-item")].map(
    (item) => item.dataset.submissionId,
  );
async function choose(value: string, target = select()) {
  await act(async () => {
    target.value = value;
    target.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function click(selector: string) {
  await act(async () =>
    host.querySelector<HTMLButtonElement>(selector)!.click(),
  );
  await flush();
}
async function search(value: string) {
  const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function status(tone: string) {
  await click(`.calls-library-filters button[data-tone="${tone}"]`);
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  push.mockReset();
  localStorage.clear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("renders rep labels, distinguishes duplicate names, and filters by UUID without a server query", async () => {
  fetchMock.mockResolvedValue(ok(page([row(ids[0]), row(ids[1], repB)])));
  await mount();
  expect(select().closest("label")?.textContent).toContain(
    "Rep (loaded calls)",
  );
  expect([...select().options].map((o) => [o.value, o.text])).toEqual([
    ["", "All reps"],
    [repA, "Fictional Rep (1)"],
    [repB, "Fictional Rep (2)"],
  ]);
  expect(
    host.querySelector(`[data-submission-id="${ids[0]}"]`)?.textContent,
  ).toContain("Rep: Fictional Rep (1)");
  await choose(repB);
  expect(visibleIds()).toEqual([ids[1]]);
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(fetchMock.mock.calls[0][0]).toBe(LIST);
  await click(`[data-submission-id="${ids[1]}"]`);
  expect(push).toHaveBeenCalledWith(`/analysis/calls/${ids[1]}`);
  expect(localStorage.getItem("ac.xray.submission.v1")).toBe(ids[1]);
});

it.each([[], [row(ids[0], null)]].map((rows) => ({ rows })))(
  "keeps empty and Personal/member payloads free of rep controls",
  async ({ rows }) => {
    fetchMock.mockResolvedValue(ok(page(rows)));
    await mount();
    expect(visibleIds()).toEqual(rows.length ? [ids[0]] : []);
    expect(host.querySelector("[role=alert]")).toBeNull();
    expect(host.textContent).not.toContain("Rep (loaded calls)");
    expect(host.textContent).not.toContain("Fictional Rep");
  },
);

it("preserves compact preview initial and refresh reads without metadata opt-in", async () => {
  fetchMock.mockResolvedValue(ok(page([row(ids[0], null)])));
  await mount({ preview: true });
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
    "/v1/conversation/acquisition/submissions",
    "/v1/conversation/acquisition/submissions",
  ]);
  expect(host.textContent).not.toContain("Rep (loaded calls)");
});

it("adds unique reps from the second page and keeps the selected UUID", async () => {
  fetchMock
    .mockResolvedValueOnce(ok(page([row(ids[0]), row(ids[1], repB)], cursor)))
    .mockResolvedValueOnce(
      ok(page([row(ids[2], repC, "f***@example.test"), row(ids[3])])),
    );
  await mount();
  await choose(repB);
  await click(".calls-library-more");
  expect(fetchMock.mock.calls[1][0]).toBe(`${LIST}&before=${cursor}`);
  expect([...select().options].map((o) => o.value)).toEqual([
    "",
    repC,
    repA,
    repB,
  ]);
  expect(select().value).toBe(repB);
  expect(visibleIds()).toEqual([ids[1]]);
  await choose(repC);
  expect(visibleIds()).toEqual([ids[2]]);
  expect(
    host.querySelector(`[data-submission-id="${ids[2]}"]`)?.textContent,
  ).toContain("f***@example.test");
});

it("intersects rep, title and status before sorting, keeping Load more for an empty local result", async () => {
  const ready = { state: "completed", has_report: true };
  fetchMock.mockResolvedValue(
    ok(
      page(
        [
          row(ids[0], repA, "Fictional A", {
            ...ready,
            display_name: "Renewal short",
            duration_seconds: 60,
          }),
          row(ids[1], repB, "Fictional B", {
            ...ready,
            display_name: "Renewal other",
            duration_seconds: 300,
          }),
          row(ids[2], repA, "Fictional A", {
            ...ready,
            display_name: "Renewal long",
            duration_seconds: 180,
          }),
          row(ids[3], repA, "Fictional A", { display_name: "Discovery" }),
        ],
        cursor,
      ),
    ),
  );
  await mount();
  await choose(repA);
  await search("renewal");
  await status("ready");
  await choose(
    "longest",
    host.querySelector<HTMLSelectElement>('[aria-label="Sort calls"]')!,
  );
  expect(visibleIds()).toEqual([ids[2], ids[0]]);
  await status("active");
  expect(visibleIds()).toEqual([]);
  expect(
    host.querySelector<HTMLButtonElement>(".calls-library-more")?.disabled,
  ).toBe(false);
  expect(host.textContent).toContain("The filter covers loaded calls only");
  await click(".calls-library-filter-empty button");
  expect(select().value).toBe("");
  expect(visibleIds()).toHaveLength(4);
});

it("retries failed initial and later reads with the same owner flag and cursor", async () => {
  fetchMock
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValueOnce(ok(page([row(ids[0])], cursor)))
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValueOnce(ok(page([row(ids[1], repB)])));
  await mount();
  await click('[role="alert"] button');
  await choose(repA);
  await click(".calls-library-more");
  expect(select().value).toBe(repA);
  await click(".calls-library-inline-error button");
  expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
    LIST,
    LIST,
    `${LIST}&before=${cursor}`,
    `${LIST}&before=${cursor}`,
  ]);
  expect(select().options).toHaveLength(3);
  expect(visibleIds()).toEqual([ids[0]]);
});

it("drops loaded rep pages on a same-membership status refresh that withdraws metadata", async () => {
  fetchMock
    .mockResolvedValueOnce(ok(page([row(ids[0])], cursor)))
    .mockResolvedValueOnce(ok(page([row(ids[1], repB)])))
    .mockResolvedValueOnce(ok(page([row(ids[0], null)], cursor)));
  await mount();
  await click(".calls-library-more");
  await choose(repB);
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(fetchMock.mock.calls[2][0]).toBe(LIST);
  expect(host.textContent).not.toContain("Rep (loaded calls)");
  expect(host.textContent).not.toContain("Fictional Rep");
  expect(visibleIds()).toEqual([ids[0]]);
  expect(host.querySelector(".calls-library-more")).not.toBeNull();
});

it.each([[], [row(ids[1], null)]].map((rows) => ({ rows })))(
  "discards stale rep scope on next-page metadata withdrawal",
  async ({ rows }) => {
    fetchMock
      .mockResolvedValueOnce(ok(page([row(ids[0])], cursor)))
      .mockResolvedValueOnce(ok(page(rows, ids[4])))
      .mockResolvedValueOnce(ok(page([row(ids[2], null)])));
    await mount();
    await choose(repA);
    await click(".calls-library-more");
    expect(host.textContent).not.toContain("Rep (loaded calls)");
    expect(host.textContent).not.toContain("Fictional Rep");
    expect(visibleIds()).toEqual(rows.length ? [ids[1]] : []);
    expect(host.querySelector(".calls-library-more")).not.toBeNull();
    await click(".calls-library-more");
    expect(fetchMock.mock.calls[2][0]).toBe(`${LIST}&before=${ids[4]}`);
    expect(visibleIds()).toContain(ids[2]);
    expect(visibleIds()).not.toContain(ids[0]);
  },
);

it.each(["personId", "sessionId", "tenantId"] as const)(
  "clears reps on %s changes and ignores delayed old-page results",
  async (key) => {
    let resolveOld!: (value: Response) => void;
    fetchMock
      .mockResolvedValueOnce(ok(page([row(ids[0]), row(ids[1], repB)], cursor)))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValueOnce(ok(page([row(ids[3], null)])));
    await mount();
    await choose(repB);
    await click(".calls-library-more");
    const oldSignal = fetchMock.mock.calls[1][1].signal as AbortSignal;
    await mount({ context: { ...context, [key]: `changed-${key}` } });
    expect(oldSignal.aborted).toBe(true);
    expect(host.textContent).not.toContain("Rep (loaded calls)");
    expect(visibleIds()).toEqual([ids[3]]);
    await act(async () =>
      resolveOld(ok(page([row(ids[2], repC, "Late Fictional Rep")]))),
    );
    await flush();
    expect(visibleIds()).toEqual([ids[3]]);
    expect(host.textContent).not.toContain("Late Fictional Rep");
  },
);

it("resets a chosen rep when switching to a different authorised organisation and on logout", async () => {
  fetchMock
    .mockResolvedValueOnce(ok(page([row(ids[0]), row(ids[1], repB)])))
    .mockResolvedValueOnce(ok(page([row(ids[2], repC, "Fictional C")])));
  await mount();
  await choose(repB);
  await mount({ context: { ...context, tenantId: "org-two" } });
  expect(select().value).toBe("");
  expect(visibleIds()).toEqual([ids[2]]);
  expect(host.textContent).not.toContain("Fictional Rep");
  await mount({ authenticated: false });
  expect(host.textContent).not.toContain("Rep (loaded calls)");
  expect(visibleIds()).toEqual([]);
});

it("preserves scope on a failed refresh, then clears it on successful withdrawal", async () => {
  fetchMock
    .mockResolvedValueOnce(ok(page([row(ids[0])], cursor)))
    .mockResolvedValueOnce(ok(page([row(ids[1], repB)])))
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValueOnce(ok(page([row(ids[0], null)])));
  await mount();
  await click(".calls-library-more");
  await choose(repB);
  await click(".calls-library-refresh");
  expect(select().value).toBe(repB);
  expect(visibleIds()).toEqual([ids[1]]);
  await click(".calls-library-refresh");
  expect(host.textContent).not.toContain("Rep (loaded calls)");
  expect(visibleIds()).toEqual([ids[0]]);
});

it("resets a selected rep when a successful refresh replaces its rows", async () => {
  fetchMock
    .mockResolvedValueOnce(ok(page([row(ids[0])])))
    .mockResolvedValueOnce(ok(page([row(ids[1], repB, "Fictional B")])));
  await mount();
  await choose(repA);
  await click(".calls-library-refresh");
  expect(select().value).toBe("");
  expect(visibleIds()).toEqual([ids[1]]);
});

it("fails closed when owner metadata is partial", async () => {
  fetchMock.mockResolvedValue(
    ok(page([row(ids[0], null, "", { owner_name: "Unverified rep" })])),
  );
  await mount();
  expect(host.textContent).toContain("Saved calls need another check");
  expect(host.textContent).not.toContain("Unverified rep");
  expect(visibleIds()).toEqual([]);
});
