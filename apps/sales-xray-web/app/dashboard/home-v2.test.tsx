// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("../shell/app-router", () => ({ useAppRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    prefetch,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    prefetch?: boolean;
    children: React.ReactNode;
  }) => {
    void prefetch;
    return (
      <a {...props} href={href}>
        {children}
      </a>
    );
  },
}));

import type { LibrarySubmission } from "../acquisition-client";
import {
  mergeCalls,
  rowFromSaved,
  type WeekActivity,
} from "../calls/call-rows";
import { takeHandedLead } from "../leads/lead-handoff";
import type { ActivityItem, LeadEvent } from "../leads/leads-client";
import { WorkspaceAccessContext } from "../workspace-access";
import {
  activityItems,
  activityLine,
  HomeActivity,
  HomeRecentCalls,
  pickUpFrom,
  PickUp,
  rememberOpened,
  SetupStart,
  startSteps,
} from "./home-v2";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const PERSON = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const REPORT = "00000000-0000-4000-8000-000000000501";

const minutesAgo = (minutes: number) =>
  new Date(Date.now() - minutes * 60_000).toISOString();

const event = (kind: LeadEvent["kind"], extra = {}): LeadEvent =>
  ({
    kind,
    at: new Date(Date.now() - 20 * 60_000).toISOString(),
    actor_name: "Meera Fictional",
    ...extra,
  }) as LeadEvent;

const item = (id: string, lead: string, e: LeadEvent): ActivityItem => ({
  event_id: id,
  lead_id: `lead-${id}`,
  lead_name: lead,
  stage_label: "Interested",
  event: e,
});

const saved = (extra: Partial<LibrarySubmission> = {}): LibrarySubmission => ({
  id: REPORT,
  createdAt: new Date(Date.now() - 60 * 60_000).toISOString(),
  durationSeconds: 842,
  state: "completed",
  hasReport: true,
  label: { displayName: "Site visit", revision: 1 },
  ...extra,
});

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  push.mockClear();
  takeHandedLead();
  localStorage.clear();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const render = (node: React.ReactNode) =>
  act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: PERSON, sessionId: "s", tenantId: TENANT },
          retry: () => {},
        }}
      >
        {node}
      </WorkspaceAccessContext.Provider>,
    ),
  );

it("picks up only this person's recent lead or Report, here", () => {
  const who = { person: PERSON, tenant: TENANT };
  const now = new Date("2026-10-27T10:00:00Z");
  const raw = (extra = {}) =>
    JSON.stringify({
      kind: "lead",
      id: "lead-1",
      name: "asha fictional",
      at: "2026-10-27T09:30:00Z",
      person: PERSON,
      tenant: TENANT,
      ...extra,
    });
  expect(pickUpFrom(raw(), who, now)?.id).toBe("lead-1");
  expect(pickUpFrom(raw({ person: "someone-else" }), who, now)).toBeNull();
  expect(pickUpFrom(raw({ tenant: "another-org" }), who, now)).toBeNull();
  expect(pickUpFrom(raw({ at: "2026-10-20T09:30:00Z" }), who, now)).toBeNull();
  expect(pickUpFrom(raw({ kind: "task" }), who, now)).toBeNull();
  expect(pickUpFrom("not json", who, now)).toBeNull();
  expect(pickUpFrom(raw(), null, now)).toBeNull();
});

it("opens the lead you left off at", async () => {
  rememberOpened({
    kind: "lead",
    id: "lead-1",
    name: "asha fictional",
    person: PERSON,
    tenant: TENANT,
  });
  await render(<PickUp />);
  const link = container.querySelector("a")!;
  expect(link.textContent).toContain("Pick up where you left off");
  expect(link.textContent).toContain("Asha Fictional");
  await act(async () => link.click());
  expect(push).toHaveBeenCalledWith("/leads");
  expect(takeHandedLead()).toEqual({ leadId: "lead-1", call: false });
});

it("merges phone and saved calls, each once, newest first", () => {
  const phone = {
    key: "e1",
    name: "Meera Fictional",
    at: new Date(Date.now() - 30 * 60_000).toISOString(),
    line: "You called · 21:08",
    kind: "outgoing" as const,
    report: REPORT,
    leadId: "lead-1",
  };
  const other = rowFromSaved(
    saved({ id: "00000000-0000-4000-8000-000000000511" }),
  );
  const rows = mergeCalls([phone], [rowFromSaved(saved()), other]);
  expect(rows.map((row) => row.key)).toEqual([
    "e1",
    "saved-00000000-0000-4000-8000-000000000511",
  ]);
  expect(other.line).toBe("Report ready · 14:02");
  expect(rowFromSaved(saved({ label: null })).name).toBe("Saved call");
});

it("shows the last three calls, each opening the Report or the lead", async () => {
  const week: WeekActivity = {
    status: "ready",
    more: false,
    items: [
      item(
        "e1",
        "asha fictional",
        event("call", { duration_seconds: 214, at: minutesAgo(10) }),
      ),
      item(
        "e2",
        "ravi sample",
        event("call", { direction: "missed", at: minutesAgo(20) }),
      ),
      item("e3", "karan example", event("note", { note: "Call after 6" })),
    ],
  };
  await render(<HomeRecentCalls week={week} saved={[saved()]} />);
  const rows = [...container.querySelectorAll("a[data-sx-action]")];
  expect(rows).toHaveLength(3);
  expect(rows[0].textContent).toContain("Asha Fictional");
  expect(rows[2].getAttribute("href")).toBe(`/analysis/calls/${REPORT}`);
  expect(container.textContent).not.toContain("Karan");
  expect(container.querySelector('a[href="/analysis/calls"]')).not.toBeNull();
});

it("hides Recent calls and Recent activity when there is nothing to show", async () => {
  const week: WeekActivity = { status: "ready", more: false, items: [] };
  await render(
    <>
      <HomeRecentCalls week={week} saved={[]} />
      <HomeActivity week={week} />
    </>,
  );
  expect(container.textContent).toBe("");
});

it("lists recent activity in the seller's words and opens the lead at that line", async () => {
  const note = item(
    "e3",
    "karan example",
    event("note", { note: "Call after 6" }),
  );
  const assigned = item(
    "e4",
    "neha fictional",
    event("assigned", { owner_name: "Swamini Fictional" }),
  );
  const week: WeekActivity = {
    status: "ready",
    more: false,
    items: [item("e1", "asha fictional", event("call")), note, assigned],
  };
  expect(activityItems(week)).toEqual([note, assigned]);
  expect(activityLine(note)).toBe("You added a note");
  expect(activityLine(assigned)).toBe("Assigned to Swamini Fictional");
  await render(<HomeActivity week={week} />);
  const rows = [...container.querySelectorAll("a[data-lead-row]")];
  expect(rows).toHaveLength(2);
  expect(rows[0].textContent).toContain("Karan Example");
  await act(async () => (rows[0] as HTMLAnchorElement).click());
  expect(takeHandedLead()).toEqual({
    leadId: "lead-e3",
    call: false,
    at: note.event.at,
  });
});

it("counts the first steps from what the desk says", () => {
  const empty = {
    counts: { open: 0 },
    numbers: { calls: 0 },
    numbers_week: { calls: 0 },
    team_pool: { open: 0 },
  };
  const steps = startSteps(empty, { inApp: true, logging: false }, false);
  expect(steps.map((step) => [step.key, step.done])).toEqual([
    ["phone", false],
    ["leads", false],
    ["call", false],
  ]);
  const going = startSteps(
    { ...empty, counts: { open: 4 }, numbers_week: { calls: 1 } },
    { inApp: true, logging: true },
    true,
  );
  expect(going.filter((step) => step.done).map((step) => step.key)).toEqual([
    "phone",
    "leads",
    "call",
  ]);
  expect(going.map((step) => step.key)).toContain("team");
  // In a browser the first step is getting the phone app.
  // In the app the first step is the permission; in a browser, getting the app.
  expect(steps[0]).toMatchObject({
    title: "Allow call logging",
    href: "/leads#phone-setup",
  });
  expect(
    startSteps(empty, { inApp: false, logging: false }, false)[0],
  ).toMatchObject({ title: "Get the phone app", href: "/leads?app=1" });
});

it("starts a new workspace with steps, a sample report and one first action", async () => {
  await render(
    <SetupStart
      desk={{ counts: { open: 0 }, numbers: { calls: 0 }, team_pool: null }}
      manager={false}
      sample
    />,
  );
  expect(container.textContent).toContain("Let's get you calling");
  expect(
    container.querySelector('[role="img"]')?.getAttribute("aria-label"),
  ).toBe("0 of 3 done");
  expect(container.querySelector('a[href="/leads?app=1"]')).not.toBeNull();
  expect(
    container.querySelector('a[href="/analysis/sample"]')?.textContent,
  ).toContain("Sample");
  expect(
    container.querySelector('a[href="/leads#add=lead"]')?.textContent,
  ).toBe("Add your first lead");
});

it("offers the sample report by default, and leaves it out when told to", async () => {
  const desk = { counts: { open: 0 }, numbers: { calls: 0 }, team_pool: null };
  await render(<SetupStart desk={desk} manager={false} />);
  expect(container.querySelector('a[href="/analysis/sample"]')).not.toBeNull();
  await render(<SetupStart desk={desk} manager={false} sample={false} />);
  expect(container.querySelector('a[href="/analysis/sample"]')).toBeNull();
  expect(container.textContent).toContain("Add your first lead");
});
