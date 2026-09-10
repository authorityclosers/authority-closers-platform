// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  PracticeFocusEnd,
  PracticeFocusStatus,
  usePracticeFocus,
} from "./practice-focus";
import {
  PracticeFocusRequestError,
  type FocusResult,
  type FocusRun,
  type FocusSummary,
  type PracticeFocusApi,
} from "../lib/practice-focus-api";
import type { PracticeAttempt } from "../lib/practice-engine-api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const attemptId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const otherAttemptId = "33333333-3333-4333-8333-333333333333";
const now = "2026-09-08T10:00:00Z";

function attempt(overrides: Partial<PracticeAttempt> = {}): PracticeAttempt {
  return {
    id: attemptId,
    set_id: "next-move",
    set_version: 1,
    content_digest: "d".repeat(64),
    state: "in_progress",
    revision: 0,
    issued_at: now,
    completed_at: null,
    set: {
      id: "next-move",
      version: 1,
      title: "Choose your next move",
      kind: "choice",
      skill: "Discovery",
      description: "Listen before proposing.",
      art: "discovery-compass",
      color: "cobalt",
      estimated_minutes: 3,
      item_count: 2,
      mode: "editorial_preview",
      items: ["first", "second"].map((id) => ({
        id,
        kind: "choice" as const,
        prompt: "What would clarify the concern?",
        hint: "Listen first.",
        options: [
          { id: 0, text: "Ask a question." },
          { id: 1, text: "Assume." },
        ],
      })),
    },
    acknowledged_item_ids: [],
    item_states: ["first", "second"].map((item_id) => ({
      item_id,
      response_id: null,
      selections: null,
      feedback: null,
      acknowledged: false,
    })),
    reward_receipts: [],
    responses_stored: true,
    course_progress_affected: false,
    ...overrides,
  };
}

function run(overrides: Partial<FocusRun> = {}): FocusRun {
  return {
    id: runId,
    attempt_id: attemptId,
    set_id: "next-move",
    state: "active",
    started_at: now,
    finished_at: null,
    exit_cost: 0,
    completion_restore: 0,
    ...overrides,
  };
}

function summary(overrides: Partial<FocusSummary> = {}): FocusSummary {
  return {
    policy_version: "arcade-focus-local-2026-09-08-v1",
    charges: 3,
    capacity: 3,
    revision: 0,
    local_day: "2026-09-08",
    timezone: "Asia/Kolkata",
    active_run: null,
    ...overrides,
  };
}

function started(overrides: Partial<FocusSummary> = {}): FocusResult {
  return {
    summary: summary({ revision: 1, active_run: run(), ...overrides }),
    run: run(),
  };
}

function ended(cost: 0 | 1 = 1): FocusResult {
  return {
    summary: summary({ revision: 2, charges: 3 - cost }),
    run: run({ state: "ended", finished_at: now, exit_cost: cost }),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

let root: Root;
let container: HTMLDivElement;
let api: PracticeFocusApi;
let unmounted: boolean;
const onReload = vi.fn();

function Harness({
  current,
  source = api,
}: {
  current: PracticeAttempt | null;
  source?: PracticeFocusApi;
}) {
  const focus = usePracticeFocus(current, source);
  const reload = () => {
    onReload();
    focus.reload();
  };
  return (
    <>
      <output aria-label="Focus reconciliation">
        {focus.uncertain ? "uncertain" : "confirmed"}
      </output>
      <PracticeFocusStatus focus={focus} attempt={current} onReload={reload} />
      {current ? (
        <PracticeFocusEnd focus={focus} attempt={current} onReload={reload} />
      ) : null}
    </>
  );
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
  onReload.mockClear();
  api = {
    summary: vi.fn(async () => summary()),
    start: vi.fn(async () => started()),
    end: vi.fn(async () => ended()),
  };
});

afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function mount(
  current: PracticeAttempt | null = attempt(),
  source = api,
) {
  await act(async () =>
    root.render(<Harness current={current} source={source} />),
  );
}

function button(label: string) {
  const node = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find((node) => node.textContent?.trim() === label);
  expect(node, label).toBeTruthy();
  return node!;
}

async function click(node: HTMLElement) {
  await act(async () => node.click());
}

it("only reads on entry and StrictMode replay; Focus is never enabled implicitly", async () => {
  await act(async () =>
    root.render(
      <StrictMode>
        <Harness current={attempt()} />
      </StrictMode>,
    ),
  );
  expect(api.summary).toHaveBeenCalled();
  expect(api.start).not.toHaveBeenCalled();
  expect(api.end).not.toHaveBeenCalled();
  expect(container.textContent).toContain("3 / 3 Focus charges");
  expect(
    container.querySelector('[aria-label="3 of 3 Focus charges"]'),
  ).not.toBeNull();
});

it("enables only by explicit click and displays the returned server counter without optimistic spending", async () => {
  const pending = deferred<FocusResult>();
  vi.mocked(api.start).mockReturnValue(pending.promise);
  await mount();
  await click(button("Enable Focus for this run"));
  expect(api.start).toHaveBeenCalledExactlyOnceWith(
    attemptId,
    { expected_revision: 0, expected_attempt_revision: 0 },
    expect.any(String),
    expect.any(AbortSignal),
  );
  expect(button("Enabling…").disabled).toBe(true);
  expect(container.textContent).toContain("3 / 3 Focus charges");
  await act(async () => pending.resolve(started({ charges: 2, revision: 7 })));
  expect(container.textContent).toContain("2 / 3 Focus charges");
  expect(container.textContent).toContain("Focus is on for this run");
  expect(api.end).not.toHaveBeenCalled();
});

it.each([
  new TypeError("offline"),
  new PracticeFocusRequestError(0, "timeout"),
  new PracticeFocusRequestError(503),
])(
  "retries an uncertain enable with exactly the same logical key and revision payload (%s)",
  async (failure) => {
    vi.mocked(api.start).mockRejectedValueOnce(failure);
    await mount();
    await click(button("Enable Focus for this run"));
    expect(container.textContent).toContain("not confirmed");
    expect(container.textContent).toContain("3 / 3 Focus charges");
    await click(button("Retry enabling Focus"));
    const [first, second] = vi.mocked(api.start).mock.calls;
    expect(second.slice(0, 3)).toEqual(first.slice(0, 3));
    expect(api.end).not.toHaveBeenCalled();
  },
);

it("preserves uncertainty and the same key through an in-flight or failed reconciliation replay", async () => {
  const pendingReplay = deferred<FocusResult>();
  vi.mocked(api.start).mockRejectedValueOnce(
    new PracticeFocusRequestError(0, "timeout"),
  );
  await mount();
  await click(button("Enable Focus for this run"));
  const reconciliation = () =>
    container.querySelector('[aria-label="Focus reconciliation"]')?.textContent;
  expect(reconciliation()).toBe("uncertain");
  vi.mocked(api.start).mockReturnValueOnce(pendingReplay.promise);
  await click(button("Check saved Focus"));
  expect(reconciliation()).toBe("uncertain");
  expect(api.summary).toHaveBeenCalledOnce();
  await act(async () =>
    pendingReplay.reject(new PracticeFocusRequestError(0, "network")),
  );
  expect(reconciliation()).toBe("uncertain");
  await click(button("Retry enabling Focus"));
  const [first, second, third] = vi.mocked(api.start).mock.calls;
  expect(second.slice(0, 3)).toEqual(first.slice(0, 3));
  expect(third.slice(0, 3)).toEqual(first.slice(0, 3));
  expect(reconciliation()).toBe("confirmed");
});

it("reconciles an unknown result with the same command, never an unrelated summary GET", async () => {
  const pendingReplay = deferred<FocusResult>();
  vi.mocked(api.start).mockRejectedValueOnce(
    new PracticeFocusRequestError(0, "timeout"),
  );
  await mount();
  await click(button("Enable Focus for this run"));
  vi.mocked(api.start).mockReturnValueOnce(pendingReplay.promise);
  await click(button("Check saved Focus"));
  expect(
    container.querySelector('[aria-label="Focus reconciliation"]')?.textContent,
  ).toBe("uncertain");
  expect(api.summary).toHaveBeenCalledOnce();
  const [first, second] = vi.mocked(api.start).mock.calls;
  expect(second.slice(0, 3)).toEqual(first.slice(0, 3));
  await act(async () => pendingReplay.resolve(started()));
  expect(
    container.querySelector('[aria-label="Focus reconciliation"]')?.textContent,
  ).toBe("confirmed");
  expect(container.textContent).toContain("Focus is on for this run");
  expect(api.start).toHaveBeenCalledTimes(2);
  expect(api.end).not.toHaveBeenCalled();
});

it("requires a conflict reload and uses the refreshed Focus and attempt revisions", async () => {
  vi.mocked(api.summary).mockResolvedValue(
    summary({ revision: 4, charges: 2, active_run: run() }),
  );
  vi.mocked(api.end).mockRejectedValueOnce(
    new PracticeFocusRequestError(409, "revision_conflict"),
  );
  await mount(attempt({ revision: 2, acknowledged_item_ids: ["first"] }));
  await click(button("End Focus run · 1 charge"));
  expect(button("End Focus run · 1 charge").disabled).toBe(true);
  vi.mocked(api.summary).mockResolvedValue(
    summary({ revision: 6, charges: 3, active_run: run() }),
  );
  await click(button("Check saved Focus"));
  expect(onReload).toHaveBeenCalledOnce();
  await mount(attempt({ revision: 4, acknowledged_item_ids: ["first"] }));
  await click(button("End Focus run · 1 charge"));
  const [first, second] = vi.mocked(api.end).mock.calls;
  expect(first[1]).toEqual({
    expected_revision: 4,
    expected_attempt_revision: 2,
  });
  expect(second[1]).toEqual({
    expected_revision: 6,
    expected_attempt_revision: 4,
  });
  expect(second[2]).not.toBe(first[2]);
});

it.each([0, 1] as const)(
  "shows exact confirmed server exit cost %i and preserves the supplied earned state",
  async (cost) => {
    const current = attempt({
      revision: cost ? 2 : 0,
      acknowledged_item_ids: cost ? ["first"] : [],
    });
    const before = structuredClone(current);
    vi.mocked(api.summary).mockResolvedValue(
      summary({ revision: 1, active_run: run() }),
    );
    vi.mocked(api.end).mockResolvedValue(ended(cost));
    await mount(current);
    expect(api.end).not.toHaveBeenCalled();
    await click(button(`End Focus run · ${cost ? "1 charge" : "no charge"}`));
    expect(api.end).toHaveBeenCalledExactlyOnceWith(
      runId,
      { expected_revision: 1, expected_attempt_revision: current.revision },
      expect.any(String),
      expect.any(AbortSignal),
    );
    expect(container.textContent).toContain(
      cost ? "1 Focus charge used." : "No charge used.",
    );
    expect(container.textContent).toContain(
      "saved answers and earned rewards are safe",
    );
    expect(container.textContent).toContain(`${3 - cost} / 3 Focus charges`);
    expect(current).toEqual(before);
    expect(api.start).not.toHaveBeenCalled();
  },
);

it("blocks duplicate end while pending and safely retries an unknown result with the same key", async () => {
  const pending = deferred<FocusResult>();
  vi.mocked(api.summary).mockResolvedValue(
    summary({ revision: 1, active_run: run() }),
  );
  vi.mocked(api.end).mockReturnValueOnce(pending.promise);
  await mount(attempt({ revision: 2, acknowledged_item_ids: ["first"] }));
  const end = button("End Focus run · 1 charge");
  await act(async () => {
    end.click();
    end.click();
  });
  expect(api.end).toHaveBeenCalledOnce();
  expect(button("Confirming…").disabled).toBe(true);
  await act(async () =>
    pending.reject(new PracticeFocusRequestError(0, "network")),
  );
  expect(container.textContent).not.toContain("1 Focus charge used.");
  await click(button("Retry ending Focus"));
  const [first, second] = vi.mocked(api.end).mock.calls;
  expect(second.slice(0, 3)).toEqual(first.slice(0, 3));
});

it("does not infer a charge from panel closure, page hiding, disconnection or unmount", async () => {
  vi.mocked(api.summary).mockResolvedValue(
    summary({ revision: 1, active_run: run() }),
  );
  await mount(attempt({ revision: 2, acknowledged_item_ids: ["first"] }));
  await act(async () => {
    const panel = container.querySelector("details")!;
    panel.open = true;
    panel.open = false;
    panel.dispatchEvent(new Event("toggle"));
    window.dispatchEvent(new Event("pagehide"));
    window.dispatchEvent(new Event("offline"));
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await act(async () => root.unmount());
  unmounted = true;
  expect(api.start).not.toHaveBeenCalled();
  expect(api.end).not.toHaveBeenCalled();
});

it("links another active run using its server-provided safe set and attempt without starting a replacement", async () => {
  vi.mocked(api.summary).mockResolvedValue(
    summary({
      revision: 3,
      active_run: run({ attempt_id: otherAttemptId, set_id: "gaps" }),
    }),
  );
  await mount();
  const resume = container.querySelector<HTMLAnchorElement>("a");
  expect(resume?.getAttribute("href")).toBe(
    `/practice?set=gaps&attempt=${otherAttemptId}`,
  );
  expect(resume?.textContent).toBe("Resume your Focus run");
  expect(container.textContent).not.toContain("Enable Focus for this run");
  expect(container.textContent).not.toContain("End Focus run ·");
  expect(api.start).not.toHaveBeenCalled();
  expect(api.end).not.toHaveBeenCalled();
});

it("keeps standard practice available at zero or when optional Focus cannot load", async () => {
  vi.mocked(api.summary).mockResolvedValue(
    summary({ charges: 0, revision: 6 }),
  );
  await mount();
  expect(button("Enable Focus for this run").disabled).toBe(true);
  expect(container.textContent).toContain("standard mode");
  vi.mocked(api.summary).mockRejectedValue(new PracticeFocusRequestError(503));
  await mount(attempt({ id: otherAttemptId }));
  expect(container.textContent).toContain(
    "Standard practice is still available",
  );
  expect(api.start).not.toHaveBeenCalled();
});

it("aborts both reads and mutations on unmount and ignores late results", async () => {
  const pending = deferred<FocusResult>();
  vi.mocked(api.start).mockReturnValue(pending.promise);
  await mount();
  const readSignal = vi.mocked(api.summary).mock.calls[0][0];
  await click(button("Enable Focus for this run"));
  const mutationSignal = vi.mocked(api.start).mock.calls[0][3];
  await act(async () => root.unmount());
  unmounted = true;
  expect(readSignal.aborted).toBe(true);
  expect(mutationSignal.aborted).toBe(true);
  await act(async () => pending.resolve(started()));
  expect(container.innerHTML).toBe("");
});

it("discards an old attempt's pending command and late result when the attempt scope changes", async () => {
  const pending = deferred<FocusResult>();
  vi.mocked(api.start).mockReturnValueOnce(pending.promise);
  await mount();
  await click(button("Enable Focus for this run"));
  const oldSignal = vi.mocked(api.start).mock.calls[0][3];
  await mount(attempt({ id: otherAttemptId }));
  expect(oldSignal.aborted).toBe(true);
  await act(async () => pending.resolve(started()));
  expect(container.textContent).not.toContain("Resume your Focus run");
  expect(button("Enable Focus for this run").disabled).toBe(false);
  vi.mocked(api.start).mockResolvedValue({
    summary: summary({
      revision: 1,
      active_run: run({ attempt_id: otherAttemptId }),
    }),
    run: run({ attempt_id: otherAttemptId }),
  });
  await click(button("Enable Focus for this run"));
  expect(vi.mocked(api.start).mock.calls[1][0]).toBe(otherAttemptId);
  expect(vi.mocked(api.start).mock.calls[1][2]).not.toBe(
    vi.mocked(api.start).mock.calls[0][2],
  );
});

it("discards in-flight mutations when the authority API scope changes without changing attempt id", async () => {
  const pending = deferred<FocusResult>();
  vi.mocked(api.start).mockReturnValueOnce(pending.promise);
  await mount();
  await click(button("Enable Focus for this run"));
  const oldSignal = vi.mocked(api.start).mock.calls[0][3];
  const replacement: PracticeFocusApi = {
    summary: vi.fn(async () => summary({ charges: 1, revision: 8 })),
    start: vi.fn(async () => started({ charges: 1, revision: 9 })),
    end: vi.fn(async () => ended()),
  };
  await mount(attempt(), replacement);
  expect(oldSignal.aborted).toBe(true);
  await act(async () => pending.resolve(started()));
  expect(container.textContent).toContain("1 / 3 Focus charges");
  await click(button("Enable Focus for this run"));
  expect(replacement.start).toHaveBeenCalledExactlyOnceWith(
    attemptId,
    { expected_revision: 8, expected_attempt_revision: 0 },
    expect.any(String),
    expect.any(AbortSignal),
  );
});
