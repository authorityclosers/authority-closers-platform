import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  observeSubmission,
  STATUS_READ_TIMEOUT_MS,
} from "./observe-submission";
import {
  envelope,
  progress,
  recordingId,
  submissionId,
  transcript,
} from "../tests/acquisition-fixture";

const bound = { id: submissionId, recordingId, sha: progress.source_sha256 };
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
let progressBody: unknown;
let pending: Array<{
  path: string;
  signal: AbortSignal;
  resolve: (response: Response) => void;
}>;

beforeEach(() => {
  progressBody = { ...progress, has_report: true };
  pending = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init: RequestInit) => {
      if (path.endsWith(`/submissions/${submissionId}`))
        return Promise.resolve(response(progressBody));
      return new Promise<Response>((resolve, reject) => {
        const signal = init.signal!;
        pending.push({ path, signal, resolve });
        signal.addEventListener("abort", () => reject(signal.reason), {
          once: true,
        });
        if (signal.aborted) reject(signal.reason);
      });
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function start(signal = new AbortController().signal) {
  vi.useFakeTimers();
  const running = observeSubmission(bound, signal);
  // Attach rejection handling before advancing fake timers or aborting.
  const settled = running.then(
    (value) => ({ value, error: null }),
    (error: unknown) => ({ value: null, error }),
  );
  await vi.advanceTimersByTimeAsync(0);
  return { running, settled };
}

function complete(
  transcriptBody: unknown = transcript,
  reportBody: unknown = envelope,
) {
  pending
    .find(({ path }) => path.endsWith("/transcript"))!
    .resolve(response(transcriptBody));
  pending
    .find(({ path }) => path.endsWith("/report"))!
    .resolve(response(reportBody));
}

it("does not request either object until canonical progress confirms a report", async () => {
  progressBody = progress;
  const { running } = await start();
  await expect(running).resolves.toMatchObject({ result: null });
  expect(pending).toHaveLength(0);
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["transcript", "report"])(
  "starts both GETs before either resolves, including when %s finishes first",
  async (first) => {
    const { running } = await start();
    expect(pending.map(({ path }) => path.split("/").at(-1))).toEqual([
      "transcript",
      "report",
    ]);
    const firstRequest = pending.find(({ path }) =>
      path.endsWith(`/${first}`),
    )!;
    firstRequest.resolve(
      response(first === "transcript" ? transcript : envelope),
    );
    await vi.advanceTimersByTimeAsync(0);
    const other = pending.find((request) => request !== firstRequest)!;
    other.resolve(response(first === "transcript" ? envelope : transcript));
    await expect(running).resolves.toMatchObject({
      result: { transcript, runId: envelope.run_id, callRecord: null },
    });
    expect(vi.getTimerCount()).toBe(0);
  },
);

it("rejects an invalid transcript before it validates the report", async () => {
  const { running } = await start();
  complete({ ...transcript, source_sha256: "1".repeat(64) }, {});
  await expect(running).rejects.toThrow("transcript_source_mismatch");
  expect(vi.getTimerCount()).toBe(0);
});

it.each([
  ["schema", "untrusted-schema"],
  ["submission_id", recordingId],
  ["recording_id", submissionId],
  ["source_sha256", "1".repeat(64)],
  ["transcript_revision", "another-revision"],
])("rejects a report with mismatched %s", async (field, value) => {
  const { running } = await start();
  complete(transcript, { ...envelope, [field]: value });
  await expect(running).rejects.toThrow("report_envelope_binding");
  expect(vi.getTimerCount()).toBe(0);
});

it("rejects malformed report content even when its identity matches", async () => {
  const { running } = await start();
  complete(transcript, { ...envelope, report: {} });
  await expect(running).rejects.toThrow();
  expect(vi.getTimerCount()).toBe(0);
});

it("cancels both in-flight reads when the page owner aborts", async () => {
  const parent = new AbortController();
  const { settled } = await start(parent.signal);
  expect(pending).toHaveLength(2);
  const reason = new DOMException("Page left", "AbortError");
  parent.abort(reason);
  expect(
    pending.every(({ signal }) => signal.aborted && signal.reason === reason),
  ).toBe(true);
  expect((await settled).error).toBe(reason);
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["both", "transcript", "report"])(
  "keeps the 30-second bound when %s stalls",
  async (stalled) => {
    const { settled } = await start();
    expect(pending).toHaveLength(2);
    if (stalled !== "both") {
      const other = pending.find(({ path }) => !path.endsWith(`/${stalled}`))!;
      other.resolve(response(stalled === "transcript" ? envelope : transcript));
    }
    await vi.advanceTimersByTimeAsync(STATUS_READ_TIMEOUT_MS - 1);
    expect(pending.every(({ signal }) => !signal.aborted)).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    expect((await settled).error).toMatchObject({ name: "TimeoutError" });
    expect(pending.filter(({ signal }) => signal.aborted)).toHaveLength(
      stalled === "both" ? 2 : 1,
    );
    expect(vi.getTimerCount()).toBe(0);
  },
);
