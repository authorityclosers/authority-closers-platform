import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import type { LeadRow } from "../leads/leads-client";
import { RecentlyCalled, recentLine } from "./recently-called";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const row = (n: number, extra: Partial<LeadRow> = {}) =>
  ({
    lead_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    revision: 1,
    name: `fictional lead ${n}`,
    company: null,
    city: null,
    language: null,
    interest: null,
    phone_last4: "3210",
    stage: "interested",
    stage_label: "Interested",
    source: "manual",
    source_label: "Added by hand",
    owner_person_id: "me",
    owner_name: null,
    why: "Later",
    why_kind: "later",
    next_action_at: null,
    created_at: "2026-10-20T05:30:00Z",
    attempts: 1,
    calls: 1,
    last_result: "interested",
    last_result_label: "Interested",
    test_data: false,
    last_contact_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    ...extra,
  }) as LeadRow;

let root: Root | null = null;
let mounted: HTMLDivElement | null = null;
const asked: string[] = [];

async function mount(leads: LeadRow[]) {
  asked.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      asked.push(String(input));
      return new Response(
        JSON.stringify({ leads, total: leads.length, next_offset: null }),
      );
    }),
  );
  const box = document.createElement("div");
  document.body.append(box);
  const made = createRoot(box);
  mounted = box;
  root = made;
  await act(async () => made.render(<RecentlyCalled />));
  await act(async () => Promise.resolve());
  return box;
}

afterEach(async () => {
  const made = root;
  if (made) await act(async () => made.unmount());
  mounted?.remove();
  root = null;
  mounted = null;
  vi.unstubAllGlobals();
});

it("lists the seller's last calls this week, newest first, with how each went", async () => {
  const host = await mount([
    row(1),
    row(2, { phone_last4: null }),
    ...[3, 4, 5, 6].map((n) => row(n)),
  ]);
  expect(asked[0]).toContain("scope=mine");
  expect(asked[0]).toContain("contact=week");
  expect(asked[0]).toContain("sort=last_contact");
  expect(asked[0]).toContain("order=desc");
  expect(host.querySelector("h2")?.textContent).toBe("Recently called");
  const names = Array.from(
    host.querySelectorAll("li strong"),
    (item) => item.textContent,
  );
  expect(names).toEqual([
    "Fictional Lead 1",
    "Fictional Lead 2",
    "Fictional Lead 3",
    "Fictional Lead 4",
    "Fictional Lead 5",
  ]);
  expect(host.textContent).toContain("Interested · ");
  // One-tap call back, where there is a number.
  expect(
    host.querySelector('a[aria-label="Call Fictional Lead 1"]'),
  ).not.toBeNull();
  expect(
    host.querySelector('a[aria-label="Call Fictional Lead 2"]'),
  ).toBeNull();
});

it("shows nothing until there is a call to show", async () => {
  const host = await mount([]);
  expect(host.textContent).toBe("");
});

it("says how it went before when", () => {
  expect(recentLine(row(1, { last_contact_at: null }))).toBe("Interested");
  expect(
    recentLine(row(1, { last_result_label: null, stage_label: "Call back" })),
  ).toMatch(/^Call back · /);
});
