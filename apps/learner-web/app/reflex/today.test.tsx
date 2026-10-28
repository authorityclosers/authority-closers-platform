// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { TodayScreen } from "./today";
import {
  apiMock,
  assertCopy,
  engineMock,
  harness,
  learning,
  program,
  summary,
} from "./test-support";
import { ApiError } from "../lib/learner-api";
import HomePage from "../(app)/home/page";

describe("Reflex Today", () => {
  const h = harness();
  it("holds the final layout while loading", async () => {
    const api = apiMock();
    vi.mocked(api.me).mockReturnValue(new Promise(() => {}));
    await h.mount(<TodayScreen api={api} practiceEnabled />);
    expect(h.el.querySelector('[aria-label="Loading"]')).toBeTruthy();
    expect(h.el.textContent).toContain("Your courses");
    expect(h.el.textContent).toContain("Today’s practice");
    assertCopy(h.el);
  });
  it("shows a plain retry and can recover from an error", async () => {
    const api = apiMock();
    vi.mocked(api.me).mockRejectedValueOnce(
      new Error("private technical details"),
    );
    await h.mount(<TodayScreen api={api} />);
    expect(h.el.querySelector('[role="alert"]')?.textContent).toContain(
      "This couldn’t load",
    );
    expect(h.el.textContent).not.toContain("private technical details");
    await h.click(h.button("Try again"));
    expect(h.link("Continue")?.getAttribute("href")).toBe("/activity/next");
    assertCopy(h.el);
  });
  it("greets by first name, follows real progress and hides disabled practice", async () => {
    const api = apiMock();
    const practice = engineMock();
    await h.mount(<TodayScreen api={api} practiceApi={practice} />);
    expect(h.el.textContent).toMatch(/Good (morning|afternoon|evening), Mira/);
    expect(h.el.querySelector("time")?.textContent).toBeTruthy();
    expect(h.link("Continue")?.getAttribute("href")).toBe("/activity/next");
    expect(h.el.textContent).toContain("Reflect");
    expect(h.el.textContent).toContain("40% complete");
    expect(h.el.textContent).not.toContain("Today’s practice");
    expect(practice.progress).not.toHaveBeenCalled();
    expect(api.calendar).not.toHaveBeenCalled();
    expect(api.plans).not.toHaveBeenCalled();
    expect(api.upNext).not.toHaveBeenCalled();
    expect(api.learning).toHaveBeenCalledWith(
      program.id,
      { enrollmentId: "enrollment-a", programVersionId: "version-a" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    assertCopy(h.el);
  });
  it("shows practice days only when enabled", async () => {
    await h.mount(
      <TodayScreen
        api={apiMock()}
        practiceApi={engineMock()}
        practiceEnabled
      />,
    );
    expect(h.el.textContent).toContain("3 of 7 days practised");
    expect(h.link("Open practice")?.getAttribute("href")).toBe("/practice");
    assertCopy(h.el);
  });
  it("uses the most recently updated in-progress course, not a completed or older one", async () => {
    const api = apiMock([
      { ...summary, enrollment_id: "old", updated_at: "2026-10-01" },
      { ...summary, enrollment_id: "new", updated_at: "2026-10-27" },
      {
        ...summary,
        state: "completed",
        enrollment_id: "done",
        updated_at: "2026-10-28",
      },
    ]);
    vi.mocked(api.learning).mockImplementation(async (_id, scope) => {
      const item = learning();
      item.program_title = scope!.enrollmentId;
      return item;
    });
    await h.mount(<TodayScreen api={api} />);
    expect(h.el.querySelector("section")?.textContent).toContain("new");
    assertCopy(h.el);
  });
  it("reuses free enrolment and its consent recovery without reimplementing consent", async () => {
    const api = apiMock([]);
    vi.mocked(api.enrollFree).mockRejectedValue(
      new ApiError(409, "Consent required", {
        code: "learner_consent_update_required",
      }),
    );
    await h.mount(<TodayScreen api={api} />);
    expect(h.el.textContent).toContain("Start your first course");
    expect(h.el.textContent).toContain("Closers' Academy");
    await h.click(h.button("Start free course"));
    expect(api.enrollFree).toHaveBeenCalledWith("version-a");
    expect(h.el.querySelector('a[href*="/consent/renewal"]')).toBeTruthy();
    assertCopy(h.el);
  });
  it("keeps state simulation at the real route", async () => {
    const page = await HomePage({
      searchParams: Promise.resolve({ state: "loading" }),
    });
    await h.mount(page);
    expect(h.el.querySelector('[aria-label="Loading"]')).toBeTruthy();
    await h.mount(
      await HomePage({
        searchParams: Promise.resolve({ state: "error-retryable" }),
      }),
    );
    expect(h.link("Try again")?.getAttribute("href")).toBe("/home");
    assertCopy(h.el);
  });
  it("cancels a pending read on unmount", async () => {
    const api = apiMock();
    let signal: AbortSignal | undefined;
    vi.mocked(api.me).mockImplementation((options) => {
      signal = options?.signal as AbortSignal;
      return new Promise(() => {});
    });
    await h.mount(<TodayScreen api={api} />);
    await h.mount(null);
    expect(signal?.aborted).toBe(true);
  });
});
