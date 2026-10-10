import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { plan, recordingId, submissionId } from "../tests/acquisition-fixture";
import { AnalysisRetryAction } from "./analysis-retry-status";
import { notify } from "./notice-center";

vi.mock("./notice-center", () => ({ notify: vi.fn() }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const button = () => container.querySelector("button")!;
const render = async () =>
  act(async () =>
    root.render(
      <AnalysisRetryAction
        submissionId={submissionId}
        recordingId={recordingId}
      />,
    ),
  );
const click = async () => act(async () => button().click());

it("coalesces a double click and accepts only the displayed successor plan", async () => {
  let resolve!: (value: Response) => void;
  const fetch = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ...plan, accepted: true, state: "active" }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => undefined);
  await render();
  await act(async () => {
    button().click();
    button().click();
  });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(button().disabled).toBe(true);
  await act(async () => resolve(new Response(JSON.stringify(plan))));
  expect(container.textContent).toContain("Providers and privacy terms");
  expect(container.textContent).toContain(
    "used only when a report is delivered",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  await click();
  expect(fetch).toHaveBeenCalledTimes(2);
  const first = fetch.mock.calls[0][1] as RequestInit;
  const accepted = fetch.mock.calls[1][1] as RequestInit;
  expect(fetch.mock.calls[0][0]).toContain(
    `/submissions/${submissionId}/retry`,
  );
  expect(fetch.mock.calls[1][0]).toContain(`/submissions/${submissionId}/plan`);
  expect((accepted.headers as Record<string, string>)["Idempotency-Key"]).toBe(
    `${(first.headers as Record<string, string>)["Idempotency-Key"]}:accept`,
  );
  expect(JSON.parse(accepted.body as string)).toEqual({
    plan_id: plan.id,
    plan_fingerprint: plan.plan_fingerprint,
    privacy_revision: plan.privacy_revision,
    accepted: true,
  });
  expect(reload).toHaveBeenCalledTimes(1);
});

it("keeps an ambiguous request key and sends errors to a corner card", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new Error("fictional offline"))
    .mockResolvedValueOnce(new Response(JSON.stringify(plan)));
  vi.stubGlobal("fetch", fetch);
  await render();
  await click();
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "error" }),
  );
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(button().textContent).toBe("Try again");
  await click();
  expect(fetch.mock.calls[1][1].headers["Idempotency-Key"]).toBe(
    fetch.mock.calls[0][1].headers["Idempotency-Key"],
  );
});

it("refuses a plan for another recording before any acceptance", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        ...plan,
        recording_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      }),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  await render();
  await click();
  expect(button().textContent).toBe("Try again");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(notify).toHaveBeenCalledTimes(1);
});

it("ends a silent network wait while preserving the request for reconciliation", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_url, init: RequestInit) =>
        new Promise((_done, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    ),
  );
  await render();
  await click();
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(button().disabled).toBe(false);
  expect(button().textContent).toBe("Try again");
  expect(sessionStorage.getItem(`ac.xray.retry.v1:${submissionId}`)).toMatch(
    /^retry:/,
  );
  expect(notify).toHaveBeenCalledTimes(1);
});

it("starts a confirmed local retry with no provider acceptance", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        retry_kind: "local",
        recording_id: recordingId,
        run_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        state: "queued",
      }),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => undefined);
  await render();
  await click();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(reload).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(`ac.xray.retry.v1:${submissionId}`)).toBeNull();
});

it("reconciles an already accepted retry after a browser restart", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...plan,
          accepted: true,
          state: "active",
        }),
      ),
    ),
  );
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => undefined);
  await render();
  await click();
  expect(reload).toHaveBeenCalledTimes(1);
  expect(container.textContent).not.toContain("Review this retry");
});

it("does not confirm acceptance for a different plan on the same call", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(plan)))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...plan,
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          accepted: true,
          state: "active",
        }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => undefined);
  await render();
  await click();
  await click();
  expect(reload).not.toHaveBeenCalled();
  expect(notify).toHaveBeenCalledTimes(1);
});

it.each(["held", "cancelled"])(
  "returns to Try again when the exact accepted retry becomes %s",
  async (state) => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(plan)))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...plan, accepted: true, state })),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(plan)));
    vi.stubGlobal("fetch", fetch);
    const reload = vi
      .spyOn(window.location, "reload")
      .mockImplementation(() => undefined);
    await render();
    await click();
    const originalKey = fetch.mock.calls[0][1].headers["Idempotency-Key"];
    await click();
    expect(button().textContent).toBe("Try again");
    expect(container.textContent).not.toContain("Review this retry");
    expect(
      sessionStorage.getItem(`ac.xray.retry.v1:${submissionId}`),
    ).toBeNull();
    expect(reload).not.toHaveBeenCalled();
    await click();
    expect(fetch.mock.calls[2][0]).toContain("/retry");
    expect(fetch.mock.calls[2][1].headers["Idempotency-Key"]).not.toBe(
      originalKey,
    );
  },
);

it("reconciles an expired approval refusal against the exact terminal plan", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(plan)))
    .mockResolvedValueOnce(new Response("", { status: 403 }))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...plan, state: "held" })),
    );
  vi.stubGlobal("fetch", fetch);
  await render();
  await click();
  await click();
  expect(fetch.mock.calls[2][0]).toContain("/plan");
  expect(fetch.mock.calls[2][1].method).toBeUndefined();
  expect(button().textContent).toBe("Try again");
  expect(sessionStorage.getItem(`ac.xray.retry.v1:${submissionId}`)).toBeNull();
  expect(notify).toHaveBeenCalledTimes(1);
});

it("retains the approval command when a refusal read returns another plan", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(plan)))
    .mockResolvedValueOnce(new Response("", { status: 403 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...plan,
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          state: "held",
        }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  await render();
  await click();
  const key = sessionStorage.getItem(`ac.xray.retry.v1:${submissionId}`);
  await click();
  expect(button().textContent).toBe("Accept and retry analysis");
  expect(sessionStorage.getItem(`ac.xray.retry.v1:${submissionId}`)).toBe(key);
  expect(notify).toHaveBeenCalledTimes(1);
});

it("reuses an ambiguous acceptance command without issuing a fresh retry", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(plan)))
    .mockRejectedValueOnce(new Error("fictional acknowledgement lost"))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ...plan, accepted: true, state: "active" }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const reload = vi
    .spyOn(window.location, "reload")
    .mockImplementation(() => undefined);
  await render();
  await click();
  await click();
  expect(button().textContent).toBe("Accept and retry analysis");
  await click();
  expect(fetch.mock.calls[2][0]).toContain("/plan");
  expect(fetch.mock.calls[2][1].headers["Idempotency-Key"]).toBe(
    fetch.mock.calls[1][1].headers["Idempotency-Key"],
  );
  expect(reload).toHaveBeenCalledTimes(1);
});
