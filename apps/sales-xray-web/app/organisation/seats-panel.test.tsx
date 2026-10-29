// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { parseSeats, type OrgMember } from "./organisation-api";
import {
  quietestFirst,
  seatSource,
  SeatsPanel,
  type SeatUse,
} from "./seats-panel";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const seats = (overrides: Record<string, unknown> = {}) => ({
  paid_seats: 0,
  complimentary_seats: 4,
  total_seats: 4,
  active_members: 2,
  pending_invites: 1,
  seats_available: 1,
  can_buy: true,
  ...overrides,
});
const DAY = 86_400_000;
const member = (
  n: number,
  name: string,
  daysQuiet: number | null,
): OrgMember => ({
  status: "active",
  personId: id(n),
  inviteId: null,
  name,
  email: `${name.toLowerCase().replace(/\s+/g, ".")}@example.test`,
  role: "member",
  joinedAt: new Date(Date.now() - 60 * DAY).toISOString(),
  lastActiveAt:
    daysQuiet === null
      ? null
      : new Date(Date.now() - daysQuiet * DAY).toISOString(),
  minutesUsed30d: 0,
  calls30d: 1,
});

let root: Root;
let host: HTMLDivElement;
let reply: () => Response;
let fetchMock: ReturnType<typeof vi.fn>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  reply = () => json(seats());
  fetchMock = vi.fn(async (url: string) => {
    expect(url).toBe("/v1/organisation/seats");
    return reply();
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function show(
  props: Partial<{
    version: number;
    people: OrgMember[] | null;
    usage: Map<string, SeatUse> | null;
    seesTeam: boolean;
  }> = {},
) {
  await act(async () =>
    root.render(
      <SeatsPanel
        version={props.version ?? 0}
        people={props.people ?? null}
        usage={props.usage ?? null}
        seesTeam={props.seesTeam ?? true}
      />,
    ),
  );
  await vi.waitFor(() =>
    expect(host.querySelector('[aria-busy="true"]')).toBeNull(),
  );
}

it("reads the server's seat counts and refuses a shape it does not know", () => {
  expect(parseSeats(seats())).toEqual({
    paidSeats: 0,
    complimentarySeats: 4,
    totalSeats: 4,
    activeMembers: 2,
    pendingInvites: 1,
    seatsAvailable: 1,
    canBuy: true,
  });
  expect(() => parseSeats(seats({ total_seats: 5 }))).toThrow();
  expect(() => parseSeats(seats({ until: "2027-01-31" }))).toThrow();
  expect(() => parseSeats(seats({ can_buy: "yes" }))).toThrow();
  expect(() => parseSeats(seats({ pending_invites: 1.5 }))).toThrow();
});

it("says where seats come from in plain words", () => {
  const counts = parseSeats(seats());
  expect(seatSource(counts)).toBe("4 free seats from Authority Closers");
  expect(seatSource({ ...counts, paidSeats: 1, complimentarySeats: 0 })).toBe(
    "1 paid seat",
  );
  expect(seatSource({ ...counts, paidSeats: 10, complimentarySeats: 1 })).toBe(
    "10 paid seats and 1 free seat from Authority Closers",
  );
});

it("shows seats taken, who holds them and where to buy more, with no dates or prices", async () => {
  await show();
  const text = host.textContent ?? "";
  expect(text).toContain("3 of 4 seats taken");
  expect(text).toContain("2 members");
  expect(text).toContain("1 invite waiting");
  expect(text).toContain("1 free");
  expect(text).toContain("4 free seats from Authority Closers");
  expect(text).not.toMatch(/₹|until|valid/i);
  const buy = host.querySelector("a");
  expect(buy?.textContent).toBe("Buy seats");
  expect(buy?.getAttribute("href")).toBe("/settings/plan");
  expect(host.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
    "3 of 4 seats taken: 2 members, 1 invite waiting, 1 free",
  );
});

it("says how to free a seat when every seat is taken", async () => {
  reply = () =>
    json(seats({ active_members: 3, pending_invites: 1, seats_available: 0 }));
  await show();
  expect(host.textContent).toContain(
    "Every seat is taken. Remove someone or revoke an invite to free one.",
  );
});

it("an admin without seats is told to ask the owner and gets no buy link", async () => {
  reply = () =>
    json(
      seats({
        complimentary_seats: 0,
        total_seats: 0,
        active_members: 1,
        pending_invites: 0,
        seats_available: 0,
        can_buy: false,
      }),
    );
  await show();
  expect(host.textContent).toContain("No seats yet.");
  expect(host.textContent).toContain("Ask your owner to add seats");
  expect(host.querySelector("a")).toBeNull();
});

it("lists seat use quietest first, with calls, call minutes and a Quiet mark", async () => {
  const people = [
    member(1, "Busy Seller", 0),
    member(2, "Quiet Seller", 20),
    member(3, "New Seller", null),
  ];
  const usage = new Map<string, SeatUse>([
    [id(1), { calls: 12, minutes: 47.6 }],
    [id(2), { calls: 0, minutes: 0 }],
  ]);
  await show({ people, usage });
  const rows = [...host.querySelectorAll("li")].filter((row) =>
    row.querySelector("small"),
  );
  expect(rows.map((row) => row.querySelector("b")?.textContent)).toEqual([
    "New Seller",
    "Quiet Seller",
    "Busy Seller",
  ]);
  expect(rows[0].textContent).toContain("Quiet");
  expect(rows[0].textContent).toContain("1 call · not active yet");
  expect(rows[1].textContent).toContain("0 calls · 0 min");
  expect(rows[2].textContent).toContain("12 calls · 48 min · active today");
  expect(rows[2].textContent).not.toContain("Quiet");
});

it("Finance sees the counts but not each person's use", async () => {
  await show({ people: [member(1, "Busy Seller", 0)], seesTeam: false });
  expect(host.textContent).toContain("3 of 4 seats taken");
  expect(host.textContent).not.toContain("Busy Seller");
});

it("hides itself on a server without seats and retries after an error", async () => {
  reply = () => json({ detail: "Not Found" }, 404);
  await show();
  expect(host.textContent).toBe("");

  reply = () => json({ detail: "Busy" }, 503);
  await show({ version: 1 });
  expect(host.textContent).toContain("Seats could not be loaded.");
  reply = () => json(seats());
  const retry = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Try again",
  );
  await act(async () => retry?.click());
  await vi.waitFor(() =>
    expect(host.textContent).toContain("3 of 4 seats taken"),
  );
});

it("orders only active members", () => {
  const invited = {
    ...member(9, "Invited Person", null),
    status: "invited",
    personId: null,
    inviteId: id(9),
  } as OrgMember;
  expect(
    quietestFirst([member(1, "A Seller", 1), invited], Date.now()).map(
      (row) => row.name,
    ),
  ).toEqual(["A Seller"]);
});
