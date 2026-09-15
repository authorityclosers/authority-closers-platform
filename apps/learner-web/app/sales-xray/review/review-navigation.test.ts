// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  registerReviewNavigationGuard,
  requestReviewNavigation,
  REVIEW_NAVIGATION_CONFIRMATION,
} from "./review-navigation";

describe("review navigation guard", () => {
  let cleanup: (() => void) | undefined;

  beforeEach(() => {
    window.history.replaceState(
      { route: "assigned-review" },
      "",
      "/sales-xray/review/assignment-1",
    );
  });

  afterEach(() => {
    cleanup?.();
    cleanup = undefined;
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });

  it("cancels same-origin link navigation and keeps the dirty route mounted", () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    cleanup = registerReviewNavigationGuard(true);
    const link = document.createElement("a");
    link.href = "/home";
    document.body.append(link);

    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
    });
    expect(link.dispatchEvent(event)).toBe(false);
    expect(window.location.pathname).toBe("/sales-xray/review/assignment-1");
    expect(confirm).toHaveBeenCalledOnce();
    expect(confirm).toHaveBeenCalledWith(REVIEW_NAVIGATION_CONFIRMATION);
  });

  it("restores the guarded URL when browser back is canceled", () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    cleanup = registerReviewNavigationGuard(true);
    window.history.pushState({ route: "home" }, "", "/home");

    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(window.location.pathname).toBe("/sales-xray/review/assignment-1");
    expect(confirm).toHaveBeenCalledOnce();
  });

  it("blocks imperative router navigation when the user stays", () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    cleanup = registerReviewNavigationGuard(true);
    const navigate = vi.fn();

    expect(requestReviewNavigation(navigate)).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledOnce();
  });

  it("runs accepted navigation once without a duplicate same-task dialog", () => {
    vi.useFakeTimers();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    cleanup = registerReviewNavigationGuard(true);
    const firstNavigate = vi.fn();
    const secondNavigate = vi.fn();

    expect(requestReviewNavigation(firstNavigate)).toBe(true);
    expect(requestReviewNavigation(secondNavigate)).toBe(true);
    expect(firstNavigate).toHaveBeenCalledOnce();
    expect(secondNavigate).toHaveBeenCalledOnce();
    expect(confirm).toHaveBeenCalledOnce();

    vi.advanceTimersByTime(1);
    expect(requestReviewNavigation(vi.fn())).toBe(true);
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("does not install a guard while the review is clean", () => {
    const confirm = vi.fn();
    vi.stubGlobal("confirm", confirm);
    const navigate = vi.fn();
    cleanup = registerReviewNavigationGuard(false);

    expect(requestReviewNavigation(navigate)).toBe(true);
    expect(navigate).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
  });
});
