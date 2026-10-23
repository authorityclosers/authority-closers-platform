import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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

import { SalesHome } from "./sales-home";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const outcomes = (scale: number) => ({
  calls: 10 * scale,
  connected: 4 * scale,
  leads_called: 8 * scale,
  interested: 2 * scale,
  won: 1 * scale,
  new_leads: 6 * scale,
  first_call_minutes: 7,
});

const row = (name: string, extra: Record<string, unknown> = {}) => ({
  lead_id: `00000000-0000-4000-8000-${String(name.length).padStart(12, "0")}`,
  revision: 1,
  name,
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-22T05:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...extra,
});

const desk = (queue: unknown[]) => ({
  me: { person_id: "p", name: "asha", role: "member", can_manage: false },
  numbers: {
    calls: 5,
    connected: 2,
    talk_seconds: 300,
    follow_ups_done: 1,
    new_assigned: 0,
  },
  counts: {
    open: 3,
    new: 1,
    follow_up_due: 0,
    not_connected: 0,
    later_today: 0,
    unassigned: null,
  },
  queue,
  call_mode: "phone",
  sandbox: false,
  generated_at: "2026-10-22T05:30:00Z",
});

let root: Root;
let host: HTMLDivElement;

function answer(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      const key = Object.keys(routes).find((route) =>
        route.endsWith("*")
          ? path.startsWith(route.slice(0, -1))
          : path === route,
      );
      return key
        ? new Response(JSON.stringify(routes[key]))
        : new Response("{}", { status: 404 });
    }),
  );
}

async function mount(manager: boolean) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<SalesHome manager={manager} />));
  await act(async () => Promise.resolve());
}

beforeEach(() => {
  window.history.replaceState(null, "", "/dashboard");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

// Owner, 22 Oct 2026: owners and admins first see how sales are going.
it("shows owners outcomes first, then sellers ranked and open leads by stage", async () => {
  answer({
    "/v1/lead-desk": desk([]),
    "/v1/lead-desk/reports/performance*": {
      days: 7,
      start: "2026-10-16",
      end: "2026-10-22",
      current: outcomes(2),
      previous: outcomes(1),
      sellers: [
        {
          person_id: "s1",
          name: "swamini fictional",
          calls: 12,
          connected: 6,
          interested: 3,
          won: 2,
          open_leads: 20,
          late: 1,
        },
      ],
      pipeline: { new: 4, follow_up: 2 },
    },
  });
  await mount(true);
  const titles = Array.from(host.querySelectorAll("h2"), (h) => h.textContent);
  expect(titles).toEqual([
    "How sales are going",
    "Needs you",
    "Sellers",
    "Open leads by stage",
  ]);
  const figures = Array.from(host.querySelectorAll("dt"), (dt) =>
    dt.textContent?.trim(),
  );
  expect(figures).toEqual(["Won", "Interested", "New leads", "Connected"]);
  expect(host.textContent).toContain("13% of 16 leads called");
  expect(host.textContent).toContain("Swamini Fictional");
  expect(host.textContent).toContain("2 won · 3 interested · 12 calls");
  expect(host.textContent).toContain("Late follow-ups");
  expect(host.textContent).toContain("6 open now");
  const seller = host.querySelector<HTMLAnchorElement>(
    'a[href="/organisation/people/s1"]',
  );
  expect(seller).not.toBeNull();
});

it("gives a seller today's calls with one primary action", async () => {
  answer({
    "/v1/lead-desk": desk([
      row("ravi sample", { overdue: true, why_kind: "due" }),
      row("asha fictional"),
    ]),
  });
  await mount(false);
  expect(host.querySelector("h2")?.textContent).toBe("Today");
  expect(host.textContent).toContain("1 late");
  const primary = Array.from(host.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("Call "),
  );
  expect(primary?.textContent).toBe("Call Ravi");
  expect(host.textContent).toContain("Follow-ups done");
});

it("says all caught up when nobody is due", async () => {
  answer({ "/v1/lead-desk": desk([]) });
  await mount(false);
  expect(host.textContent).toContain("All caught up");
  expect(
    Array.from(host.querySelectorAll("a")).some((link) =>
      link.textContent?.startsWith("Call "),
    ),
  ).toBe(false);
});

// Approved map, slice 8 (22 Oct 2026): "Needs you", from facts the server counts.
it("tells an owner what needs them, each row opening the work", async () => {
  answer({
    "/v1/lead-desk": {
      ...desk([]),
      counts: { ...desk([]).counts, unassigned: 2 },
    },
    "/v1/lead-desk/reports/performance*": {
      days: 7,
      start: "2026-10-16",
      end: "2026-10-22",
      current: outcomes(2),
      previous: outcomes(1),
      sellers: [],
      pipeline: {},
    },
    "/v1/lead-desk/reports/sla": {
      settings: { on: true, minutes: 10, alertManagers: false, targets: [] },
      start: "2026-10-16",
      end: "2026-10-22",
      sellers: [],
      late: [
        {
          leadId: "11111111-1111-4111-8111-111111111111",
          leadName: "meera fictional",
          seller: "rahul example",
          minutesLate: 25,
        },
      ],
    },
  });
  await mount(true);
  const needs = host.querySelector('[aria-label="Needs you"]');
  expect(needs?.textContent).toContain("Waiting for a first response");
  expect(needs?.textContent).toContain("Meera Fictional");
  expect(needs?.textContent).toContain("Waiting 25 min · Rahul Example");
  expect(needs?.textContent).toContain("New leads with no owner");
  const links = Array.from(needs?.querySelectorAll("a") ?? [], (a) =>
    a.getAttribute("href"),
  );
  expect(links).toContain("/leads?lead=11111111-1111-4111-8111-111111111111");
  expect(links).toContain("/leads?tab=all&stage=open&who=unassigned");
});

it("says so when nothing needs the owner, and switches to My day", async () => {
  answer({
    "/v1/lead-desk": desk([row("ravi sample", { overdue: true })]),
    "/v1/lead-desk/reports/performance*": {
      days: 7,
      start: "2026-10-16",
      end: "2026-10-22",
      current: outcomes(2),
      previous: outcomes(1),
      sellers: [],
      pipeline: {},
    },
  });
  await mount(true);
  expect(host.textContent).toContain("Nothing needs you right now.");
  const mine = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "My day",
  )!;
  await act(async () => mine.click());
  await act(async () => Promise.resolve());
  expect(host.querySelector("h2")?.textContent).toBe("Today");
  expect(window.location.search).toBe("?view=mine");
});
