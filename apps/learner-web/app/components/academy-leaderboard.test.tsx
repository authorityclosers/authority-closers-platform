// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CommunityLeaderboardResponse,
  type LearnerApi,
} from "../lib/learner-api";
import {
  AcademyLeaderboard,
  ACADEMY_LEADERBOARD_REQUEST_TIMEOUT_MS,
} from "./academy-leaderboard";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const board = (items: CommunityLeaderboardResponse["items"] = []) => ({
  policy: {
    version: "all_time_practice_xp_v1" as const,
    label: "All-time practice XP" as const,
    period: "all_time" as const,
    ranking: "competition" as const,
    scope: "academy" as const,
  },
  items,
  next_cursor: null,
});

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function render(api: Pick<LearnerApi, "communityLeaderboard">) {
  await act(async () => {
    root.render(<AcademyLeaderboard api={api} />);
  });
  await flush();
}

describe("AcademyLeaderboard", () => {
  it("uses only the authenticated leaderboard read and preserves server ties/current row", async () => {
    const communityLeaderboard = vi.fn(async () =>
      board([
        { rank: 1, username: "alex", xp_total: 90, is_current_learner: true },
        { rank: 1, username: "sam", xp_total: 90, is_current_learner: false },
      ]),
    );
    await render({ communityLeaderboard });

    expect(communityLeaderboard).toHaveBeenCalledTimes(1);
    expect(communityLeaderboard).toHaveBeenCalledWith(
      25,
      undefined,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(container.textContent).toContain("All-time practice XP");
    expect(container.textContent).toContain("@alexYou");
    expect(container.textContent).toContain("@sam");
    expect(
      [...container.querySelectorAll("tbody td:first-child")].map(
        (cell) => cell.textContent,
      ),
    ).toEqual(["1", "1"]);
    expect(container.querySelectorAll("[role=tab]")).toHaveLength(0);
    expect(container.querySelector('a[href="/profile"]')).not.toBeNull();
    expect(container.querySelector('a[href="/settings"]')).not.toBeNull();
  });

  it("renders an honest empty state with Start practice and no invented rows", async () => {
    const communityLeaderboard = vi.fn(async () => board());
    await render({ communityLeaderboard });

    expect(container.textContent).toContain("No leaderboard entries yet");
    expect(container.textContent).toContain(
      "No opted-in learners with confirmed practice XP are listed yet.",
    );
    expect(container.querySelector("tbody")).toBeNull();
    expect(
      container.querySelector('a[href="/practice"]')?.textContent,
    ).toContain("Start practice");
    expect(container.textContent).not.toContain("Alex");
    expect(container.textContent).not.toContain("Sam");
  });

  it("offers sign-in recovery for 401 without calling profile or claim APIs", async () => {
    const communityLeaderboard = vi.fn(async () => {
      throw new ApiError(401, "expired");
    });
    await render({ communityLeaderboard });

    expect(container.textContent).toContain(
      "Sign in to view your academy leaderboard",
    );
    expect(container.textContent).toContain("Your session has expired");
    expect(
      container.querySelector('a[href="/session-expired"]')?.textContent,
    ).toBe("Sign in again");
    expect(container.querySelector("button")).toBeNull();
  });

  it("retries a transient read and renders the recovered board", async () => {
    const communityLeaderboard = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(
        board([
          { rank: 1, username: "alex", xp_total: 30, is_current_learner: true },
        ]),
      );
    await render({ communityLeaderboard });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")?.click();
    });
    await flush();

    expect(communityLeaderboard).toHaveBeenCalledTimes(2);
    expect(container.querySelector("tbody")).not.toBeNull();
    expect(container.textContent).toContain("@alex");
  });

  it("loads the next server page without changing ranks or making a write", async () => {
    const first = {
      ...board([
        { rank: 1, username: "alex", xp_total: 90, is_current_learner: true },
      ]),
      next_cursor: "cursor-1",
    };
    const second = board([
      { rank: 2, username: "sam", xp_total: 40, is_current_learner: false },
    ]);
    const communityLeaderboard = vi
      .fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    await render({ communityLeaderboard });
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")?.click();
    });
    await flush();

    expect(communityLeaderboard).toHaveBeenNthCalledWith(
      2,
      25,
      "cursor-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(container.textContent).toContain("@sam");
    expect(container.textContent).not.toContain("Practice tabs");
  });

  it("aborts a pending read on unmount and ignores its late response", async () => {
    let signal: AbortSignal | undefined;
    let resolve!: (value: CommunityLeaderboardResponse) => void;
    const pending = new Promise<CommunityLeaderboardResponse>((done) => {
      resolve = done;
    });
    const communityLeaderboard = vi.fn((_limit, _cursor, options) => {
      signal = options?.signal;
      return pending;
    });
    await act(async () => {
      root.render(<AcademyLeaderboard api={{ communityLeaderboard }} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => root.unmount());
    expect(signal?.aborted).toBe(true);
    await act(async () =>
      resolve(
        board([
          { rank: 1, username: "late", xp_total: 20, is_current_learner: true },
        ]),
      ),
    );
    expect(container.textContent).not.toContain("@late");
  });

  it("turns a hung read into a retryable state", async () => {
    vi.useFakeTimers();
    const communityLeaderboard = vi.fn(
      () => new Promise<CommunityLeaderboardResponse>(() => {}),
    );
    await act(async () => {
      root.render(<AcademyLeaderboard api={{ communityLeaderboard }} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () =>
      vi.advanceTimersByTimeAsync(ACADEMY_LEADERBOARD_REQUEST_TIMEOUT_MS),
    );
    expect(container.textContent).toContain("took too long to load");
    expect(container.textContent).toContain("Retry");
  });
});
