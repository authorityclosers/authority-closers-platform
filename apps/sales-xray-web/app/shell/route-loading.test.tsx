import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

const place = vi.hoisted(() => ({ pathname: "/leads" }));

vi.mock("next/navigation", () => ({
  usePathname: () => place.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import Loading from "../loading";
import { routeLoadingKind } from "./route-loading";

it("loads every place with its own outline, never New analysis", () => {
  expect(routeLoadingKind("/dashboard")).toBe("dashboard");
  expect(routeLoadingKind("/leads")).toBe("leads");
  expect(routeLoadingKind("/leads/")).toBe("leads");
  expect(routeLoadingKind("/chats")).toBe("chats");
  expect(routeLoadingKind("/analysis/calls")).toBe("calls");
  expect(routeLoadingKind("/analysis")).toBe("calls");
  expect(routeLoadingKind("/calls")).toBe("calls");
  expect(
    routeLoadingKind("/analysis/calls/0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10"),
  ).toBe("call");
  expect(routeLoadingKind("/prospects")).toBe("prospects");
  expect(
    routeLoadingKind("/prospects/0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10"),
  ).toBe("prospect");
  expect(routeLoadingKind("/coaching")).toBe("coaching");
  expect(routeLoadingKind("/organisation")).toBe("organisation");
  expect(routeLoadingKind("/organisation/insights")).toBe("insights");
  expect(routeLoadingKind("/organisation/invites")).toBe("invites");
  expect(
    routeLoadingKind(
      "/organisation/people/0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10",
    ),
  ).toBe("person");
  expect(routeLoadingKind("/settings")).toBe("settings");
  expect(routeLoadingKind("/settings/team")).toBe("settings");
  expect(routeLoadingKind("/account")).toBe("account");
  expect(routeLoadingKind("/review")).toBe("review");
  // New analysis keeps its own outline.
  expect(routeLoadingKind("/analysis/new")).toBe("new");
  expect(routeLoadingKind("/")).toBe("new");
});

it("keeps the app frame off pages that don't have it", () => {
  expect(routeLoadingKind("/login")).toBe("plain");
  expect(routeLoadingKind("/privacy")).toBe("plain");
  expect(routeLoadingKind("/plans")).toBe("plain");
  expect(routeLoadingKind(null)).toBe("new");
});

it("draws the opened page's outline at the root while it loads", () => {
  place.pathname = "/analysis/calls";
  const calls = renderToStaticMarkup(<Loading />);
  expect(calls).not.toContain("analyse your next call");
  expect(calls).not.toContain("Drop your call recording here");

  place.pathname = "/analysis/new";
  expect(renderToStaticMarkup(<Loading />)).toContain(
    "Drop your call recording here",
  );

  place.pathname = "/login";
  const plain = renderToStaticMarkup(<Loading />);
  expect(plain).toContain('aria-busy="true"');
  expect(plain).not.toContain("data-lightbox-shell");
});
