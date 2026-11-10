// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { StageView } from "./journey/journey-client";
import { inWorkView } from "./lead-moves";
import type { LeadRow } from "./leads-client";
import {
  CallBand,
  CallNext,
  callNextView,
  FollowUpTabs,
  LeadSearch,
  StageChips,
  StagePicker,
  ViewTabs,
  WorkSplit,
  resolveStep,
  emptyWords,
  lastView,
  listTitle,
  sideStage,
  stagesPipeline,
  pipelinesFor,
  pickableStages,
  rememberView,
  tabCount,
} from "./work-views";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Dipak's Home + Leads handoff (31 Oct 2026, items 46-80): work views, not
// stages; one stage dropdown; search with one Filter; a compact Call Next.
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const stage = (
  key: string,
  label: string,
  kind: StageView["kind"],
  more: Partial<StageView> = {},
) =>
  ({
    key,
    label,
    kind,
    kindWords: label,
    milestone: "",
    meaning: "",
    archived: false,
    origin: "template",
    leads: 0,
    ...more,
  }) as StageView;

const STAGES = [
  stage("new", "New Lead", "new", { coldLabel: "Unworked" }),
  stage("open_leads", "Open Leads", "follow_up"),
  stage("not_connected", "Not Connected", "not_connected"),
  stage("meeting_done", "Meeting Done", "interested", { visible: false }),
  stage("old", "Old stage", "interested", { archived: true }),
];

const tabs = () =>
  [...host.querySelectorAll('[role="tab"]')].map((tab) => [
    tab.textContent,
    tab.getAttribute("aria-selected"),
  ]);

it("shows To Call, Follow-ups and All Leads as views, and switches once per tap", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(<ViewTabs value="to_call" onChange={onChange} />),
  );
  expect(
    host.querySelector('[role="tablist"]')!.getAttribute("aria-label"),
  ).toBe("Work views");
  expect(tabs()).toEqual([
    ["To Call", "true"],
    ["Follow-ups", "false"],
    ["All Leads", "false"],
  ]);
  const [toCall, followUps] =
    host.querySelectorAll<HTMLButtonElement>("button");
  await act(async () => toCall.click());
  expect(onChange).not.toHaveBeenCalled();
  await act(async () => followUps.click());
  expect(onChange).toHaveBeenCalledWith("follow_ups");
});

it("puts each view's count on its tab once the list has counted (one count rule, #9)", async () => {
  await act(async () =>
    root.render(
      <ViewTabs
        value="to_call"
        onChange={vi.fn()}
        counts={{ to_call: 7, follow_ups: 0, all: 1178 }}
      />,
    ),
  );
  expect(tabs()).toEqual([
    ["To Call 7", "true"],
    ["Follow-ups 0", "false"],
    ["All Leads 1.2K", "false"],
  ]);
  expect([999, 117800].map(tabCount)).toEqual(["999", "1.2L"]);
});

// Leads L1 (owner, 8 Nov 2026: "Build L1"): the views as text tabs that keep
// one line and scroll sideways where they don't fit (bugs 165, 180, N7).
it("keeps the views as text tabs on one line that scroll rather than wrap", async () => {
  await act(async () =>
    root.render(
      <ViewTabs
        value="follow_ups"
        onChange={vi.fn()}
        counts={{ to_call: 233, follow_ups: 4, all: 294 }}
      />,
    ),
  );
  const list = host.querySelector('[role="tablist"]')!;
  // The tabs sit in a sideways scroller of their own, never stacked.
  expect(list.parentElement).not.toBe(host);
  expect(list.hasAttribute("data-stacked")).toBe(false);
  expect(tabs()).toEqual([
    ["To Call 233", "false"],
    ["Follow-ups 4", "true"],
    ["All Leads 294", "false"],
  ]);
});

it("splits Follow-ups into Due Today, Overdue and Upcoming", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(<FollowUpTabs value="today" onChange={onChange} />),
  );
  expect(tabs()).toEqual([
    ["Due Today", "true"],
    ["Overdue", "false"],
    ["Upcoming", "false"],
  ]);
  await act(async () =>
    host.querySelectorAll<HTMLButtonElement>("button")[1].click(),
  );
  expect(onChange).toHaveBeenCalledWith("overdue");
  // The chosen one again: back to every follow-up, so the tab's count is its rows.
  await act(async () =>
    host.querySelectorAll<HTMLButtonElement>("button")[0].click(),
  );
  expect(onChange).toHaveBeenLastCalledWith(null);
});

it("names every stage a seller sees, on the chosen side, in the list's order", async () => {
  const onChange = vi.fn();
  const seller = pickableStages(STAGES, false);
  expect(seller.map((item) => item.key)).toEqual([
    "new",
    "open_leads",
    "not_connected",
  ]);
  expect(pickableStages(STAGES, true).map((item) => item.key)).toContain(
    "meeting_done",
  );
  const rows = () => [...host.querySelectorAll<HTMLElement>('[role="option"]')];
  const options = () => rows().map((item) => item.textContent);
  const open = async () => {
    if (!host.querySelector('[role="listbox"]'))
      await act(async () =>
        host.querySelector<HTMLButtonElement>("button")!.click(),
      );
  };
  await act(async () =>
    root.render(
      <StagePicker
        stages={seller}
        side="inbound"
        value={null}
        onChange={onChange}
      />,
    ),
  );
  expect(host.textContent).toContain("Pipeline stage:");
  await open();
  expect(options()).toEqual([
    "All stages",
    "New Lead",
    "Open Leads",
    "Not Connected",
  ]);
  await act(async () =>
    root.render(
      <StagePicker
        stages={seller}
        side="cold"
        value="open_leads"
        counts={{ new: 3, open_leads: 5 }}
        onChange={onChange}
      />,
    ),
  );
  await open();
  // The first stage is Unworked on Cold Leads (items 64-65), and each stage
  // shows its count for the list's other filters.
  expect(options()).toEqual([
    "All stages8",
    "Unworked3",
    "Open Leads5",
    "Not Connected0",
  ]);
  expect(host.querySelector('[aria-selected="true"]')!.textContent).toBe(
    "Open Leads5",
  );
  await act(async () => rows()[0].click());
  expect(onChange).toHaveBeenLastCalledWith(null);
});

// Owner bug 193 (9 Nov 2026, his OnePlus): All stages opens a list of every
// stage, with a cue that it is a drop-down; the chips after it still pick the
// stages holding leads in one tap.
it("opens every stage from All stages, its chevron saying so", async () => {
  const onChange = vi.fn();
  const seller = pickableStages(STAGES, false);
  await act(async () =>
    root.render(
      <StageChips
        stages={seller}
        side="inbound"
        value={null}
        counts={{ new: 3 }}
        onChange={onChange}
      />,
    ),
  );
  const all = host.querySelector<HTMLButtonElement>(
    'button[aria-haspopup="listbox"]',
  )!;
  expect(all.textContent).toBe("All stages 3");
  expect(all.getAttribute("aria-expanded")).toBe("false");
  expect(all.querySelectorAll("svg")).toHaveLength(2);
  expect(
    [...host.querySelectorAll("button[aria-pressed]")].map(
      (chip) => chip.textContent,
    ),
  ).toEqual(["New Lead 3"]);
  await act(async () => all.click());
  expect(
    [...host.querySelectorAll('[role="option"]')].map((row) => row.textContent),
  ).toEqual(["All stages3", "New Lead3", "Open Leads0", "Not Connected0"]);
  await act(async () =>
    host.querySelectorAll<HTMLElement>('[role="option"]')[2].click(),
  );
  expect(onChange).toHaveBeenLastCalledWith("open_leads");
});

it("searches on the page, and clearing the search leaves the Filter alone", async () => {
  const onChange = vi.fn();
  await act(async () =>
    root.render(
      <LeadSearch
        value="pune"
        onChange={onChange}
        filter={<button type="button">Filter</button>}
      />,
    ),
  );
  expect(
    host.querySelector('input[type="search"]')!.getAttribute("placeholder"),
  ).toBe("Search name or number");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Clear search"]')!
      .click(),
  );
  expect(onChange).toHaveBeenCalledWith("");
  expect(host.textContent).toContain("Filter");
});

it("calls the next lead on Inbound and starts cold calling on Cold", async () => {
  const onStart = vi.fn();
  await act(async () =>
    root.render(<CallNext side="inbound" disabled={false} onStart={onStart} />),
  );
  const button = () => host.querySelector<HTMLButtonElement>("button")!;
  expect(button().textContent).toBe("Call Next Lead");
  await act(async () => button().click());
  expect(onStart).toHaveBeenCalledTimes(1);
  await act(async () =>
    root.render(<CallNext side="cold" disabled onStart={onStart} />),
  );
  expect(button().textContent).toBe("Start Cold Calling");
  expect(button().disabled).toBe(true);
  // The round's size on the button (competitor teardown 2).
  await act(async () =>
    root.render(
      <CallNext side="cold" disabled={false} onStart={onStart} count={900} />,
    ),
  );
  expect(button().textContent).toBe("Start Cold Calling · 900");
});

it("names the band's call for its view: Call Next Follow-up on Follow-ups (Leads L1)", async () => {
  const onStart = vi.fn();
  const label = () => host.querySelector("button")!.textContent;
  await act(async () =>
    root.render(
      <CallBand side="inbound" disabled={false} onStart={onStart} count={16} />,
    ),
  );
  expect(label()).toBe("Call Next Lead · 16");
  await act(async () =>
    root.render(
      <CallBand
        side="inbound"
        view="follow_ups"
        disabled={false}
        onStart={onStart}
        count={12}
      />,
    ),
  );
  expect(label()).toBe("Call Next Follow-up · 12");
  await act(async () =>
    root.render(
      <CallBand side="cold" disabled={false} onStart={onStart} count={233} />,
    ),
  );
  expect(label()).toBe("Start Cold Calling · 233");
  await act(async () => host.querySelector("button")!.click());
  expect(onStart).toHaveBeenCalledTimes(1);
});

it("remembers the last work view per person, without a lead, a search or whose leads", () => {
  expect(
    rememberView("p1:t1", {
      side: "cold",
      view: "follow_ups",
      when: "overdue",
      step: "open_leads",
      source: "meta",
    }),
  ).toBe(true);
  expect(lastView("p1:t1")).toBe(
    "side=cold&view=follow_ups&step=open_leads&when=overdue&source=meta",
  );
  expect(lastView("p2:t1")).toBeNull();
  // Where Leads opens needs nothing kept.
  expect(rememberView("p1:t1", {})).toBe(false);
  expect(lastView("p1:t1")).toBeNull();
});

it("says what each list holds and what an empty one means", () => {
  expect(listTitle("to_call", "inbound", null)).toBe("Inbound leads to call");
  expect(listTitle("to_call", "cold", null)).toBe("Cold leads to call");
  expect(listTitle("follow_ups", "inbound", "overdue")).toBe(
    "Overdue · Inbound",
  );
  expect(listTitle("follow_ups", "cold", null)).toBe("Cold follow-ups");
  // All Leads is both sides (owner, 2 Nov 2026); a Cold row says so.
  expect(listTitle("all", "cold", null)).toBe("All leads");
  expect(listTitle("all", "inbound", null)).toBe("All leads");
  expect(sideStage({ side: "cold" }, "Unworked")).toBe("Cold · Unworked");
  expect(sideStage({ side: "inbound" }, "New Lead")).toBe("New Lead");
  expect(sideStage({}, "New Lead")).toBe("New Lead");
  // Several pipelines and none picked: the main pipeline's stages, as the server
  // counts them (Dipak, 3 Nov 2026: only "All stages" showed).
  expect(stagesPipeline(null)).toBe("main");
  expect(stagesPipeline(undefined)).toBe("main");
  expect(stagesPipeline("partner_outreach")).toBe("partner_outreach");
  // Sellers never see pipelines; whoever manages leads picks one (bug 129).
  const pipes = { pipelines: [{ key: "main" }, { key: "partner_outreach" }] };
  expect(pipelinesFor("member", pipes)).toBeNull();
  expect(pipelinesFor("viewer", pipes)).toBeNull();
  expect(pipelinesFor(undefined, pipes)).toBeNull();
  for (const role of ["owner", "admin", "manager"])
    expect(pipelinesFor(role, pipes)).toBe(pipes);
  expect(emptyWords("to_call").title).toBe("Nobody to call right now");
  expect(emptyWords("all").title).toBe("No leads yet");
});

it("a moved lead leaves a work view it no longer fits", () => {
  const now = new Date(2026, 9, 31, 11, 0).getTime();
  const at = (hours: number) => new Date(now + hours * 3_600_000).toISOString();
  const row = (
    stage: string,
    next: string | null,
    step: string | null = null,
  ) =>
    ({ stage, step, next_action_at: next }) as Pick<
      LeadRow,
      "stage" | "step" | "next_action_at"
    >;
  const toCall = { view: "to_call" as const };
  expect(inWorkView(row("new", null), toCall, now)).toBe(true);
  expect(inWorkView(row("not_connected", at(2)), toCall, now)).toBe(true);
  // A call moved to tomorrow, or a lead won, leaves To Call at once.
  expect(inWorkView(row("not_connected", at(30)), toCall, now)).toBe(false);
  expect(inWorkView(row("won", null), toCall, now)).toBe(false);
  const followUps = { view: "follow_ups" as const };
  expect(inWorkView(row("interested", at(30)), followUps, now)).toBe(true);
  expect(inWorkView(row("interested", null), followUps, now)).toBe(false);
  expect(inWorkView(row("not_connected", at(1)), followUps, now)).toBe(false);
  const overdue = { view: "follow_ups" as const, when: "overdue" as const };
  expect(inWorkView(row("interested", at(-30)), overdue, now)).toBe(true);
  expect(inWorkView(row("interested", at(1)), overdue, now)).toBe(false);
  // The stage pick: a lead moved to another stage leaves it.
  expect(
    inWorkView(row("interested", null, "meeting_done"), { step: "open_leads" }),
  ).toBe(false);
  expect(inWorkView(row("won", null), null)).toBe(true);
});

it("gives the list the whole width until a lead is open (persona QA, 31 Oct 2026)", async () => {
  await act(async () =>
    root.render(
      <WorkSplit pane={null}>
        <p>Rows</p>
      </WorkSplit>,
    ),
  );
  const split = host.firstElementChild as HTMLElement;
  expect(split.hasAttribute("data-pane")).toBe(false);
  expect(split.children).toHaveLength(1);
  await act(async () =>
    root.render(
      <WorkSplit pane={<p>Lead</p>}>
        <p>Rows</p>
      </WorkSplit>,
    ),
  );
  expect(split.hasAttribute("data-pane")).toBe(true);
  expect(split.textContent).toBe("RowsLead");
});

it("sizes the lead beside the list from where it sits, so it ends above the window's bottom (owner, 31 Oct 2026)", async () => {
  let top = 202;
  const real = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    return {
      top,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      x: 0,
      y: top,
      toJSON: () => ({}),
    } as DOMRect;
  };
  try {
    await act(async () =>
      root.render(
        <WorkSplit pane={<p>Lead</p>}>
          <p>Rows</p>
        </WorkSplit>,
      ),
    );
    const pane = Array.from(host.querySelectorAll("p")).find(
      (line) => line.textContent === "Lead",
    )!.parentElement!;
    // At rest, lower on the page.
    expect(pane.style.getPropertyValue("--pane-top")).toBe("202px");
    // Scrolled: pinned under the head.
    top = 102;
    await act(async () => {
      document.dispatchEvent(new Event("scroll"));
      await new Promise((done) =>
        window.requestAnimationFrame(() => done(null)),
      );
    });
    expect(pane.style.getPropertyValue("--pane-top")).toBe("102px");
  } finally {
    HTMLElement.prototype.getBoundingClientRect = real;
  }
});

it("finds a linked stage by its meaning, and never shows a raw key (phone personas, 1 Nov 2026)", async () => {
  const eight = [
    stage("new", "New", "new"),
    stage("follow_up", "Follow-up", "follow_up"),
    stage("interested", "Interested", "interested"),
  ];
  expect(resolveStep(eight, "open_leads")).toBe("follow_up");
  expect(resolveStep(eight, "unworked")).toBe("new");
  expect(resolveStep(eight, "interested")).toBe("interested");
  expect(resolveStep(eight, "demo_done")).toBeNull();
  // An archived stage is no longer in the list.
  expect(resolveStep(STAGES, "old")).toBeNull();
  await act(async () =>
    root.render(
      <StagePicker
        stages={STAGES}
        side="inbound"
        value="demo_done"
        onChange={() => undefined}
      />,
    ),
  );
  expect(host.textContent).not.toContain("demo_done");
  expect(host.textContent).toContain("Demo done");
});

// Phone QA seller day on v1.36 (3 Nov 2026): Inbound's All Leads, which lists
// both sides, said "Call Next Lead · 913", Cold's count. Call Next keeps to
// the side: on All Leads it calls the side's To Call, with that count.
it("calls the side's To Call from All Leads, and each work view's own list elsewhere", async () => {
  expect(callNextView("all")).toBe("to_call");
  expect(callNextView("to_call")).toBe("to_call");
  expect(callNextView("follow_ups")).toBe("follow_ups");
  const counts = { to_call: 4, follow_ups: 3, all: 913 };
  await act(async () =>
    root.render(
      <CallNext
        side="inbound"
        disabled={false}
        onStart={vi.fn()}
        count={counts[callNextView("all")]}
      />,
    ),
  );
  expect(host.textContent).toContain("Call Next Lead · 4");
  expect(host.textContent).not.toContain("913");
});
