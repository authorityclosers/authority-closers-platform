// @vitest-environment happy-dom
// Managing many leads (picks M1, M2-A, M1-C, 17 Nov 2026; study 02 §4-§5):
// the selection's scope, the laptop bar, the phone dock, and Assign with each
// seller's load as one bulk job with Undo.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type Notice = {
  title?: string;
  tone?: string;
  action?: { label: string; run?: () => void };
};
const notices = vi.hoisted(() => [] as Notice[]);
vi.mock("../notice-center", () => ({
  notify: (notice: Notice) => notices.push(notice),
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { alreadyWith, LoadAssignSheet } from "./load-assign-sheet";
import {
  filterOf,
  forgetLoads,
  PhoneDock,
  ScopeBanner,
  selectionRequest,
  SHELF_ACTIONS_ENABLED,
  TableBulkBar,
  withShelf,
  type ManageActions,
} from "./manage-bar";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let sent: { url: string; body: Record<string, unknown> | undefined }[];
const ROHAN = "00000000-0000-4000-8000-000000000011";
const FARAH = "00000000-0000-4000-8000-000000000012";
const GONE = "00000000-0000-4000-8000-000000000013";
const LEAD = (n: number) => `00000000-0000-4000-8000-0000000001${10 + n}`;

const load = (open: number, late: number) => ({
  open,
  late,
  due_today: 0,
  untouched_7d: 0,
  by_stage: {},
});

beforeEach(() => {
  notices.length = 0;
  sent = [];
  forgetLoads();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (url.startsWith("/v1/lead-desk/team/load"))
        return Response.json({
          side: "inbound",
          generated_at: "2026-11-17T06:00:00Z",
          sellers: [
            {
              person_id: FARAH,
              name: "farah example",
              role: "seller",
              takes_new_leads: true,
              max_open: null,
              load: load(42, 6),
            },
            {
              person_id: ROHAN,
              name: "rohan sample",
              role: "seller",
              takes_new_leads: true,
              max_open: null,
              load: load(18, 1),
            },
            {
              person_id: GONE,
              name: "left fictional",
              role: null,
              takes_new_leads: false,
              max_open: null,
              load: load(3, 0),
            },
          ],
          unassigned: load(6, 0),
          totals: load(69, 7),
        });
      if (url === "/v1/lead-desk/leads/bulk-jobs")
        return Response.json({
          job_id: "job-1",
          action: "assign",
          selection: "ids",
          selected: 3,
          changed: 2,
          unchanged: 1,
          not_found: 0,
          failed: [],
          lead_ids: [LEAD(1), LEAD(2)],
          words: "2 leads given to Rohan · 1 already theirs",
          by_person_id: null,
          at: "2026-11-17T06:00:00Z",
          undo_until: "2026-11-17T06:30:00Z",
          undoable: true,
          undone_at: null,
        });
      if (url === "/v1/lead-desk/leads/bulk-jobs/job-1/undo")
        return Response.json({ job_id: "job-1", restored: 2, skipped: 0 });
      return Response.json({}, { status: 404 });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

const actions = (): ManageActions &
  Record<string, ReturnType<typeof vi.fn>> => ({
  onAssign: vi.fn(),
  onStage: vi.fn(),
  onTag: vi.fn(),
  onArchive: vi.fn(),
  onWhatsApp: vi.fn(),
  onBin: vi.fn(),
});

const button = (label: string) =>
  Array.from(document.querySelectorAll("button")).find(
    (item) => item.textContent?.trim() === label,
  );

it("freezes the list's own question, never its sort, as the bulk filter", () => {
  const filter = filterOf({
    scope: "team",
    owner: FARAH,
    stage: null,
    search: "  pune ",
    pipeline: "main",
    more: {
      side: "inbound",
      view: "follow_ups",
      step: null,
      due: "late",
      sort: "name",
      order: "desc",
    },
  });
  expect(filter).toEqual({
    scope: "team",
    side: "inbound",
    view: "follow_ups",
    due: "late",
    owner: FARAH,
    pipeline: "main",
    search: "pune",
  });
  expect(selectionRequest({ kind: "filter", filter, total: 155 })).toEqual({
    filter,
    expected_total: 155,
  });
  expect(selectionRequest({ kind: "ids", ids: [LEAD(1)] })).toEqual({
    lead_ids: [LEAD(1)],
  });
});

it("says the selection's scope and offers every lead that matches", async () => {
  const onAll = vi.fn();
  const view = (count: number, total: number, all = false) =>
    act(async () =>
      root.render(
        <ScopeBanner
          count={count}
          loaded={25}
          total={total}
          allMatching={all}
          where="Follow-ups"
          onAllMatching={onAll}
          onClear={() => undefined}
        />,
      ),
    );
  // Not everything on screen ticked: no banner.
  await view(3, 155);
  expect(host.textContent).toBe("");
  await view(25, 155);
  expect(host.textContent).toContain("All 25 on screen are selected.");
  await act(async () => button("Select all 155 in Follow-ups")?.click());
  expect(onAll).toHaveBeenCalledOnce();
  await view(155, 155, true);
  expect(host.textContent).toContain("All 155 in Follow-ups are selected.");
  await view(25, 25);
  expect(host.textContent).toBe("All 25 in Follow-ups are selected.");
  // Over the server's limit it says so instead of offering it.
  await view(25, 2600);
  expect(host.textContent).toContain("up to 2,000 change at a time");
  expect(button("Select all 2,600 in Follow-ups")).toBeUndefined();
});

it("puts the laptop's actions on one bar, with no red Delete on it", async () => {
  const act1 = actions();
  await act(async () =>
    root.render(
      <TableBulkBar
        count={25}
        busy={false}
        actions={act1}
        onClear={act1.onTag}
        banner={null}
      />,
    ),
  );
  const bar = host.querySelector('[role="toolbar"]')!;
  expect(bar.textContent).toContain("25 selected");
  for (const label of ["Assign", "Change stage", "Add tag", "Archive"]) {
    await act(async () => button(label)?.click());
  }
  expect(act1.onAssign).toHaveBeenCalledOnce();
  expect(act1.onStage).toHaveBeenCalledOnce();
  expect(act1.onArchive).toHaveBeenCalledOnce();
  expect(bar.textContent).not.toContain("Delete");
  // The Bin waits in More.
  await act(async () => button("More")?.click());
  const items = Array.from(
    host.querySelectorAll('[role="menuitem"]'),
    (item) => item.textContent,
  );
  expect(items).toEqual(["Send a WhatsApp template", "Move to Bin…"]);
  await act(async () => button("Move to Bin…")?.click());
  expect(act1.onBin).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="menu"]')).toBeNull();
});

it("gives the phone a dock of four, Archive and the Bin under More", async () => {
  const act1 = actions();
  await act(async () =>
    root.render(<PhoneDock count={3} busy={false} actions={act1} />),
  );
  const dock = host.querySelector('[role="toolbar"]')!;
  expect(Array.from(dock.children, (item) => item.textContent?.trim())).toEqual(
    ["Assign", "Stage", "Tag", "More"],
  );
  await act(async () => button("More")?.click());
  expect(
    Array.from(
      host.querySelectorAll('[role="menuitem"]'),
      (item) => item.textContent,
    ),
  ).toEqual(["Archive", "Send a WhatsApp template", "Move to Bin…"]);
  // Nothing ticked: nothing to act on.
  await act(async () =>
    root.render(<PhoneDock count={0} busy={false} actions={act1} />),
  );
  expect(button("Assign")?.disabled).toBe(true);
});

it("keeps Archive and the Bin off both bars until they can be restored (v1.78)", async () => {
  // No Archived or Bin list with Restore yet (M3-A): nothing hides a lead
  // beyond its 10-second Undo.
  expect(SHELF_ACTIONS_ENABLED).toBe(false);
  const act1 = withShelf(actions());
  expect(act1.onArchive).toBeUndefined();
  expect(act1.onBin).toBeUndefined();
  expect(withShelf(actions(), true).onBin).toBeDefined();
  await act(async () =>
    root.render(
      <TableBulkBar
        count={25}
        busy={false}
        actions={act1}
        onClear={act1.onTag}
        banner={null}
      />,
    ),
  );
  const bar = host.querySelector('[role="toolbar"]')!;
  expect(
    Array.from(bar.querySelectorAll("button"), (item) =>
      item.textContent?.trim(),
    ),
  ).toEqual(["Assign", "Change stage", "Add tag", "More", "Clear"]);
  await act(async () => button("More")?.click());
  expect(
    Array.from(
      host.querySelectorAll('[role="menuitem"]'),
      (item) => item.textContent,
    ),
  ).toEqual(["Send a WhatsApp template"]);
  await act(async () => root.render(<></>));
  await act(async () =>
    root.render(<PhoneDock count={3} busy={false} actions={act1} />),
  );
  const dock = host.querySelector('[role="toolbar"]')!;
  expect(Array.from(dock.children, (item) => item.textContent?.trim())).toEqual(
    ["Assign", "Stage", "Tag", "More"],
  );
  await act(async () => button("More")?.click());
  expect(
    Array.from(
      host.querySelectorAll('[role="menuitem"]'),
      (item) => item.textContent,
    ),
  ).toEqual(["Send a WhatsApp template"]);
});

it("assigns with each seller's load, previews the change and offers Undo", async () => {
  const onDone = vi.fn();
  const selection = { kind: "ids" as const, ids: [LEAD(1), LEAD(2), LEAD(3)] };
  const owners = new Map<string, string | null>([
    [LEAD(1), FARAH],
    [LEAD(2), null],
    [LEAD(3), ROHAN],
  ]);
  expect(alreadyWith(selection, owners, ROHAN)).toBe(1);
  await act(async () =>
    root.render(
      <LoadAssignSheet
        open
        selection={selection}
        side="inbound"
        owners={owners}
        onClose={() => undefined}
        onDone={onDone}
      />,
    ),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  const text = document.body.textContent ?? "";
  expect(text).toContain("Give 3 leads to");
  expect(text).toContain("They keep their stage and follow-ups.");
  expect(text).toContain("Farah Example");
  expect(text).toContain("42 open · 6 late");
  expect(text).toContain("18 open · 1 late");
  // Someone who no longer works leads isn't offered.
  expect(text).not.toContain("Left Fictional");
  expect(text).toContain("Share between sellers");
  const radios = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[name="give-to"]'),
  );
  expect(radios).toHaveLength(3);
  await act(async () => radios[1].click());
  expect(document.body.textContent).toContain(
    "3 selected · 2 will change owner · 1 already with Rohan",
  );
  expect(document.body.textContent).toContain("after: 20");
  await act(async () => button("Give 3 leads to Rohan")?.click());
  const job = sent.find((item) => item.url === "/v1/lead-desk/leads/bulk-jobs");
  expect(job?.body).toMatchObject({
    action: "assign",
    person_id: ROHAN,
    lead_ids: [LEAD(1), LEAD(2), LEAD(3)],
  });
  expect(typeof job?.body?.command_id).toBe("string");
  expect(onDone).toHaveBeenCalledOnce();
  const done = notices.at(-1)!;
  expect(done.title).toBe("2 leads given to Rohan · 1 already theirs");
  expect(done.action?.label).toBe("Undo");
  await act(async () => {
    done.action?.run?.();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(
    sent.some(
      (item) => item.url === "/v1/lead-desk/leads/bulk-jobs/job-1/undo",
    ),
  ).toBe(true);
  expect(notices.at(-1)?.title).toBe("2 leads put back");
});
