// @vitest-environment happy-dom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CommunityLeaderboardResponse,
  type CommunityProfileResponse,
  type LearnerApi,
} from "../lib/learner-api";
import {
  CommunityIdentityCard,
  COMMUNITY_REQUEST_TIMEOUT_MS,
} from "./community-identity-card";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const unclaimed: CommunityProfileResponse = {
  username: null,
  leaderboard_opted_in: false,
  revision: 0,
  leaderboard_policy: {
    version: "all_time_practice_xp_v1",
    period: "all_time",
    measure: "confirmed_practice_xp",
    ranking: "competition",
    privacy: "academy_opt_in",
  },
};

const leaderboard: CommunityLeaderboardResponse = {
  policy: {
    version: "all_time_practice_xp_v1",
    label: "All-time practice XP",
    period: "all_time",
    ranking: "competition",
    scope: "academy",
  },
  items: [
    { rank: 1, username: "alex", xp_total: 90, is_current_learner: true },
    { rank: 1, username: "sam", xp_total: 90, is_current_learner: false },
  ],
  next_cursor: null,
};

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  Object.defineProperty(window.navigator, "onLine", {
    configurable: true,
    value: true,
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function render(api: LearnerApi) {
  await act(async () => {
    root.render(<CommunityIdentityCard api={api} />);
    await Promise.resolve();
    await Promise.resolve();
  });
}

function change(input: HTMLInputElement, value: string | boolean) {
  const property = typeof value === "boolean" ? "checked" : "value";
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    property,
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("academy public identity", () => {
  it("unlocks saved participation while its optional leaderboard refresh is pending", async () => {
    const pending = deferred<CommunityLeaderboardResponse>();
    const claimed = { ...unclaimed, username: "alex", revision: 1 };
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard: vi
        .fn()
        .mockResolvedValueOnce({ ...leaderboard, items: [] })
        .mockReturnValueOnce(pending.promise),
      setLeaderboardOptIn: vi.fn(async () => ({
        ...claimed,
        leaderboard_opted_in: true,
        revision: 2,
      })),
    } as unknown as LearnerApi;
    await render(api);
    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    await act(async () =>
      container.querySelector<HTMLButtonElement>("button")!.click(),
    );
    expect(container.textContent).toContain(
      "You joined the academy leaderboard",
    );
    expect(checkbox.disabled).toBe(false);
    expect(container.textContent).not.toContain("Saving…");
    await act(async () => pending.resolve(leaderboard));
  });

  it("does not let leaderboard retry abort an in-flight participation save", async () => {
    const pending = deferred<CommunityProfileResponse>();
    const claimed = { ...unclaimed, username: "alex", revision: 1 };
    let mutationSignal: AbortSignal | undefined;
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard: vi
        .fn()
        .mockRejectedValueOnce(new TypeError("ranking unavailable"))
        .mockResolvedValue({ ...leaderboard, items: [] }),
      setLeaderboardOptIn: vi.fn(
        (_optedIn: boolean, _revision: number, signal?: AbortSignal) => {
          mutationSignal = signal;
          return pending.promise;
        },
      ),
    } as unknown as LearnerApi;
    await render(api);
    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Save participation",
    )!;
    await act(async () => save.click());

    const retry = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Retry leaderboard",
    )!;
    expect(retry.disabled).toBe(true);
    await act(async () => retry.click());
    expect(api.communityProfile).toHaveBeenCalledTimes(1);
    expect(mutationSignal?.aborted).toBe(false);

    await act(async () =>
      pending.resolve({
        ...claimed,
        leaderboard_opted_in: true,
        revision: 2,
      }),
    );
    expect(container.textContent).toContain(
      "You joined the academy leaderboard",
    );
  });

  it("times out a hung identity read and ignores its late result", async () => {
    vi.useFakeTimers();
    const pending = deferred<CommunityProfileResponse>();
    let signal: AbortSignal | undefined;
    const api = {
      communityProfile: vi.fn((options) => {
        signal = options.signal;
        return pending.promise;
      }),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
    } as unknown as LearnerApi;
    await render(api);
    await act(async () =>
      vi.advanceTimersByTimeAsync(COMMUNITY_REQUEST_TIMEOUT_MS),
    );
    expect(signal?.aborted).toBe(true);
    expect(container.textContent).not.toContain("Loading community identity");
    expect(container.textContent).toContain("Retry");
    await act(async () =>
      pending.resolve({ ...unclaimed, username: "late_name", revision: 1 }),
    );
    expect(container.textContent).not.toContain("@late_name");
  });

  it("requires reconciliation after a timed-out claim instead of promising it failed", async () => {
    vi.useFakeTimers();
    const pending = deferred<CommunityProfileResponse>();
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      claimUsername: vi.fn(() => pending.promise),
    } as unknown as LearnerApi;
    await render(api);
    const input =
      container.querySelector<HTMLInputElement>("#academy-username")!;
    await act(async () => change(input, "alex"));
    await act(async () =>
      container
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    await act(async () =>
      vi.advanceTimersByTimeAsync(COMMUNITY_REQUEST_TIMEOUT_MS),
    );
    expect(container.textContent).toContain(
      "Refresh to check the latest saved state",
    );
    expect(input.disabled).toBe(true);
    expect(input.value).toBe("alex");
    await act(async () =>
      pending.resolve({ ...unclaimed, username: "alex", revision: 1 }),
    );
    expect(container.textContent).not.toContain("Username @alex claimed");
  });

  it("does not restore an opted-out learner from an older leaderboard read", async () => {
    const oldBoard = deferred<CommunityLeaderboardResponse>();
    const claimed = {
      ...unclaimed,
      username: "alex",
      revision: 1,
      leaderboard_opted_in: true,
    };
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard: vi
        .fn()
        .mockReturnValueOnce(oldBoard.promise)
        .mockResolvedValue({ ...leaderboard, items: [] }),
      setLeaderboardOptIn: vi.fn(async () => ({
        ...claimed,
        leaderboard_opted_in: false,
        revision: 2,
      })),
    } as unknown as LearnerApi;
    await render(api);
    await act(async () =>
      container
        .querySelector<HTMLInputElement>('input[type="checkbox"]')!
        .click(),
    );
    await act(async () => {
      const save = [
        ...container.querySelectorAll<HTMLButtonElement>("button"),
      ].find((button) => button.textContent === "Save participation");
      save!.click();
    });
    expect(container.textContent).toContain("You left the academy leaderboard");
    await act(async () => oldBoard.resolve(leaderboard));
    expect(container.querySelectorAll("tbody tr")).toHaveLength(0);
    expect(
      container.querySelector<HTMLInputElement>('input[type="checkbox"]')
        ?.checked,
    ).toBe(false);
  });

  it("hides the previous identity while a replacement context is loading", async () => {
    const replacement = deferred<CommunityProfileResponse>();
    const oldApi = {
      communityProfile: vi.fn(async () => ({
        ...unclaimed,
        username: "alex",
        revision: 1,
      })),
      communityLeaderboard: vi.fn(async () => leaderboard),
    } as unknown as LearnerApi;
    await render(oldApi);
    expect(container.textContent).toContain("@alex");
    const newApi = {
      communityProfile: vi.fn(() => replacement.promise),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
    } as unknown as LearnerApi;
    await render(newApi);
    expect(container.textContent).not.toContain("@alex");
    expect(container.querySelector('input[type="checkbox"]')).toBeNull();
    await act(async () => replacement.resolve(unclaimed));
    expect(container.querySelector("#academy-username")).not.toBeNull();
  });

  it("renders and saves a username before the optional leaderboard settles", async () => {
    const pending = deferred<CommunityLeaderboardResponse>();
    const claimUsername = vi.fn(async () => ({
      ...unclaimed,
      username: "alex",
      revision: 1,
    }));
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(() => pending.promise),
      claimUsername,
    } as unknown as LearnerApi;
    await render(api);

    const input =
      container.querySelector<HTMLInputElement>("#academy-username");
    expect(input).not.toBeNull();
    expect(container.textContent).not.toContain("Loading community identity");
    await act(async () => change(input!, "alex"));
    await act(async () => {
      container
        .querySelector("form")
        ?.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
    });
    expect(container.textContent).toContain("Username @alex claimed.");
    await act(async () => pending.resolve(leaderboard));
    expect(container.textContent).toContain("Username @alex claimed.");
    expect(container.querySelector("#academy-username")).toBeNull();
  });

  it("claims a username without presenting email as public identity", async () => {
    const claimUsername = vi.fn(async () => ({
      ...unclaimed,
      username: "learner_7",
      revision: 1,
    }));
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      claimUsername,
    } as unknown as LearnerApi;
    await render(api);

    expect(container.textContent).toContain("not your sign-in ID");
    expect(container.textContent).not.toContain("@example");
    const input =
      container.querySelector<HTMLInputElement>("#academy-username");
    expect(input).not.toBeNull();
    await act(async () => change(input!, "Learner_7"));
    await act(async () => {
      container
        .querySelector("form")
        ?.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
      await Promise.resolve();
    });

    expect(claimUsername).toHaveBeenCalledWith(
      "Learner_7",
      expect.any(AbortSignal),
    );
    expect(container.textContent).toContain("@learner_7");
    expect(container.textContent).toContain("fixed in this release");
  });

  it("requires a separate saved opt-in and displays competition ties", async () => {
    const claimed = { ...unclaimed, username: "alex", revision: 1 };
    const setLeaderboardOptIn = vi.fn(async () => ({
      ...claimed,
      leaderboard_opted_in: true,
      revision: 2,
    }));
    const communityLeaderboard = vi.fn(async () => leaderboard);
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard,
      setLeaderboardOptIn,
    } as unknown as LearnerApi;
    await render(api);

    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    );
    expect(checkbox?.checked).toBe(false);
    expect(container.textContent).toContain(
      "You're not on the academy leaderboard.",
    );
    await act(async () => checkbox!.click());
    expect(setLeaderboardOptIn).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      "You're not on the academy leaderboard.",
    );
    await act(async () => {
      container
        .querySelectorAll<HTMLButtonElement>("button")
        .item(0)
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(setLeaderboardOptIn).toHaveBeenCalledWith(
      true,
      1,
      expect.any(AbortSignal),
    );
    expect(container.textContent).toContain(
      "You're on the academy leaderboard.",
    );
    expect(container.textContent).not.toContain("Participation is off");
    expect(container.textContent).toContain("All-time practice XP");
    expect(
      [...container.querySelectorAll("tbody th")].map(
        (cell) => cell.textContent,
      ),
    ).toEqual(["@alex (you)", "@sam"]);
    const ranks = [...container.querySelectorAll("tbody td:first-child")].map(
      (cell) => cell.textContent,
    );
    expect(ranks).toEqual(["1", "1"]);
    expect(container.textContent).toContain(
      "never changes course access, progress, or scoring",
    );
  });

  it("focuses a recoverable alert and preserves the username after a conflict", async () => {
    const claimUsername = vi.fn(async () => {
      throw new ApiError(409, "conflict", { code: "username_unavailable" });
    });
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      claimUsername,
    } as unknown as LearnerApi;
    await render(api);
    const input =
      container.querySelector<HTMLInputElement>("#academy-username")!;
    await act(async () => change(input, "alex"));
    await act(async () => {
      container
        .querySelector("form")
        ?.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
      await Promise.resolve();
    });

    const alert = container.querySelector<HTMLElement>('[role="alert"]');
    expect(alert?.textContent).toContain(
      "That username is already taken. Try another name.",
    );
    expect(document.activeElement).toBe(alert);
    expect(input.value).toBe("alex");
  });

  it("keeps opt-in mutation disabled offline", async () => {
    Object.defineProperty(window.navigator, "onLine", {
      configurable: true,
      value: false,
    });
    const claimed = { ...unclaimed, username: "alex", revision: 1 };
    const setLeaderboardOptIn = vi.fn();
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      setLeaderboardOptIn,
    } as unknown as LearnerApi;
    await render(api);
    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    await act(async () => {
      container
        .querySelectorAll<HTMLButtonElement>("button")
        .item(0)
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(setLeaderboardOptIn).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      "Reconnect before changing leaderboard participation",
    );
  });

  it("keeps the saved opt-in when the follow-up leaderboard refresh fails", async () => {
    const claimed = { ...unclaimed, username: "alex", revision: 1 };
    const communityLeaderboard = vi
      .fn()
      .mockResolvedValueOnce({ ...leaderboard, items: [] })
      .mockRejectedValueOnce(new TypeError("network unavailable"));
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard,
      setLeaderboardOptIn: vi.fn(async () => ({
        ...claimed,
        leaderboard_opted_in: true,
        revision: 2,
      })),
    } as unknown as LearnerApi;
    await render(api);
    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(checkbox.checked).toBe(true);
    expect(container.textContent).toContain("Participation was saved");
    expect(container.textContent).toContain("leaderboard could not refresh");
  });

  it("keeps username claiming available when the optional leaderboard read fails", async () => {
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => {
        throw new TypeError("network unavailable");
      }),
    } as unknown as LearnerApi;
    await render(api);

    expect(container.querySelector("#academy-username")).not.toBeNull();
    expect(container.textContent).toContain("leaderboard could not load");
    expect(container.textContent).toContain(
      "You can still manage your academy identity",
    );
    expect(container.textContent).toContain("Retry leaderboard");
  });

  it("allows only one username claim while a mutation is in flight", async () => {
    const pending = deferred<CommunityProfileResponse>();
    const claimUsername = vi.fn(() => pending.promise);
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      claimUsername,
    } as unknown as LearnerApi;
    await render(api);
    const input =
      container.querySelector<HTMLInputElement>("#academy-username")!;
    const form = container.querySelector("form")!;
    await act(async () => change(input, "alex"));
    await act(async () => {
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      await Promise.resolve();
    });

    expect(claimUsername).toHaveBeenCalledTimes(1);
    await act(async () => {
      pending.resolve({ ...unclaimed, username: "alex", revision: 1 });
      await pending.promise;
    });
    expect(container.textContent).toContain("@alex");
  });

  it("aborts and ignores an old mutation after its identity context is replaced", async () => {
    const pending = deferred<CommunityProfileResponse>();
    let oldSignal: AbortSignal | undefined;
    const claimUsername = vi.fn((_username: string, signal?: AbortSignal) => {
      oldSignal = signal;
      return pending.promise;
    });
    const firstApi = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      claimUsername,
    } as unknown as LearnerApi;
    await render(firstApi);
    const input =
      container.querySelector<HTMLInputElement>("#academy-username")!;
    await act(async () => change(input, "stale_name"));
    await act(async () => {
      container
        .querySelector("form")
        ?.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
      await Promise.resolve();
    });
    const replacement = { ...unclaimed, username: "current_name", revision: 4 };
    const secondApi = {
      communityProfile: vi.fn(async () => replacement),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
    } as unknown as LearnerApi;
    await act(async () => {
      root.render(<CommunityIdentityCard api={secondApi} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(oldSignal?.aborted).toBe(true);

    await act(async () => {
      pending.resolve({ ...unclaimed, username: "stale_name", revision: 1 });
      await pending.promise;
      await Promise.resolve();
    });
    expect(container.textContent).toContain("@current_name");
    expect(container.textContent).not.toContain("@stale_name");
  });

  it("offers sign-in recovery when the saved-participation refresh expires", async () => {
    const claimed = { ...unclaimed, username: "alex", revision: 1 };
    const communityLeaderboard = vi
      .fn()
      .mockResolvedValueOnce({ ...leaderboard, items: [] })
      .mockRejectedValueOnce(new ApiError(401, "expired"));
    const api = {
      communityProfile: vi.fn(async () => claimed),
      communityLeaderboard,
      setLeaderboardOptIn: vi.fn(async () => ({
        ...claimed,
        leaderboard_opted_in: true,
        revision: 2,
      })),
    } as unknown as LearnerApi;
    await render(api);
    const checkbox = container.querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    )!;
    await act(async () => checkbox.click());
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(checkbox.checked).toBe(true);
    expect(
      container.querySelector<HTMLAnchorElement>('a[href*="session-expired"]')
        ?.textContent,
    ).toBe("Sign in again");
  });

  it("offers normal sign-in recovery when identity expires during a claim", async () => {
    const api = {
      communityProfile: vi.fn(async () => unclaimed),
      communityLeaderboard: vi.fn(async () => ({ ...leaderboard, items: [] })),
      claimUsername: vi.fn(async () => {
        throw new ApiError(401, "expired");
      }),
    } as unknown as LearnerApi;
    await render(api);
    const input =
      container.querySelector<HTMLInputElement>("#academy-username")!;
    await act(async () => change(input, "alex"));
    await act(async () => {
      container
        .querySelector("form")
        ?.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
      await Promise.resolve();
    });

    const signIn = container.querySelector<HTMLAnchorElement>(
      'a[href*="session-expired"]',
    );
    expect(signIn?.textContent).toBe("Sign in again");
  });
});
