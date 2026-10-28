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

import type { LibrarySubmission } from "../acquisition-client";
import { takeHandedLead } from "../leads/lead-handoff";
import type { ActivityItem, LeadEvent } from "../leads/leads-client";
import {
  byHour,
  rowFromReport,
  TEAM_ROWS,
  TeamActivity,
  teamRows,
  teamSentence,
  type TeamRow,
} from "./team-activity";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const REPORT = "00000000-0000-4000-8000-000000000501";
const minutesAgo = (minutes: number) =>
  new Date(Date.now() - minutes * 60_000).toISOString();

const work = (
  id: string,
  lead: string,
  event: Partial<LeadEvent>,
): ActivityItem => ({
  event_id: id,
  lead_id: `lead-${id}`,
  lead_name: lead,
  stage_label: "Interested",
  event: { kind: "call", at: minutesAgo(10), ...event } as LeadEvent,
});

const saved = (extra: Partial<LibrarySubmission> = {}): LibrarySubmission => ({
  id: REPORT,
  createdAt: minutesAgo(30),
  durationSeconds: 842,
  state: "completed",
  hasReport: true,
  label: { displayName: "Site visit", revision: 1 },
  owner: { personId: "p1", name: "meera example" },
  ...extra,
});

let container: HTMLDivElement;
let root: Root;
let answer: { status: number; body: unknown };

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  push.mockClear();
  takeHandedLead();
  answer = {
    status: 200,
    body: {
      items: [
        work("e1", "asha fictional", {
          actor_name: "Meera Example",
          duration_seconds: 214,
          direction: "outgoing",
          via: "phone",
          at: minutesAgo(5),
        }),
        work("e2", "neha fictional", {
          kind: "assigned",
          actor_name: null,
          owner_name: "Rahul Example",
          at: minutesAgo(20),
        }),
      ],
      next_before: null,
      counts: {},
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("says a ready Report is whose call", () => {
  expect(rowFromReport(saved())).toMatchObject({
    title: "Report ready: Site visit",
    line: "Meera Example's call",
    actor: "meera example",
  });
  expect(rowFromReport(saved({ owner: undefined })).line).toBe("");
});

it("puts who did it first, so nobody reads the lead as the doer", () => {
  const said = (event: Partial<LeadEvent>) =>
    teamSentence(work("e", "asha fictional", event));
  expect(
    said({
      actor_name: "Meera Example",
      duration_seconds: 214,
      direction: "outgoing",
      via: "phone",
    }),
  ).toMatchObject({
    subject: "Meera Example",
    title: "Meera called Asha Fictional · 3:34",
  });
  expect(said({ actor_name: "Meera Example", direction: "missed" }).title).toBe(
    "Meera missed a call from Asha Fictional",
  );
  expect(
    said({ kind: "assigned", actor_name: null, owner_name: "Rahul Example" }),
  ).toMatchObject({
    subject: "Rahul Example",
    title: "Rahul got Asha Fictional",
    line: "By the lead rules",
  });
  expect(
    said({
      kind: "stage",
      actor_name: "Meera Example",
      stage_label: "Site visit booked",
    }).title,
  ).toBe("Meera moved Asha Fictional to Site visit booked");
  expect(
    said({ kind: "captured", actor_name: null, source_label: "Website form" }),
  ).toMatchObject({
    subject: null,
    title: "New lead: Asha Fictional",
    line: "From Website form",
  });
});

it("merges today's work and today's Reports, newest first, each once", () => {
  const call = work("e1", "asha fictional", {
    submission_id: REPORT,
    at: minutesAgo(5),
  });
  const rows = teamRows(
    [call],
    [
      saved(),
      saved({
        id: "00000000-0000-4000-8000-000000000511",
        createdAt: minutesAgo(40),
      }),
      saved({
        id: "00000000-0000-4000-8000-000000000512",
        createdAt: new Date(Date.now() - 3 * 86_400_000).toISOString(),
      }),
    ],
  );
  // The call already has its Report; the older day's Report is left out.
  expect(rows.map((row) => row.key)).toEqual([
    "e1",
    "report-00000000-0000-4000-8000-000000000511",
  ]);
});

it("lists who did what today and opens the lead or the Report", async () => {
  await act(async () => root.render(<TeamActivity saved={[saved()]} />));
  const rows = [
    ...container.querySelectorAll<HTMLAnchorElement>("a[data-sx-action]"),
  ];
  expect(rows).toHaveLength(3);
  expect(rows[0].textContent).toContain("Meera called Asha Fictional · 3:34");
  expect(rows[1].textContent).toContain("Rahul got Neha Fictional");
  expect(rows[2].textContent).toContain("Report ready: Site visit");
  expect(rows[2].getAttribute("href")).toBe(`/analysis/calls/${REPORT}`);
  await act(async () => rows[1].click());
  expect(push).toHaveBeenCalledWith("/leads");
  expect(takeHandedLead()).toMatchObject({ leadId: "lead-e2", call: false });
});

it("stays out of the way for a role that can't see the team", async () => {
  answer = {
    status: 403,
    body: { detail: "Your role sees your own leads only." },
  };
  await act(async () => root.render(<TeamActivity saved={null} />));
  expect(container.textContent).toBe("");
});

// Owner Home v3 (28 Oct 2026, C): the day as hours, who did what in each.
it("groups the lines by the hour they happened in, newest first", () => {
  const at = (hours: number, minutes: number) =>
    new Date(2026, 9, 28, hours, minutes).toISOString();
  const line = (key: string, when: string): TeamRow => ({
    key,
    at: when,
    actor: "Meera Example",
    title: "Meera called Asha Fictional",
    line: "",
    kind: "call",
    report: null,
    leadId: null,
  });
  const groups = byHour([
    line("a", at(10, 42)),
    line("b", at(10, 28)),
    line("c", at(9, 54)),
    line("d", at(14, 5)),
  ]);
  expect(groups.map((group) => group.hour)).toEqual(["10 am", "9 am", "2 pm"]);
  expect(groups[0].rows.map((row) => row.key)).toEqual(["a", "b"]);
});

it("shows a short preview by the hour, and all of today one tap away", async () => {
  answer.body = {
    items: Array.from({ length: TEAM_ROWS + 3 }, (_, index) =>
      work(`n${index}`, "asha fictional", {
        kind: "note",
        actor_name: "Meera Example",
        note: "Wants the brochure",
        at: minutesAgo(5 + index * 7),
      }),
    ),
    next_before: null,
    counts: {},
  };
  await act(async () => root.render(<TeamActivity saved={null} />));
  const preview = container.querySelector(
    'ol[aria-label="Team today, newest first"]',
  );
  expect(preview?.querySelectorAll("a[data-sx-action]")).toHaveLength(
    TEAM_ROWS,
  );
  // Each line says who wrote the note, and when in its hour.
  expect(preview?.textContent).toContain("Meera");
  expect(preview?.querySelector("time")?.textContent).toMatch(
    /^\d{1,2}:\d{2}$/,
  );
  const all = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("All activity"),
  );
  expect(all).toBeDefined();
  await act(async () => all?.click());
  const sheet = document.querySelector("dialog[open]");
  expect(sheet?.querySelectorAll("a[data-sx-action]")).toHaveLength(
    TEAM_ROWS + 3,
  );
  expect(sheet?.textContent).toContain("8 things so far today");
});
