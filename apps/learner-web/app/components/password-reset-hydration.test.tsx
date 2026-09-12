// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ResetPasswordPage from "../reset-password/page";
import * as bridge from "../lib/dev-api-proxy";
import * as apiModule from "../lib/learner-api";
import type { LearnerApi } from "../lib/learner-api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

describe("password reset token through page effect replay", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.spyOn(bridge, "isStagingAuthenticatedBridge").mockReturnValue(false);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    window.history.replaceState(null, "", "/");
    vi.restoreAllMocks();
  });

  it.each([false, true])(
    "retains the fragment in memory until explicit reset (StrictMode=%s)",
    async (strict) => {
      const token = "r".repeat(43);
      window.history.replaceState(null, "", "/reset-password#token=" + token);
      const resetPassword = vi.fn(async () => ({ reset: true }));
      vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
        resetPassword,
      } as unknown as LearnerApi);
      await act(async () =>
        root.render(
          strict ? (
            <StrictMode>{ResetPasswordPage()}</StrictMode>
          ) : (
            ResetPasswordPage()
          ),
        ),
      );

      expect(window.location.hash).toBe("");
      expect(window.location.search).toBe("");
      expect(resetPassword).not.toHaveBeenCalled();
      const password =
        container.querySelector<HTMLInputElement>("#reset-password");
      expect(password).not.toBeNull();
      password!.value = "synthetic-new-password";
      container.querySelector<HTMLInputElement>(
        "#reset-password-confirm",
      )!.value = "synthetic-new-password";
      expect(container.innerHTML).not.toContain(token);
      await act(async () =>
        container
          .querySelector("form")!
          .dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
          ),
      );
      expect(resetPassword).toHaveBeenCalledExactlyOnceWith(
        token,
        "synthetic-new-password",
      );
      expect(container.textContent).toContain("Password updated.");
      expect(container.querySelector('a[href="/login"]')).not.toBeNull();
    },
  );

  it("keeps a missing token unavailable under StrictMode without calling reset", async () => {
    window.history.replaceState(null, "", "/reset-password");
    const resetPassword = vi.fn();
    vi.spyOn(apiModule, "createLearnerApi").mockReturnValue({
      resetPassword,
    } as unknown as LearnerApi);
    await act(async () =>
      root.render(<StrictMode>{ResetPasswordPage()}</StrictMode>),
    );
    expect(container.textContent).toContain("missing its one-time token");
    expect(container.querySelector("form")).toBeNull();
    expect(resetPassword).not.toHaveBeenCalled();
  });
});
