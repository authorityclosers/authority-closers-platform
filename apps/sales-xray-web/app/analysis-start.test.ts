import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  NATIVE_CHECK_DEADLINE_MS,
  reportPlanKey,
  startAnalysis,
} from "./analysis-start";
import { STATUS_READ_TIMEOUT_MS } from "./observe-submission";
import {
  plan,
  progress,
  recordingId,
  submissionId,
} from "../tests/acquisition-fixture";

const bound = {
  id: submissionId,
  recordingId,
  sha: progress.source_sha256 as string,
};
const request = {
  bound,
  sourceSha256: bound.sha,
  policySha256: "b".repeat(64),
  reportLanguage: "en",
  supportsLanguage: false,
  paused: false,
} as const;
const timing = { reads: 3, intervalMs: 1 };
const acceptedPlan = { ...plan, accepted: true, state: "active" };

let calls: Array<{ path: string; init: RequestInit }>;
let progressBodies: unknown[];
let quoteBody: unknown;
let accept: () => Response | Promise<Response>;
let ownerPlan: unknown;

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
const posts = (suffix: string) =>
  calls.filter(
    ({ path, init }) => path.endsWith(suffix) && init.method === "POST",
  );

beforeEach(() => {
  calls = [];
  progressBodies = [progress];
  quoteBody = plan;
  accept = () => response(acceptedPlan, 202);
  ownerPlan = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, init });
      if (path.endsWith("/plan/quote")) return response(quoteBody, 201);
      if (path.endsWith("/plan"))
        return init.method === "POST"
          ? accept()
          : ownerPlan
            ? response(ownerPlan)
            : response({}, 404);
      if (path.endsWith(`/submissions/${submissionId}`))
        return response(
          progressBodies.length > 1
            ? progressBodies.shift()
            : progressBodies[0],
        );
      throw new Error("Unexpected test request");
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("root-owned analysis start", () => {
  it("reconciles a timed-out acceptance once without reposting", async () => {
    vi.useFakeTimers();
    ownerPlan = acceptedPlan;
    accept = () =>
      new Promise<Response>((_resolve, reject) => {
        const signal = posts("/plan")[0]!.init.signal!;
        signal.addEventListener("abort", () => reject(signal.reason), {
          once: true,
        });
      });
    const running = startAnalysis(
      request,
      new AbortController().signal,
      () => {},
      timing,
    );
    await vi.advanceTimersByTimeAsync(STATUS_READ_TIMEOUT_MS + 1);
    await expect(running).resolves.toMatchObject({ kind: "accepted" });
    expect(posts("/plan")).toHaveLength(1);
    expect(
      calls.filter(({ path, init }) => path.endsWith("/plan") && !init.method),
    ).toHaveLength(1);
  });

  it("ends stalled native checks at the total deadline with no writes", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, init: RequestInit) => {
        calls.push({ path: _path, init });
        return new Promise<Response>((_resolve, reject) => {
          init.signal!.addEventListener(
            "abort",
            () => reject(init.signal!.reason),
            { once: true },
          );
        });
      }),
    );
    const running = startAnalysis(
      request,
      new AbortController().signal,
      () => {},
    );
    await vi.advanceTimersByTimeAsync(NATIVE_CHECK_DEADLINE_MS + 1);
    await expect(running).resolves.toMatchObject({
      kind: "needs_action",
      reason: "checks_pending",
    });
    expect(calls.length).toBeLessThan(5);
    expect(calls.some(({ init }) => init.method === "POST")).toBe(false);
  });

  it("ends a stalled quote without posting acceptance", async () => {
    vi.useFakeTimers();
    const original = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init: RequestInit) => {
        if (!path.endsWith("/plan/quote")) return original(path, init);
        calls.push({ path, init });
        return new Promise<Response>((_resolve, reject) => {
          init.signal!.addEventListener(
            "abort",
            () => reject(init.signal!.reason),
            { once: true },
          );
        });
      }),
    );
    const running = startAnalysis(
      request,
      new AbortController().signal,
      () => {},
      timing,
    );
    await vi.advanceTimersByTimeAsync(STATUS_READ_TIMEOUT_MS + 1);
    await expect(running).resolves.toMatchObject({
      kind: "needs_action",
      reason: "start_failed",
    });
    expect(posts("/plan/quote")).toHaveLength(1);
    expect(posts("/plan")).toHaveLength(0);
  });

  it("waits for native file checks, then quotes and accepts once with stable keys", async () => {
    progressBodies = [
      { ...progress, local_state: null },
      { ...progress, local_state: "running" },
      progress,
    ];
    const phases: string[] = [];
    const outcome = await startAnalysis(
      request,
      new AbortController().signal,
      (phase) => phases.push(phase),
      timing,
    );

    expect(outcome).toMatchObject({ kind: "accepted" });
    expect(phases).toEqual(["checking", "starting"]);
    const reads = calls.filter(({ init }) => !init.method);
    expect(reads).toHaveLength(3);
    const firstPost = calls.findIndex(({ init }) => init.method === "POST");
    expect(firstPost).toBe(3);
    expect(posts("/plan/quote")).toHaveLength(1);
    expect(
      new Headers(posts("/plan/quote")[0]!.init.headers).get("Idempotency-Key"),
    ).toBe(reportPlanKey(bound, "en", false));
    expect(posts("/plan")).toHaveLength(1);
    expect(
      new Headers(posts("/plan")[0]!.init.headers).get("Idempotency-Key"),
    ).toBe(`accept-plan:${plan.id}`);
  });

  it("sends the click-time report language and stops when the plan does not confirm it", async () => {
    const outcome = await startAnalysis(
      { ...request, supportsLanguage: true, reportLanguage: "hi-Deva+en" },
      new AbortController().signal,
      () => {},
      timing,
    );

    expect(outcome).toMatchObject({
      kind: "needs_action",
      reason: "language_mismatch",
    });
    const quote = posts("/plan/quote")[0]!;
    expect(JSON.parse(String(quote.init.body))).toEqual({
      report_language: "hi-Deva+en",
    });
    expect(new Headers(quote.init.headers).get("Idempotency-Key")).toBe(
      `report-plan:${submissionId}:hi-Deva_en`,
    );
    expect(posts("/plan")).toHaveLength(0);
  });

  it("adopts work the server already progresses without a new acceptance", async () => {
    progressBodies = [{ ...progress, automatic_progression: true }];
    await expect(
      startAnalysis(request, new AbortController().signal, () => {}, timing),
    ).resolves.toEqual({ kind: "accepted", plan: null });
    progressBodies = [{ ...progress, has_report: true }];
    await expect(
      startAnalysis(request, new AbortController().signal, () => {}, timing),
    ).resolves.toEqual({ kind: "accepted", plan: null });
    expect(calls.some(({ init }) => init.method === "POST")).toBe(false);
  });

  it("reconciles a lost acceptance response with the owner plan and never posts it again", async () => {
    accept = () => Promise.reject(new TypeError("Failed to fetch"));
    ownerPlan = acceptedPlan;
    const outcome = await startAnalysis(
      request,
      new AbortController().signal,
      () => {},
      timing,
    );

    expect(outcome).toMatchObject({
      kind: "accepted",
      plan: { id: plan.id, accepted: true },
    });
    expect(posts("/plan")).toHaveLength(1);
    expect(
      calls.filter(({ path, init }) => path.endsWith("/plan") && !init.method),
    ).toHaveLength(1);
  });

  it("does not treat an unaccepted or different owner plan as acceptance", async () => {
    accept = () => response({}, 502);
    ownerPlan = plan;
    await expect(
      startAnalysis(request, new AbortController().signal, () => {}, timing),
    ).resolves.toMatchObject({ kind: "needs_action", reason: "start_failed" });

    ownerPlan = { ...acceptedPlan, plan_fingerprint: "c".repeat(64) };
    await expect(
      startAnalysis(request, new AbortController().signal, () => {}, timing),
    ).resolves.toMatchObject({ kind: "needs_action", reason: "start_failed" });
    expect(posts("/plan")).toHaveLength(2);
  });

  it("settles held or never-ready work to a visible action without quoting", async () => {
    progressBodies = [
      { ...progress, state: "held", local_state: "failed", failure_code: "x" },
    ];
    await expect(
      startAnalysis(request, new AbortController().signal, () => {}, timing),
    ).resolves.toMatchObject({
      kind: "needs_action",
      reason: "needs_attention",
    });

    calls = [];
    progressBodies = [{ ...progress, local_state: "running" }];
    await expect(
      startAnalysis(request, new AbortController().signal, () => {}, timing),
    ).resolves.toMatchObject({
      kind: "needs_action",
      reason: "checks_pending",
    });
    expect(calls).toHaveLength(timing.reads);
    expect(calls.some(({ init }) => init.method === "POST")).toBe(false);
  });

  it("makes no request for a source mismatch or paused analysis", async () => {
    await expect(
      startAnalysis(
        { ...request, sourceSha256: "f".repeat(64) },
        new AbortController().signal,
        () => {},
        timing,
      ),
    ).resolves.toMatchObject({ reason: "source_mismatch" });
    await expect(
      startAnalysis(
        { ...request, paused: true },
        new AbortController().signal,
        () => {},
        timing,
      ),
    ).resolves.toMatchObject({ reason: "paused" });
    expect(calls).toHaveLength(0);
  });

  it("stops polling when aborted", async () => {
    progressBodies = [{ ...progress, local_state: "running" }];
    const abort = new AbortController();
    const running = startAnalysis(request, abort.signal, () => {}, {
      reads: 5,
      intervalMs: 50,
    });
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    abort.abort();
    await expect(running).rejects.toBeDefined();
    expect(calls.some(({ init }) => init.method === "POST")).toBe(false);
  });
});
