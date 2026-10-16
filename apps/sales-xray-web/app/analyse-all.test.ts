import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  notAnalysedCalls,
  prepareAnalyseAll,
  rupees,
  runAnalyseAll,
  type CallRun,
} from "./analyse-all";
import { parseProcessingPlan } from "./processing-plan-contract";
import { plan, progress, recordingId } from "../tests/acquisition-fixture";

const A = "/v1/conversation/acquisition";
const one = "11111111-1111-4111-8111-111111111111";
const two = "22222222-2222-4222-8222-222222222222";
const three = "33333333-3333-4333-8333-333333333333";
const BUDGET = {
  detail: "The provider budget cannot cover this complete plan.",
};
// Through the real contract, so each fixture is a plan the page would accept.
const quoted = (id: string) =>
  parseProcessingPlan(
    {
      ...plan,
      id: id.replace(/^1/, "9"),
      max_cost_paise: 2_150,
      cost_label: "Up to ₹21.50 · approved budget",
      expires_at_epoch: Math.floor(Date.now() / 1000) + 3_600,
    },
    recordingId,
  );
const accepted = (id: string) => ({
  ...quoted(id),
  accepted: true,
  state: "active" as const,
});
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });

let calls: Array<{ path: string; init: RequestInit }>;
let routes: (path: string, init: RequestInit) => Response | null;

beforeEach(() => {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      const answer = routes(path, init);
      if (!answer) throw new Error(`Unexpected request ${path}`);
      return answer;
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const posts = (suffix: string) =>
  calls.filter(
    ({ path, init }) => path.endsWith(suffix) && init.method === "POST",
  );
const pacing = { pollMs: 1, maxWaitMs: 50 };

describe("Analyse all not-analysed calls", () => {
  it("collects only the viewer's never-analysed calls across every page", async () => {
    routes = (path) =>
      path.endsWith("order=reports_first")
        ? response({
            submissions: [
              { submission_id: one, state: "completed", has_report: true },
              { submission_id: two, state: "ready", has_report: false },
              {
                submission_id: three,
                state: "ready",
                has_report: false,
                owner_person_id: "someone-else",
              },
            ],
            next_cursor: two,
          })
        : path.endsWith(`before=${two}`)
          ? response({
              submissions: [
                {
                  submission_id: three.replace(/3/g, "4"),
                  state: "awaiting_upload",
                  has_report: false,
                  owner_person_id: "me",
                },
              ],
              next_cursor: null,
            })
          : null;
    expect(await notAnalysedCalls("me", new AbortController().signal)).toEqual([
      two,
      "44444444-4444-4444-8444-444444444444",
    ]);
    expect(calls[0].path).toBe(
      `${A}/submissions?include_owners=true&order=reports_first`,
    );
  });

  it("quotes each ready call once, sums the maximum and skips what can't start", async () => {
    routes = (path, init) => {
      if (path === `${A}/submissions/${one}`) return response(progress);
      if (path === `${A}/submissions/${two}`)
        return response({ ...progress, local_state: "running" });
      if (path === `${A}/submissions/${three}`)
        return response({ ...progress, has_report: true });
      if (path.endsWith("/plan") && !init.method) return response({}, 404);
      if (path.endsWith("/plan/quote")) return response(quoted(one), 201);
      return null;
    };
    const checked: number[] = [];
    const prepared = await prepareAnalyseAll(
      [one, two, three],
      new AbortController().signal,
      (n) => checked.push(n),
    );
    expect(prepared.planned.map((item) => item.id)).toEqual([one]);
    expect(prepared.skipped).toEqual([
      { id: two, reason: "checks" },
      { id: three, reason: "started" },
    ]);
    expect(prepared.maxCostPaise).toBe(2_150);
    expect(prepared.budgetStopped).toBe(false);
    expect(checked).toEqual([1, 2, 3]);
    // A quote spends nothing: no plan was accepted while preparing.
    expect(posts("/plan")).toHaveLength(0);
    expect(posts("/plan/quote")[0].init.headers).toMatchObject({
      "Idempotency-Key": `analyse-all-plan:${one}`,
    });
    expect(rupees(prepared.maxCostPaise)).toBe("₹22");
  });

  it("stops preparing when the budget refuses a quote", async () => {
    routes = (path, init) => {
      if (
        path.endsWith(`/submissions/${one}`) ||
        path.endsWith(`/submissions/${two}`)
      )
        return response(progress);
      if (path.endsWith("/plan") && !init.method) return response({}, 404);
      if (path.endsWith("/plan/quote"))
        return path.includes(one)
          ? response(quoted(one), 201)
          : response(BUDGET, 409);
      return null;
    };
    const prepared = await prepareAnalyseAll(
      [one, two, three],
      new AbortController().signal,
    );
    expect(prepared.planned.map((item) => item.id)).toEqual([one]);
    expect(prepared.budgetStopped).toBe(true);
    expect(calls.some(({ path }) => path.includes(three))).toBe(false);
  });

  it("starts one call at a time, waits for its report and never accepts twice", async () => {
    const reports = new Set<string>();
    routes = (path, init) => {
      const id = [one, two].find((item) => path.includes(item));
      if (!id) return null;
      if (path.endsWith("/plan") && init.method === "POST") {
        reports.add(id);
        return response(accepted(id), 202);
      }
      if (path.endsWith(`/submissions/${id}`))
        return response({ ...progress, has_report: reports.has(id) });
      return null;
    };
    const runs: Array<[string, CallRun]> = [];
    const result = await runAnalyseAll(
      [one, two].map((id) => ({ id, recordingId, plan: quoted(id) })),
      new AbortController().signal,
      (id, run) => runs.push([id, run]),
      pacing,
    );
    expect(result).toEqual({ started: 2, done: 2, failed: 0, stoppedBy: null });
    expect(
      posts("/plan").map(
        ({ init }) =>
          (init.headers as Record<string, string>)["Idempotency-Key"],
      ),
    ).toEqual([
      `accept-plan:${quoted(one).id}`,
      `accept-plan:${quoted(two).id}`,
    ]);
    // The second call starts only after the first one's report is ready.
    expect(runs).toEqual([
      [one, "starting"],
      [one, "analysing"],
      [one, "done"],
      [two, "starting"],
      [two, "analysing"],
      [two, "done"],
    ]);
  });

  it("stops cleanly when the budget can't cover the next call", async () => {
    routes = (path, init) => {
      if (path.endsWith("/plan") && init.method === "POST")
        return path.includes(one)
          ? response(accepted(one), 202)
          : response(BUDGET, 409);
      if (path.endsWith(`/submissions/${one}`))
        return response({ ...progress, has_report: true });
      return null;
    };
    const runs: Array<[string, CallRun]> = [];
    const result = await runAnalyseAll(
      [one, two, three].map((id) => ({ id, recordingId, plan: quoted(id) })),
      new AbortController().signal,
      (id, run) => runs.push([id, run]),
      pacing,
    );
    expect(result).toEqual({
      started: 1,
      done: 1,
      failed: 0,
      stoppedBy: "budget",
    });
    expect(runs.slice(-2)).toEqual([
      [two, "not_started"],
      [three, "not_started"],
    ]);
    expect(posts("/plan")).toHaveLength(2);
  });

  it("reconciles an uncertain accept with one read and never sends it again", async () => {
    routes = (path, init) => {
      if (path.endsWith("/plan") && init.method === "POST")
        return response({}, 502);
      if (path.endsWith("/plan")) return response(accepted(one));
      if (path.endsWith(`/submissions/${one}`))
        return response({ ...progress, has_report: true });
      return null;
    };
    const result = await runAnalyseAll(
      [{ id: one, recordingId, plan: quoted(one) }],
      new AbortController().signal,
      () => {},
      pacing,
    );
    expect(result.started).toBe(1);
    expect(posts("/plan")).toHaveLength(1);
  });

  it("stops after the current call when the person stops it", async () => {
    const controller = new AbortController();
    routes = (path, init) => {
      if (path.endsWith("/plan") && init.method === "POST") {
        controller.abort();
        return response(accepted(one), 202);
      }
      return response({ ...progress, has_report: false });
    };
    const result = await runAnalyseAll(
      [one, two].map((id) => ({ id, recordingId, plan: quoted(id) })),
      controller.signal,
      () => {},
      pacing,
    );
    expect(result.stoppedBy).toBe("cancelled");
    expect(posts("/plan")).toHaveLength(1);
  });
});
