// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewInvitationAcceptance } from "./review-invitation-acceptance";

const routerMock = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

const token = "invite-token-" + "b".repeat(48);
let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  routerMock.push.mockClear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  (
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true;
  window.history.replaceState(
    null,
    "",
    `/sales-xray/review/invite#token=${encodeURIComponent(token)}`,
  );
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Review invitation not found." }),
          { status: 401 },
        ),
      ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

describe("review invitation acceptance page", () => {
  it("clears the bearer fragment and requires normal sign-in before source access", async () => {
    await act(async () => {
      root.render(
        <StrictMode>
          <ReviewInvitationAcceptance />
        </StrictMode>,
      );
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(window.location.hash).toBe("");
    expect(container.textContent).toContain(
      "Sign in with the email address that received this invitation",
    );
    expect(container.textContent).not.toContain("Listen to the exact moments");
    expect(
      container.querySelector('a[href^="/login#review_invitation="]'),
    ).not.toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    const google = container.querySelector('a[target="_blank"]');
    expect(google?.getAttribute("href")).toBe("/login");
    expect(google?.getAttribute("rel")).toContain("noreferrer");
    const retry = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("I've signed in"),
    );
    expect(retry).toBeDefined();
    await act(async () => {
      retry?.click();
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(
      JSON.parse(vi.mocked(fetch).mock.calls[1][1]?.body as string).token,
    ).toBe(token);
  });

  it("retries a temporary failure with the in-memory token and preserves router state", async () => {
    window.history.replaceState(
      { __NA: true, tree: "fixture" },
      "",
      window.location.href,
    );
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Try again later" }), {
        status: 503,
      }),
    );
    await act(async () =>
      root.render(
        <StrictMode>
          <ReviewInvitationAcceptance />
        </StrictMode>,
      ),
    );
    expect(window.location.hash).toBe("");
    expect(window.history.state).toEqual({ __NA: true, tree: "fixture" });
    const retry = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Retry invitation",
    );
    expect(retry).toBeDefined();
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Sign in" }), { status: 401 }),
    );
    await act(async () => retry!.click());
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(
      JSON.parse(String(vi.mocked(fetch).mock.calls[1]![1]?.body)).token,
    ).toBe(token);
    expect(container.textContent).toContain("Sign in with the email address");
    expect(routerMock.push).not.toHaveBeenCalled();
  });

  it("keeps unavailable invitations generic without offering a transient retry", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing" }), { status: 404 }),
    );
    await act(async () => root.render(<ReviewInvitationAcceptance />));
    expect(container.textContent).toContain("unavailable, expired, revoked");
    expect(
      [...container.querySelectorAll("button")].some(
        (button) => button.textContent === "Retry invitation",
      ),
    ).toBe(false);
    expect(routerMock.push).not.toHaveBeenCalled();
  });
});
