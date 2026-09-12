// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  isPracticeTimezone,
  PracticeEngine,
  PracticeRecognition,
} from "./practice-engine";
import {
  PracticeEngineRequestError,
  type PracticeAttempt,
  type PracticeEngineApi,
  type PracticeProgress,
} from "../lib/practice-engine-api";
import type { PracticeSet } from "../lib/practice-api";
import type { PracticeFocusApi } from "../lib/practice-focus-api";
import * as soundModule from "../lib/practice-sounds";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const id = "11111111-1111-4111-8111-111111111111";
const responseId = "22222222-2222-4222-8222-222222222222";
const now = "2026-09-08T10:00:00Z";
const set: PracticeSet = {
  id: "next-move",
  version: 1,
  title: "Find your next move",
  kind: "choice",
  skill: "Discovery",
  description: "A useful question.",
  art: "discovery-compass",
  color: "cobalt",
  estimated_minutes: 3,
  item_count: 1,
  mode: "editorial_preview",
  items: [
    {
      id: "choice-01",
      kind: "choice",
      prompt: "What would clarify the concern?",
      hint: "Listen first.",
      options: [
        { id: 0, text: "Ask what matters." },
        { id: 1, text: "Assume the answer." },
      ],
    },
  ],
};
const feedback = {
  kind: "feedback" as const,
  reference_match: true,
  explanation: "A question gives them space.",
  responses_stored: true as const,
  course_progress_affected: false as const,
};
const emptyAttempt = (): PracticeAttempt => ({
  id,
  set_id: set.id,
  set_version: 1,
  content_digest: "d".repeat(64),
  state: "in_progress",
  revision: 1,
  issued_at: now,
  completed_at: null,
  set,
  acknowledged_item_ids: [],
  item_states: [
    {
      item_id: "choice-01",
      response_id: null,
      selections: null,
      feedback: null,
      acknowledged: false,
    },
  ],
  reward_receipts: [],
  responses_stored: true,
  course_progress_affected: false,
});
const answeredAttempt = (): PracticeAttempt => ({
  ...emptyAttempt(),
  revision: 2,
  item_states: [
    {
      item_id: "choice-01",
      response_id: responseId,
      selections: [0],
      feedback,
      acknowledged: false,
    },
  ],
});
const completedAttempt = (): PracticeAttempt => ({
  ...answeredAttempt(),
  revision: 3,
  state: "completed",
  completed_at: now,
  acknowledged_item_ids: ["choice-01"],
  item_states: [
    {
      item_id: "choice-01",
      response_id: responseId,
      selections: [0],
      feedback,
      acknowledged: true,
    },
  ],
  reward_receipts: [
    {
      id: responseId,
      kind: "daily_set",
      credits: 10,
      xp: 30,
      local_day: "2026-09-08",
      week_start: "2026-09-07",
      created_at: now,
    },
  ],
});
const progress = (): PracticeProgress => ({
  profile: {
    timezone: "Asia/Kolkata",
    revision: 1,
    pending_timezone: null,
    pending_effective_at: null,
  },
  credits_balance: 0,
  xp_total: 0,
  actual_practice_days_this_week: 0,
  policy_version: "arcade-earned-pilot-2026-09-08-v1",
  recent_attempts: [],
  recent_awards: [],
  purchases_enabled: false,
  course_progress_affected: false,
});
let root: Root;
let container: HTMLDivElement;
let api: PracticeEngineApi;
let focusApi: PracticeFocusApi;
let unmounted: boolean;
const contentApi = { set: vi.fn(async () => set) };
beforeEach(() => {
  soundModule.savePracticeSounds(false);
  window.localStorage.removeItem("ac-practice-companion");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.open = false;
  });
  api = {
    progress: vi.fn(async () => progress()),
    profile: vi.fn(async () => progress().profile),
    updateProfile: vi.fn(async () => progress().profile),
    issue: vi.fn(async () => emptyAttempt()),
    attempt: vi.fn(async () => answeredAttempt()),
    respond: vi.fn(async () => answeredAttempt()),
    acknowledge: vi.fn(async () => completedAttempt()),
  };
  focusApi = {
    summary: vi.fn(async () => ({
      policy_version: "arcade-focus-local-2026-09-08-v1",
      charges: 3,
      capacity: 3 as const,
      revision: 0,
      local_day: "2026-09-08",
      timezone: "Asia/Kolkata",
      active_run: null,
    })),
    start: vi.fn(async () => {
      throw new Error("Unexpected Focus activation in standard practice test");
    }),
    end: vi.fn(async () => {
      throw new Error("Unexpected Focus end in standard practice test");
    }),
  };
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  expect(focusApi.start).not.toHaveBeenCalled();
  expect(focusApi.end).not.toHaveBeenCalled();
  container.remove();
  vi.restoreAllMocks();
});
async function mount(attemptId?: string) {
  await act(async () =>
    root.render(
      <PracticeEngine
        setId="next-move"
        attemptId={attemptId}
        api={api}
        contentApi={contentApi}
        focusApi={focusApi}
      />,
    ),
  );
}
function button(text: string) {
  const result = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find(
    (node) =>
      node.textContent?.trim() === text ||
      node.getAttribute("aria-label") === text,
  );
  expect(result, text).toBeTruthy();
  return result!;
}
async function click(node: HTMLElement) {
  await act(async () => node.click());
}

it("does not issue or reward on entry; explicitly starts then awards only after acknowledged server completion", async () => {
  await mount();
  expect(api.issue).not.toHaveBeenCalled();
  expect(api.acknowledge).not.toHaveBeenCalled();
  await click(button("Start a new practice"));
  expect(window.location.search).toContain(`attempt=${id}`);
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));
  expect(container.textContent).toContain(feedback.explanation);
  expect(container.textContent).not.toContain("+10 credits");
  expect(api.acknowledge).not.toHaveBeenCalled();
  await click(button("Finish this set"));
  expect(api.respond).toHaveBeenCalledWith(
    id,
    { item_id: "choice-01", selections: [0], expected_revision: 1 },
    expect.any(String),
    expect.any(AbortSignal),
  );
  expect(api.acknowledge).toHaveBeenCalledWith(
    id,
    responseId,
    { expected_revision: 2 },
    expect.any(String),
    expect.any(AbortSignal),
  );
  expect(container.textContent).toContain("+10 credits · +30 XP");
  expect(container.textContent).toContain("Practice saved");
  expect(document.activeElement?.id).toBe("practice-earned-title");
  expect(container.querySelector('[data-animate="true"]')).not.toBeNull();
});

it("shows past earned receipts without replaying a fresh celebration or sound", async () => {
  const play = vi.fn();
  vi.spyOn(soundModule, "createPracticeSoundPlayer").mockReturnValue({
    prepare: vi.fn(),
    play,
    setEnabled: vi.fn(),
    setVolume: vi.fn(),
    preview: vi.fn(),
    stop: vi.fn(),
    dispose: vi.fn(),
  });
  vi.mocked(api.attempt).mockResolvedValue(completedAttempt());
  await mount(id);
  expect(container.textContent).toContain("+10 credits");
  expect(container.querySelector('[data-animate="true"]')).toBeNull();
  expect(play).not.toHaveBeenCalled();
});

it("uses user-gesture sound preparation, confirmed reward cues and immediate mute", async () => {
  const player = {
    prepare: vi.fn(),
    play: vi.fn(),
    setEnabled: vi.fn(),
    setVolume: vi.fn(),
    preview: vi.fn(),
    stop: vi.fn(),
    dispose: vi.fn(),
  };
  vi.spyOn(soundModule, "createPracticeSoundPlayer").mockReturnValue(player);
  await mount(id);
  expect(player.prepare).not.toHaveBeenCalled();
  expect(player.play).not.toHaveBeenCalled();
  await click(
    container.querySelector<HTMLButtonElement>(
      '[aria-label="Unmute practice sounds"]',
    )!,
  );
  expect(player.setEnabled).toHaveBeenLastCalledWith(true);
  expect(player.prepare).toHaveBeenCalledOnce();
  await click(button("Finish this set"));
  expect(player.play).toHaveBeenCalledExactlyOnceWith(
    "reward",
    `completion:${id}`,
  );
  await click(
    container.querySelector<HTMLButtonElement>(
      '[aria-label="Mute practice sounds"]',
    )!,
  );
  expect(player.setEnabled).toHaveBeenLastCalledWith(false);
  await act(async () => root.unmount());
  unmounted = true;
  expect(player.dispose).toHaveBeenCalledOnce();
});

it.each([
  { referenceMatch: true, expectedCue: "confirm" },
  { referenceMatch: false, expectedCue: "retry" },
  { referenceMatch: null, expectedCue: null },
] as const)(
  "routes editorial reference match $referenceMatch to $expectedCue feedback audio",
  async ({ referenceMatch, expectedCue }) => {
    const play = vi.fn();
    vi.spyOn(soundModule, "createPracticeSoundPlayer").mockReturnValue({
      prepare: vi.fn(),
      play,
      setEnabled: vi.fn(),
      setVolume: vi.fn(),
      preview: vi.fn(),
      stop: vi.fn(),
      dispose: vi.fn(),
    });
    vi.mocked(api.respond).mockResolvedValue({
      ...answeredAttempt(),
      item_states: [
        {
          ...answeredAttempt().item_states[0],
          feedback: { ...feedback, reference_match: referenceMatch },
        },
      ],
    });

    await mount();
    await click(button("Start a new practice"));
    await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
    await click(button("Check my response"));

    const feedbackCalls = play.mock.calls.filter(([kind]) => kind !== "select");
    if (expectedCue) {
      expect(feedbackCalls).toEqual([
        [expectedCue, `response:${responseId}:reference:${referenceMatch}`],
      ]);
    } else {
      expect(feedbackCalls).toEqual([]);
    }
  },
);

it("plays no feedback cue when the response request has no canonical result", async () => {
  const play = vi.fn();
  vi.spyOn(soundModule, "createPracticeSoundPlayer").mockReturnValue({
    prepare: vi.fn(),
    play,
    setEnabled: vi.fn(),
    setVolume: vi.fn(),
    preview: vi.fn(),
    stop: vi.fn(),
    dispose: vi.fn(),
  });
  vi.mocked(api.respond).mockRejectedValue(new TypeError("Network failed"));

  await mount();
  await click(button("Start a new practice"));
  await click(container.querySelector<HTMLInputElement>('input[value="0"]')!);
  await click(button("Check my response"));

  expect(play.mock.calls.filter(([kind]) => kind !== "select")).toEqual([]);
});

it("lets a learner choose a decorative companion without any account or reward mutation", async () => {
  await mount();
  expect(container.textContent).not.toContain("A useful question.");
  await click(button("Practice details"));
  expect(container.querySelector("dialog[open]")?.textContent).toContain(
    "A useful question.",
  );
  await click(button("Scout"));
  expect(window.localStorage.getItem("ac-practice-companion")).toBe("scout");
  expect(
    container.querySelector('section svg[data-companion="scout"]'),
  ).not.toBeNull();
  expect(api.updateProfile).not.toHaveBeenCalled();
  expect(api.issue).not.toHaveBeenCalled();
  expect(api.acknowledge).not.toHaveBeenCalled();
});

it("resumes saved feedback without reissuing or resubmitting a response", async () => {
  await mount(id);
  expect(api.issue).not.toHaveBeenCalled();
  expect(api.respond).not.toHaveBeenCalled();
  expect(container.textContent).toContain(feedback.explanation);
  await click(button("Finish this set"));
  expect(api.acknowledge).toHaveBeenCalledTimes(1);
});

it("keeps feedback on acknowledgement failure and reuses the exact command key/body on retry", async () => {
  vi.mocked(api.acknowledge).mockRejectedValueOnce(
    new TypeError("Network failed"),
  );
  await mount(id);
  await click(button("Finish this set"));
  expect(container.textContent).toContain(feedback.explanation);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "feedback couldn’t be saved",
  );
  expect(container.textContent).not.toContain("Practice saved");
  await click(button("Finish this set"));
  const [first, second] = vi.mocked(api.acknowledge).mock.calls;
  expect(first.slice(0, 4)).toEqual(second.slice(0, 4));
  expect(container.textContent).toContain("+10 credits · +30 XP");
});

it("blocks double acknowledgement and aborts its pending response on unmount", async () => {
  let resolve!: (value: PracticeAttempt) => void;
  vi.mocked(api.acknowledge).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  await mount(id);
  const finish = button("Finish this set");
  await act(async () => {
    finish.click();
    finish.click();
  });
  expect(api.acknowledge).toHaveBeenCalledTimes(1);
  expect(button("Saving…").disabled).toBe(true);
  const signal = vi.mocked(api.acknowledge).mock.calls[0][4];
  await act(async () => root.unmount());
  unmounted = true;
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(completedAttempt()));
  expect(container.innerHTML).toBe("");
});

it("requires explicit timezone confirmation, not a silent timezone write on mount", async () => {
  vi.mocked(api.progress).mockResolvedValue({
    ...progress(),
    profile: { ...progress().profile, timezone: null, revision: 0 },
  });
  await mount();
  expect(api.updateProfile).not.toHaveBeenCalled();
  expect(container.querySelector("input[list]")).not.toBeNull();
  await click(button("Save timezone & start"));
  expect(api.updateProfile).toHaveBeenCalledWith(
    { timezone: expect.any(String), expected_revision: 0 },
    expect.any(String),
    expect.any(AbortSignal),
  );
  expect(api.issue).toHaveBeenCalledTimes(1);
});

it("never invents an award for a completed replay without receipts", async () => {
  vi.mocked(api.attempt).mockResolvedValue({
    ...completedAttempt(),
    reward_receipts: [],
  });
  await mount(id);
  expect(container.textContent).toContain("No new reward was added");
  expect(container.textContent).not.toContain("+10");
});

it.each([401, 403, 404])(
  "offers a real recovery route for an unavailable saved attempt (%i)",
  async (status) => {
    vi.mocked(api.attempt).mockRejectedValue(
      new PracticeEngineRequestError(status),
    );
    await mount(id);
    expect(
      container.querySelector(
        'a[href="' +
          (status === 401 ? "/login" : status === 403 ? "/home" : "/practice") +
          '"]',
      ),
    ).not.toBeNull();
    expect(container.textContent).not.toContain("couldn’t connect");
    expect(api.issue).not.toHaveBeenCalled();
  },
);

it("offers sign-in when the session expires after the preflight loaded", async () => {
  vi.mocked(api.issue).mockRejectedValue(new PracticeEngineRequestError(401));
  await mount();
  await click(button("Start a new practice"));
  expect(container.querySelector('a[href="/login"]')).not.toBeNull();
  expect(container.textContent).not.toContain("Practice saved");
});

it("closes the exit dialog through native cancel and restores focus to its trigger", async () => {
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.open = true;
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  });
  await mount(id);
  const exit = container.querySelector<HTMLButtonElement>(
    'button[aria-label="Leave practice"]',
  )!;
  await click(exit);
  const dialog = container.querySelector("dialog")!;
  const cancel = new Event("cancel", { cancelable: true });
  await act(async () => {
    dialog.dispatchEvent(cancel);
  });
  expect(cancel.defaultPrevented).toBe(true);
  expect(document.activeElement).toBe(exit);
  expect(container.querySelector("dialog")).toBeNull();
  expect(api.respond).not.toHaveBeenCalled();
  expect(api.acknowledge).not.toHaveBeenCalled();
});

it("rejects invalid timezone suggestions and lets definite server input rejection be corrected", async () => {
  expect(isPracticeTimezone("not/a/timezone")).toBe(false);
  expect(isPracticeTimezone("Asia/Kolkata")).toBe(true);
  vi.mocked(api.progress).mockResolvedValue({
    ...progress(),
    profile: { ...progress().profile, timezone: null, revision: 0 },
  });
  vi.mocked(api.updateProfile).mockRejectedValueOnce(
    new PracticeEngineRequestError(422),
  );
  await mount();
  await click(button("Save timezone & start"));
  expect(
    container.querySelector<HTMLInputElement>("input[list]")?.disabled,
  ).toBe(false);
  expect(container.textContent).toContain("Choose a valid timezone");
  expect(api.issue).not.toHaveBeenCalled();
  await click(button("Save timezone & start"));
  const [first, second] = vi.mocked(api.updateProfile).mock.calls;
  expect(first[1]).not.toBe(second[1]);
  expect(api.issue).toHaveBeenCalledTimes(1);
});

it("refreshes an initial profile conflict before creating a fresh start command", async () => {
  vi.mocked(api.progress).mockResolvedValueOnce({
    ...progress(),
    profile: { ...progress().profile, timezone: null, revision: 0 },
  });
  vi.mocked(api.updateProfile).mockRejectedValueOnce(
    new PracticeEngineRequestError(409),
  );
  await mount();
  await click(button("Save timezone & start"));
  expect(button("Save timezone & start").disabled).toBe(true);
  await click(button("Reload saved preferences"));
  expect(api.progress).toHaveBeenCalledTimes(2);
  await click(button("Start a new practice"));
  expect(api.updateProfile).toHaveBeenCalledTimes(1);
  expect(api.issue).toHaveBeenCalledTimes(1);
});

it("keeps the same issuance key after an uncertain start result", async () => {
  vi.mocked(api.issue).mockRejectedValueOnce(
    new PracticeEngineRequestError(0, "network"),
  );
  await mount();
  await click(button("Start a new practice"));
  await click(button("Start a new practice"));
  const [first, second] = vi.mocked(api.issue).mock.calls;
  expect(first.slice(0, 2)).toEqual(second.slice(0, 2));
});

it("unlocks wallet timezone correction after definite input rejection", async () => {
  vi.mocked(api.updateProfile).mockRejectedValueOnce(
    new PracticeEngineRequestError(400),
  );
  await act(async () => root.render(<PracticeRecognition api={api} />));
  await click(button("View your week"));
  await click(button("Change timezone"));
  await click(button("Save timezone"));
  expect(
    container.querySelector<HTMLInputElement>("input[list]")?.disabled,
  ).toBe(false);
  expect(container.textContent).toContain("Choose a valid timezone");
  await click(button("Save timezone"));
  const [first, second] = vi.mocked(api.updateProfile).mock.calls;
  expect(first[1]).not.toBe(second[1]);
});

it("requires refreshing a conflicting revision and restores the saved feedback", async () => {
  vi.mocked(api.acknowledge).mockRejectedValueOnce(
    new PracticeEngineRequestError(409),
  );
  await mount(id);
  await click(button("Finish this set"));
  expect(button("Finish this set").disabled).toBe(true);
  await click(button("Reload saved attempt"));
  expect(button("Finish this set").disabled).toBe(false);
  expect(container.textContent).toContain(feedback.explanation);
});

it("renders server wallet totals without awarding or issuing in StrictMode", async () => {
  vi.mocked(api.progress).mockResolvedValue({
    ...progress(),
    credits_balance: 74,
    xp_total: 90,
    actual_practice_days_this_week: 3,
  });
  await act(async () =>
    root.render(
      <StrictMode>
        <PracticeRecognition api={api} />
      </StrictMode>,
    ),
  );
  const wallet = container.querySelector('[aria-label="Your saved practice"]');
  expect(wallet?.textContent).toContain("74");
  expect(wallet?.textContent).toContain("90");
  expect(
    wallet
      ?.querySelector('[role="progressbar"]')
      ?.getAttribute("aria-valuenow"),
  ).toBe("3");
  expect(wallet?.querySelectorAll("[data-learning-symbol]")).toHaveLength(3);
  expect(api.issue).not.toHaveBeenCalled();
  expect(api.updateProfile).not.toHaveBeenCalled();
  expect(api.acknowledge).not.toHaveBeenCalled();
});

it("shows the original reward date and receipt without treating an empty week as a streak", async () => {
  vi.mocked(api.progress).mockResolvedValue({
    ...progress(),
    recent_awards: completedAttempt().reward_receipts,
  });
  await act(async () => root.render(<PracticeRecognition api={api} />));
  expect(
    container
      .querySelector('[role="progressbar"]')
      ?.getAttribute("aria-valuenow"),
  ).toBe("0");
  expect(container.querySelector("details")).toBeNull();
  await click(
    container.querySelector<HTMLButtonElement>(
      'button[aria-label="0 earned credits. View details"]',
    )!,
  );
  await click(button("Reward activity"));
  expect(container.textContent).toContain("Your recent rewards");
  expect(container.textContent).toContain("Sep 8");
  expect(container.textContent).toContain("+10 credits · +30 XP");
  expect(container.textContent).not.toMatch(/streak|mastery|rank/i);
  expect(api.acknowledge).not.toHaveBeenCalled();
});

it("opens accessible reward sheets on tap, restores focus on Escape and restores page scrolling", async () => {
  document.body.style.overflow = "auto";
  await act(async () => root.render(<PracticeRecognition api={api} />));
  const trigger = container.querySelector<HTMLButtonElement>(
    'button[aria-label="0 earned credits. View details"]',
  )!;
  await click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  const dialog = container.querySelector<HTMLDialogElement>("dialog")!;
  expect(dialog.open).toBe(true);
  expect(
    document.getElementById(dialog.getAttribute("aria-labelledby")!)
      ?.textContent,
  ).toBe("Earned credits");
  await click(button("Reward activity"));
  expect(dialog.textContent).toContain("Your first reward belongs here");
  expect(document.body.style.overflow).toBe("hidden");
  await act(async () =>
    dialog.dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  expect(container.querySelector("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(document.body.style.overflow).toBe("auto");
  expect(api.issue).not.toHaveBeenCalled();
  document.body.style.overflow = "";
});

it("keeps XP, academy leaderboard access and weekly activity distinct without fake scores or purchases", async () => {
  await act(async () => root.render(<PracticeRecognition api={api} />));
  const weekTrigger = button("View your week");
  const weekProgress = container.querySelector('[role="progressbar"]')!;
  expect(weekProgress.closest("button")).toBeNull();
  expect(
    document.getElementById(weekTrigger.getAttribute("aria-describedby")!)
      ?.textContent,
  ).toContain("0 of 3 practice days");
  expect(weekTrigger.getAttribute("aria-expanded")).toBe("false");
  await click(
    container.querySelector<HTMLButtonElement>(
      'button[aria-label="0 practice xp. View details"]',
    )!,
  );
  expect(container.querySelector("dialog")?.textContent).toContain(
    "separate from course progress",
  );
  expect(
    container.querySelector('dialog a[href="/leaderboard"]'),
  ).not.toBeNull();
  await click(
    container.querySelector<HTMLButtonElement>(
      'button[aria-label="Close reward details"]',
    )!,
  );
  await click(button("View your week"));
  expect(weekTrigger.getAttribute("aria-expanded")).toBe("true");
  expect(weekTrigger.getAttribute("aria-controls")).toBe(
    container.querySelector("dialog")?.id,
  );
  expect(container.querySelector("dialog")?.textContent).toContain(
    "not a consecutive-day streak",
  );
  expect(container.querySelector("dialog")?.textContent).toContain(
    "Asia/Kolkata",
  );
  await act(async () => root.unmount());
  unmounted = true;
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(api.updateProfile).not.toHaveBeenCalled();
});
