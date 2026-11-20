import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import type {
  Effort,
  SellerEffort,
  SideEffort,
} from "../performance/performance-client";
import { attention } from "../performance/growth-visual";
import { resetHomeReads } from "./home-load";
import { both, teamFigures } from "./team-numbers";
import { insights, sellerNow, TeamToday } from "./team-today";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Round 2, board 6 (owner's pick, 20 Nov 2026): Team today, insights first.
// Fictional sellers and numbers.
const NOW = new Date("2026-11-20T09:15:00Z"); // 2:45 PM in India, a Friday

const day = (extra: Partial<SideEffort> = {}): SideEffort => ({
  attempted: 0,
  connected: 0,
  talk_seconds: 0,
  leads_attempted: 0,
  reached: 0,
  interested: 0,
  meetings: 0,
  won: 0,
  worked_interested: 0,
  backlog: 0,
  eligible: 0,
  first_call_minutes: null,
  late: 0,
  missed_calls: 0,
  not_called_back: 0,
  missing_recordings: 0,
  ...extra,
});

const seller = (
  id: string,
  name: string,
  inbound: Partial<SideEffort>,
  cold: Partial<SideEffort>,
  extra: Partial<SellerEffort> = {},
): SellerEffort => ({
  person_id: id,
  name,
  inbound: day(inbound),
  cold: day(cold),
  breaks: [],
  unplanned_break_minutes: 0,
  first_call_at: null,
  last_call_at: null,
  tasks_late: 0,
  missing_recordings: 0,
  ...extra,
});

const today = (): Effort => ({
  days: 1,
  start: "2026-11-20",
  end: "2026-11-20",
  team: true,
  sellers: [
    seller(
      "s1",
      "priya example",
      {
        attempted: 30,
        connected: 12,
        talk_seconds: 1800,
        first_call_minutes: 4,
      },
      { attempted: 10, connected: 2 },
      { last_call_at: "2026-11-20T09:05:00Z", missing_recordings: 1 },
    ),
    seller(
      "s2",
      "aditya sample",
      { attempted: 20, connected: 8, first_call_minutes: 9, late: 5 },
      { attempted: 5, connected: 1, late: 1 },
      { last_call_at: "2026-11-20T07:30:00Z", missing_recordings: 9 },
    ),
    seller("s3", "rohan fictional", {}, {}),
  ],
  inbound: day({
    attempted: 50,
    connected: 20,
    talk_seconds: 3000,
    first_call_minutes: 6,
    late: 5,
    backlog: 4,
    not_called_back: 2,
    missing_recordings: 8,
  }),
  cold: day({ attempted: 15, connected: 3, late: 1, backlog: 6 }),
  missing_recordings: 10,
});

const lastWeek = (): Effort => ({
  ...today(),
  inbound: day({ attempted: 40, connected: 10, first_call_minutes: 11 }),
  cold: day({ attempted: 5 }),
});

it("counts the team one way, so Home's Team today and Growth agree (board 6)", () => {
  const effort = today();
  const all = teamFigures(effort, "all");
  // Growth's tiles and Needs attention, from the same read.
  expect(all.calls).toBe(both(effort, "attempted"));
  expect(all.calls).toBe(65);
  expect(all.noRecording).toBe(
    attention(effort).find((row) => row.key === "recordings")?.value,
  );
  expect(all.late).toBe(
    attention(effort).find((row) => row.key === "late")?.value,
  );
  // Inbound is a filter that says so, never a silent default.
  const inbound = teamFigures(effort, "inbound");
  expect(inbound.calls).toBe(50);
  expect(inbound.noRecording).toBe(8);
  // Speed to lead is Inbound's on every scope.
  expect(inbound.speed).toBe(all.speed);
});

it("writes the morning note in plain words, worst first, each with one action", () => {
  const list = insights({
    today: today(),
    before: lastWeek(),
    scope: "all",
    waiting: 3,
    newKey: "new",
    now: NOW,
  });
  expect(list.map((item) => item.key)).toEqual([
    "missed",
    "recordings",
    "waiting",
    "quiet",
  ]);
  expect(list[1].text).toBe(
    "10 connected calls today have no recording, 9 from Aditya Sample's phone. Their phone setup may be off.",
  );
  expect(list[1].action.href).toBe("/analysis/calls?day=today&person=s2");
  expect(list[2].text).toBe("3 new leads are waiting for a first call.");
  // Rohan has no call; Aditya none for 1 h 45 min.
  expect(list[3].text).toBe(
    "2 sellers haven't made a call for an hour or more: Aditya, Rohan.",
  );
});

it("says how fast new leads were called beside the week before", () => {
  const quiet = { ...today(), sellers: [] };
  quiet.inbound = day({ first_call_minutes: 6 });
  quiet.cold = day();
  quiet.missing_recordings = 0;
  const [speed] = insights({
    today: quiet,
    before: lastWeek(),
    scope: "all",
    waiting: 0,
    newKey: "new",
    now: NOW,
  });
  expect(speed.text).toBe(
    "New leads were called in 6 min today (median), faster than the Fri before (11 min).",
  );
  expect(speed.tone).toBe("good");
});

it("says where a seller is from the last call, never a live call it can't know", () => {
  const [priya, aditya, rohan] = today().sellers;
  expect(sellerNow(priya, "all", NOW)).toEqual({
    words: "Last call 2:35 PM",
    tone: "calling",
  });
  expect(sellerNow(aditya, "all", NOW)).toEqual({
    words: "No call for 1 h 45 min",
    tone: "quiet",
  });
  expect(sellerNow(aditya, "all", NOW, true).tone).toBe("calling");
  expect(sellerNow(rohan, "all", NOW)).toEqual({
    words: "No calls yet",
    tone: "none",
  });
});

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  window.history.replaceState(null, "", "/dashboard");
  resetHomeReads();
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === "/v1/lead-desk/performance/sellers?days=1")
        return Response.json(today());
      if (path.startsWith("/v1/lead-desk/performance/sellers?days=1&on="))
        return Response.json(lastWeek());
      if (path.startsWith("/v1/lead-desk/leads?scope=team"))
        return Response.json({ leads: [], total: 3, next_offset: null });
      return new Response("{}", { status: 404 });
    }),
  );
});
afterEach(async () => {
  // The plain-function cases draw nothing.
  if (root) await act(async () => root.unmount());
  if (host) host.remove();
  root = undefined as unknown as Root;
  host = undefined as unknown as HTMLDivElement;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const kpi = (label: string) =>
  Array.from(host.querySelectorAll("li a")).find(
    (link) => link.querySelector("span")?.textContent === label,
  );

it("is Team today: insights, today beside last week, one row per seller, what is coming", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(<TeamToday stages={{ newKey: "new", openKey: null }} />),
  );
  for (let step = 0; step < 4; step += 1)
    await act(async () => Promise.resolve());
  expect(host.querySelector("h2")?.textContent).toBe("Team today");
  expect(host.querySelectorAll("[data-insight]")).toHaveLength(4);
  expect(kpi("Calls")?.querySelector("strong")?.textContent).toBe("65");
  expect(kpi("Calls")?.textContent).toContain("Last Fri: 45");
  expect(kpi("Sellers calling")?.querySelector("strong")?.textContent).toBe(
    "2 of 3",
  );
  expect(kpi("Speed to lead")?.textContent).toBe(
    "Speed to lead6 minLast Fri: 11 min",
  );
  const rows = Array.from(host.querySelectorAll("tbody tr"), (tr) =>
    tr.getAttribute("data-seller"),
  );
  expect(rows).toEqual(["s1", "s2", "s3"]);
  expect(
    host.querySelector('tr[data-seller="s1"] a')?.getAttribute("href"),
  ).toBe("/analysis/calls?day=today&person=s1");
  expect(host.textContent).toContain("Coming soon");
  expect(host.textContent).toContain("On a call right now");
  // Inbound picked: the numbers and the words follow, kept in the address.
  const inbound = Array.from(host.querySelectorAll("[role=radio]")).find(
    (radio) => radio.textContent === "Inbound",
  ) as HTMLButtonElement;
  await act(async () => inbound.click());
  expect(window.location.search).toBe("?count=inbound");
  expect(kpi("Calls")?.querySelector("strong")?.textContent).toBe("50");
  expect(host.textContent).toContain("Inbound leads");
});
