import { afterEach, expect, it, vi } from "vitest";

import {
  cachedCallsPage,
  cachedPanel,
  forgetCalls,
  identityOf,
  insightShelf,
  rememberCallsPage,
  rememberPanel,
  warmCallsList,
} from "./calls-cache";

afterEach(() => {
  forgetCalls();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const page = (id: string) => ({
  submissions: [
    {
      id,
      createdAt: "2026-10-20T09:00:00Z",
      durationSeconds: 60,
      state: "complete",
      hasReport: true,
      label: null,
    },
  ],
  nextCursor: null,
});

// The list as the server sends it.
const WARM_ID = "0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10";
const served = {
  submissions: [
    {
      submission_id: WARM_ID,
      created_at: "2026-10-20T09:00:00Z",
      duration_seconds: 60,
      state: "complete",
      has_report: true,
    },
  ],
  next_cursor: null,
};

const one = identityOf({ personId: "p1", sessionId: "s1", tenantId: "t1" });
const other = identityOf({ personId: "p1", sessionId: "s1", tenantId: "t2" });

it("keeps each identity's list, panels and insights apart", () => {
  rememberCallsPage(one, page("a"));
  rememberPanel(one, "summary", { status: "ready", value: 3 });
  insightShelf<string>(one).set("a", "read");
  expect(cachedCallsPage(one)?.submissions[0].id).toBe("a");
  expect(cachedPanel(one, "summary")).toEqual({ status: "ready", value: 3 });
  expect(insightShelf<string>(one).get("a")).toBe("read");
  // Another workspace sees nothing of it.
  expect(cachedCallsPage(other)).toBeNull();
  expect(cachedPanel(other, "summary")).toBeUndefined();
  expect(insightShelf<string>(other).has("a")).toBe(false);
});

it("keeps nothing without a signed-in identity", () => {
  rememberCallsPage(null, page("a"));
  rememberCallsPage("authenticated-context-pending", page("a"));
  expect(cachedCallsPage(null)).toBeNull();
  expect(cachedCallsPage("authenticated-context-pending")).toBeNull();
  insightShelf<string>(null).set("a", "read");
  expect(insightShelf<string>(null).size).toBe(0);
});

it("keeps only the four most recent identities", () => {
  const ids = [1, 2, 3, 4, 5].map((n) =>
    identityOf({ personId: "p", sessionId: "s", tenantId: `t${n}` }),
  );
  for (const id of ids) rememberCallsPage(id, page(String(id)));
  expect(cachedCallsPage(ids[0])).toBeNull();
  expect(cachedCallsPage(ids[4])).not.toBeNull();
});

it("warms the list once, quietly, and never over a list already read", async () => {
  // Shared reads are off under test unless asked for.
  vi.stubEnv("NODE_ENV", "production");
  const fetcher = vi.fn().mockResolvedValue(Response.json(served));
  vi.stubGlobal("fetch", fetcher);
  await Promise.all([warmCallsList(one), warmCallsList(one)]);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(String(fetcher.mock.calls[0][0])).toContain(
    "/submissions?include_owners=true&order=reports_first&include_summary=true",
  );
  expect(cachedCallsPage(one)?.submissions[0].id).toBe(WARM_ID);
  await warmCallsList(one);
  expect(fetcher).toHaveBeenCalledOnce();
  // A failed warm-up changes nothing.
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await expect(warmCallsList(other)).resolves.toBeUndefined();
  expect(cachedCallsPage(other)).toBeNull();
});
