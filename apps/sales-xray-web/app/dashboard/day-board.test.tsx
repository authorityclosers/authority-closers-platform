import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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

import { DayTiles, MyStages } from "./day-board";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, #18 (26 Oct 2026): Home is a day dashboard, not the Leads list.
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("counts the day in four tiles, each opening its Leads", async () => {
  await act(async () =>
    root.render(
      <DayTiles counts={{ overdue: 2, dueToday: 5, fresh: 3, calls: 7 }} />,
    ),
  );
  const tiles = [...host.querySelectorAll("a")].map((link) => ({
    text: link.textContent,
    href: link.getAttribute("href"),
    bad: link.getAttribute("data-tone") === "bad",
  }));
  expect(tiles).toEqual([
    { text: "2Overdue", href: "/leads?tab=all&due=late", bad: true },
    { text: "5Due today", href: "/leads?tab=all&due=today", bad: false },
    { text: "3New leads", href: "/leads?tab=all&stage=new", bad: false },
    { text: "7Calls today", href: "/analysis/calls", bad: false },
  ]);
  // They prefetch nothing on their own (v0.96 release check).
  expect(
    [...host.querySelectorAll("a")].every(
      (link) => link.dataset.prefetch === "false",
    ),
  ).toBe(true);
});

it("lists the seller's open leads by the organisation's stages", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.includes("/journey")
        ? {
            version: 1,
            industry: null,
            savedAt: null,
            savedBy: null,
            canEdit: false,
            kinds: {},
            meanings: {},
            stages: [
              {
                key: "new",
                label: "New enquiry",
                kind: "new",
                archived: false,
              },
              {
                key: "visit",
                label: "Site visit",
                kind: "interested",
                archived: false,
              },
              { key: "old", label: "Old stage", kind: "new", archived: true },
            ],
          }
        : url.includes("/leads?")
          ? {
              leads: [],
              total: 0,
              next_offset: null,
              stage_counts: { new: 4, visit: 1 },
            }
          : {};
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  await act(async () => root.render(<MyStages />));
  await act(async () => {
    for (let n = 0; n < 8; n++) await Promise.resolve();
  });
  const rows = [...host.querySelectorAll("li a")].map((link) => ({
    text: link.textContent,
    href: link.getAttribute("href"),
  }));
  expect(rows).toEqual([
    { text: "New enquiry4", href: "/leads?tab=all&stage=new" },
    { text: "Site visit1", href: "/leads?tab=all&stage=visit" },
  ]);
});
