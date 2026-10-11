import { afterEach, expect, it, vi } from "vitest";
import {
  preloadSavedReport,
  SAVED_REPORT_READ_TIMEOUT_MS,
  type SavedReportRead,
} from "./report-preload";
import {
  envelope,
  progress,
  recordingId,
  submissionId,
  transcript,
} from "../tests/acquisition-fixture";
import {
  callCoachingBinding,
  fictionalCallCoaching,
} from "./report-call-coaching.fixture";

const completed = { ...progress, has_report: true };
const read = (objects: Record<string, unknown> = {}) =>
  vi.fn(async (path: string) => {
    const key = path.split("/").at(-1)!;
    if (Object.hasOwn(objects, key)) return objects[key];
    return key === submissionId
      ? completed
      : key === "transcript"
        ? transcript
        : envelope;
  });
afterEach(() => vi.useRealTimers());

it.each(["matches", "changed"])(
  "opens the retained Report and checks the optional Coaching report pin when it %s",
  async (kind) => {
    const payload = fictionalCallCoaching();
    const reportRevision = "b".repeat(64);
    payload.report_revision =
      kind === "matches" ? reportRevision : "c".repeat(64);
    const port: SavedReportRead = async (path) => {
      if (path.includes("/me/coaching/")) return payload;
      return read({ report: { ...envelope, report_revision: reportRevision } })(
        path,
      );
    };
    const view = await preloadSavedReport(submissionId, port, undefined, {
      coachingActor: {
        personId: callCoachingBinding.personId,
        tenantId: callCoachingBinding.tenantId,
        sessionId: callCoachingBinding.sessionId,
      },
    });
    expect(view.state).toBe("ready");
    if (view.state === "ready") {
      expect(view.result.reportRevision).toBe(reportRevision);
      if (kind === "matches")
        expect(view.result.callCoaching?.state).toBe("ready");
      else expect(view.result.callCoaching).toBeUndefined();
    }
  },
);

it("loads optional own-call coaching in parallel with C2/C5 under the route's actor", async () => {
  const pending: Array<() => void> = [];
  const payload = fictionalCallCoaching();
  const port: SavedReportRead = vi.fn(async (path) => {
    if (path.includes("/acquisition/") && path.endsWith(submissionId))
      return completed;
    return new Promise((resolve) =>
      pending.push(() =>
        resolve(
          path.includes("/me/coaching/")
            ? payload
            : path.endsWith("transcript")
              ? transcript
              : envelope,
        ),
      ),
    );
  });
  const running = preloadSavedReport(submissionId, port, undefined, {
    coachingActor: {
      personId: callCoachingBinding.personId,
      tenantId: callCoachingBinding.tenantId,
      sessionId: callCoachingBinding.sessionId,
    },
  });
  await vi.waitFor(() => expect(pending).toHaveLength(3));
  pending.forEach((complete) => complete());
  expect(await running).toMatchObject({
    state: "ready",
    result: {
      recordingId,
      callCoaching: { state: "ready", submission_id: submissionId },
    },
  });
});

it.each(["missing", "wrong person", "wrong source"])(
  "opens the retained Report when optional coaching is %s",
  async (failure) => {
    const payload = fictionalCallCoaching();
    if (failure === "wrong person") payload.person_id = recordingId;
    if (failure === "wrong source") payload.source_sha256 = "f".repeat(64);
    const port: SavedReportRead = async (path) => {
      if (path.includes("/me/coaching/")) {
        if (failure === "missing") throw new Error("Private service error");
        return payload;
      }
      return read()(path);
    };
    const view = await preloadSavedReport(submissionId, port, undefined, {
      coachingActor: {
        personId: callCoachingBinding.personId,
        tenantId: callCoachingBinding.tenantId,
        sessionId: callCoachingBinding.sessionId,
      },
    });
    expect(view.state).toBe("ready");
    if (view.state === "ready")
      expect(view.result.callCoaching).toBeUndefined();
  },
);

it("does not wait for a stalled optional Coaching service to open the Report", async () => {
  let coachingSignal: AbortSignal | undefined;
  const port: SavedReportRead = async (path, signal) => {
    if (path.includes("/me/coaching/")) {
      coachingSignal = signal;
      return new Promise(() => {});
    }
    return read()(path);
  };
  const view = await preloadSavedReport(submissionId, port, undefined, {
    coachingActor: {
      personId: callCoachingBinding.personId,
      tenantId: callCoachingBinding.tenantId,
      sessionId: callCoachingBinding.sessionId,
    },
  });
  expect(view.state).toBe("ready");
  expect(coachingSignal?.aborted).toBe(true);
  if (view.state === "ready") expect(view.result.callCoaching).toBeUndefined();
});

it("loads a finished saved call in one status read plus parallel source-verified reads", async () => {
  const pending: Array<() => void> = [];
  const calls: string[] = [];
  const port: SavedReportRead = vi.fn(async (path) => {
    calls.push(path);
    if (path.endsWith(submissionId)) return completed;
    return new Promise((resolve) => {
      pending.push(() =>
        resolve(path.endsWith("transcript") ? transcript : envelope),
      );
    });
  });
  const running = preloadSavedReport(submissionId, port);
  await vi.waitFor(() => expect(pending).toHaveLength(2));
  expect(calls).toEqual([
    `/v1/conversation/acquisition/submissions/${submissionId}`,
    `/v1/conversation/acquisition/submissions/${submissionId}/transcript`,
    `/v1/conversation/acquisition/submissions/${submissionId}/report`,
  ]);
  pending.forEach((complete) => complete());
  expect(await running).toMatchObject({
    state: "ready",
    result: { transcript, runId: envelope.run_id, callRecord: null },
  });
});

it("keeps queued/working calls in their canonical state without requesting nonexistent output", async () => {
  const queued = { ...progress, state: "queued", local_state: "queued" };
  const port = read({ [submissionId]: queued });
  expect(await preloadSavedReport(submissionId, port)).toMatchObject({
    state: "processing",
    progress: { state: "queued", local_state: "queued", has_report: false },
    result: null,
  });
  expect(port).toHaveBeenCalledOnce();
});

it.each([
  [
    "submission",
    { [submissionId]: { ...completed, submission_id: recordingId } },
  ],
  ["missing field", { [submissionId]: { submission_id: submissionId } }],
  [
    "C2 source",
    { transcript: { ...transcript, source_sha256: "1".repeat(64) } },
  ],
  ["C5 identity", { report: { ...envelope, recording_id: submissionId } }],
  [
    "C5 revision",
    { report: { ...envelope, transcript_revision: "stale-revision" } },
  ],
  ["C5 content", { report: { ...envelope, report: {} } }],
  [
    "C5 report revision",
    { report: { ...envelope, report_revision: "invalid-digest" } },
  ],
])(
  "returns an unavailable state rather than throwing or showing mismatched %s",
  async (_, objects) => {
    expect(await preloadSavedReport(submissionId, read(objects))).toEqual({
      state: "unavailable",
      message: "This saved call is unavailable. Try again.",
      result: null,
    });
  },
);

it("never sends invalid IDs or provider error bodies to a page", async () => {
  const port = vi.fn(async () => {
    throw new Error("Private provider details");
  });
  expect(
    (await preloadSavedReport("https://other.example/call", port)).state,
  ).toBe("unavailable");
  expect(port).not.toHaveBeenCalled();
  expect(await preloadSavedReport(submissionId, port)).toMatchObject({
    state: "unavailable",
    message: "This saved call is unavailable. Try again.",
  });
});

it.each(["deadline", "page left"])(
  "bounds stalled adapters when %s occurs",
  async (reason) => {
    vi.useFakeTimers();
    const parent = new AbortController();
    const signals: AbortSignal[] = [];
    const port: SavedReportRead = async (_, signal) => {
      signals.push(signal);
      return new Promise(() => {});
    };
    const pending = preloadSavedReport(submissionId, port, parent.signal);
    if (reason === "deadline")
      await vi.advanceTimersByTimeAsync(SAVED_REPORT_READ_TIMEOUT_MS);
    else parent.abort();
    expect((await pending).state).toBe("unavailable");
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  },
);
