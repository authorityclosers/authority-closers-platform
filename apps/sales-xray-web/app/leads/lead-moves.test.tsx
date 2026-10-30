// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, expect, it } from "vitest";

import { announceWorkspaceChange } from "../workspace-change";
import {
  deskWithMoves,
  inStageList,
  noteLeadMoved,
  useLeadMoves,
  withMoves,
  type Moves,
} from "./lead-moves";
import type { Desk, LeadPage, LeadRow } from "./leads-client";
import { LEADS_CACHE_SLOT } from "./list-cache-slot";
// What the device keeps follows moves once the list cache is loaded.
import "./list-cache";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 30 Oct 2026: after a disposition the lead leaves the list being
// worked at once, the next lead is on top, and it shows under its new stage.
const row = (n: number, stage: LeadRow["stage"], revision = 1): LeadRow => ({
  lead_id: `fictional-${n}`,
  revision,
  name: `Fictional prospect ${n}`,
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: null,
  stage,
  stage_label: stage,
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-30T00:00:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: true,
});
const list = (stage: string, readAt = 0, join = true) => ({
  belongs: (lead: LeadRow) => inStageList(lead, stage),
  join,
  readAt,
});
const movesOf = (...moved: LeadRow[]): Moves =>
  new Map(moved.map((lead) => [lead.lead_id, { row: lead, at: 10 }]));

beforeEach(() => {
  localStorage.clear();
  announceWorkspaceChange("arrived");
});

it("a list is a filter on the stage: All holds every open stage, a stage its own", () => {
  expect(inStageList(row(1, "new"), "open")).toBe(true);
  expect(inStageList(row(1, "interested"), "open")).toBe(true);
  for (const closed of ["won", "lost", "junk"] as const)
    expect(inStageList(row(1, closed), "open")).toBe(false);
  expect(inStageList(row(1, "follow_up"), "follow_up")).toBe(true);
  expect(inStageList(row(1, "follow_up"), "new")).toBe(false);
});

it("a moved lead leaves the list at once, so the next lead is on top", () => {
  const rows = [row(1, "new"), row(2, "new"), row(3, "new")];
  const moved = row(1, "follow_up", 2);
  const shown = withMoves(rows, movesOf(moved), list("new", 5));
  expect(shown.map((lead) => lead.lead_id)).toEqual([
    "fictional-2",
    "fictional-3",
  ]);
  // All leads keeps it, at its new stage.
  const all = withMoves(rows, movesOf(moved), list("open", 5));
  expect(all).toHaveLength(3);
  expect(all[0]).toBe(moved);
});

it("it joins the top of its new stage's list until a read after the move has it", () => {
  const moved = row(1, "follow_up", 2);
  const before = [row(7, "follow_up")];
  expect(withMoves(before, movesOf(moved), list("follow_up", 5))[0]).toBe(
    moved,
  );
  // A read asked after the move is the server's answer: nothing is added.
  expect(withMoves(before, movesOf(moved), list("follow_up", 20))).toBe(before);
  // With a search or other filters on, it is not added where it may not fit.
  expect(withMoves(before, movesOf(moved), list("follow_up", 5, false))).toBe(
    before,
  );
});

it("the server's row wins once it is as new as the move; test leads only refresh", () => {
  const moved = row(1, "follow_up", 2);
  const rows = [row(1, "new", 3), row(2, "new")];
  expect(withMoves(rows, movesOf(moved), list("new", 5))).toBe(rows);
  const test = [row(1, "new"), row(2, "new")];
  const shown = withMoves(test, movesOf(moved), {
    belongs: null,
    join: true,
    readAt: 0,
  });
  expect(shown.map((lead) => lead.stage)).toEqual(["follow_up", "new"]);
});

it("To call drops a lead just worked, and is the same desk when nothing moved", () => {
  const desk = {
    queue: [row(1, "new"), row(2, "new")],
    upcoming: [row(3, "follow_up")],
    call_back: [],
  } as unknown as Desk;
  expect(deskWithMoves(desk, new Map())).toBe(desk);
  const after = deskWithMoves(desk, movesOf(row(1, "not_connected", 2)));
  expect(after.queue.map((lead) => lead.lead_id)).toEqual(["fictional-2"]);
  expect(after.upcoming).toHaveLength(1);
});

it("noting a move tells the lists, patches what the device keeps, and a workspace change forgets it", async () => {
  const page = (leads: LeadRow[]) =>
    ({ leads, total: leads.length, next_offset: null }) as unknown as LeadPage;
  const question = (stage: string) =>
    `list:${JSON.stringify(["mine", null, stage, "", false, null, null])}`;
  localStorage.setItem(
    LEADS_CACHE_SLOT,
    JSON.stringify({
      identity: JSON.stringify(["person", "session", "workspace"]),
      entries: {
        [question("new")]: {
          at: 1,
          value: page([row(1, "new"), row(2, "new")]),
        },
        [question("open")]: { at: 1, value: page([row(1, "new")]) },
        "leads.desk:": {
          at: 1,
          value: { queue: [row(1, "new"), row(2, "new")] },
        },
      },
    }),
  );
  const host = document.createElement("div");
  const root = createRoot(host);
  function Count() {
    return <output>{useLeadMoves().size}</output>;
  }
  await act(async () => root.render(<Count />));
  expect(host.textContent).toBe("0");

  await act(async () => noteLeadMoved(row(1, "lost", 2)));
  expect(host.textContent).toBe("1");
  const kept = JSON.parse(localStorage.getItem(LEADS_CACHE_SLOT) ?? "{}") as {
    entries: Record<
      string,
      { value: { leads?: LeadRow[]; queue?: LeadRow[] } }
    >;
  };
  const ids = (key: string) =>
    (kept.entries[key].value.leads ?? kept.entries[key].value.queue ?? []).map(
      (lead) => lead.lead_id,
    );
  expect(ids(question("new"))).toEqual(["fictional-2"]);
  expect(ids(question("open"))).toEqual([]);
  expect(ids("leads.desk:")).toEqual(["fictional-2"]);

  await act(async () => announceWorkspaceChange("leaving"));
  expect(host.textContent).toBe("0");
  await act(async () => root.unmount());
});
