import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ path: "/organisation" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.path }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch,
    ...rest
  }: {
    href: string;
    children: ReactNode;
    prefetch?: boolean;
  }) => (
    <a href={href} data-prefetch={String(prefetch)} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("./review-client", () => ({ readBadge: vi.fn(async () => null) }));

import { publishReviewBadge, ReviewBarChip } from "./review-badge";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// The phone top bar's Review chip (owner, 26 Oct 2026: it squeezed the page
// title): its words live in one span a narrow screen hides, and the count in
// another drawn as a bubble on the icon.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  nav.path = "/organisation";
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const badge = (waiting: number) => ({
  reviewer: true,
  metrics: false,
  waiting,
  newest_at: null,
});

it("shows the count when reviews wait, and says so to screen readers", async () => {
  publishReviewBadge(badge(3));
  await act(async () => root.render(<ReviewBarChip live />));
  const chip = host.querySelector("a")!;
  expect(chip.getAttribute("href")).toBe("/review");
  expect(chip.getAttribute("aria-label")).toBe("Review, 3 waiting");
  expect(chip.textContent).toBe("3");
  expect(chip.querySelector("[class*='barChipCount']")).not.toBeNull();
});

it("says Review in its own span when nothing waits", async () => {
  publishReviewBadge(badge(0));
  await act(async () => root.render(<ReviewBarChip live />));
  const chip = host.querySelector("a")!;
  expect(chip.getAttribute("aria-label")).toBe("Review");
  expect(chip.querySelector("[class*='barChipText']")?.textContent).toBe(
    "Review",
  );
});

it("hides on Review itself, but not on pages whose address only starts so", async () => {
  publishReviewBadge(badge(2));
  nav.path = "/review/queue";
  await act(async () => root.render(<ReviewBarChip live />));
  expect(host.querySelector("a")).toBeNull();
  nav.path = "/review-fixture/hub";
  await act(async () => root.render(<ReviewBarChip live />));
  expect(host.querySelector("a")?.getAttribute("aria-label")).toBe(
    "Review, 2 waiting",
  );
});
