import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OrganisationRules } from "./rules";
import {
  readTeam,
  saveSettings,
  saveWorkHours,
} from "../../leads/leads-client";
vi.mock("../../leads/routing-rules", () => ({
  RoutingRules: () => (
    <section>
      <header>
        <h2>Match lead rules</h2>
      </header>
      <button>Try a lead</button>
    </section>
  ),
}));
vi.mock("../../leads/seller-sheet", () => ({
  SellerSheet: ({ rep }: { rep: { name: string } | null }) =>
    rep ? (
      <div role="dialog">Areas, languages and products for {rep.name}</div>
    ) : null,
}));
vi.mock("../../leads/team-view", () => ({
  TeamView: () => <div>More settings</div>,
}));
vi.mock("../../call-ai/call-ai-client", () => ({
  readCallAi: () => Promise.resolve(null),
}));
vi.mock("../../leads/leads-client", () => ({
  LeadsError: class LeadsError extends Error {},
  readTeam: vi.fn(),
  saveSettings: vi.fn(),
  saveWorkHours: vi.fn(),
}));
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
vi.mock("./lead-split", () => ({
  useLeadSplit: () => ({
    changed: false,
    valid: true,
    turns: [],
    parts: [],
    save: async () => true,
    discard: () => undefined,
  }),
  LeadSplitCard: () => <section>Who gets new leads</section>,
  Face: () => null,
  perTen: () => "",
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
const team = {
  reps: [
    {
      person_id: "sample",
      name: "Mira Fictional",
      available: true,
      max_open: 25,
    },
  ],
  settings: {
    revision: 7,
    auto_reassign: false,
    reassign_minutes: 35,
    work_hours: {
      days: [0, 1, 2, 3, 4],
      start: "09:30",
      end: "18:30",
      pause_leads: true,
      inside: false,
      next_start: null,
    },
  },
};
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readTeam).mockResolvedValue(
    team as Awaited<ReturnType<typeof readTeam>>,
  );
  vi.mocked(saveSettings).mockResolvedValue({
    ...team,
    settings: { ...team.settings, revision: 8, auto_reassign: true },
  } as Awaited<ReturnType<typeof readTeam>>);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});
async function tap(text: string) {
  const item = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.includes(text),
  );
  expect(item).toBeDefined();
  await act(async () => item!.click());
}
async function open(summary: string) {
  const item = [...host.querySelectorAll("details")].find((details) =>
    details.querySelector("summary")?.textContent?.includes(summary),
  );
  expect(item).toBeDefined();
  await act(async () => {
    item!.open = true;
    item!.dispatchEvent(new Event("toggle"));
  });
}
it("puts every lead rule on one page, with no rows of tabs", async () => {
  // Round-2 board 3 (option C, 20 Nov 2026): the split, the move, the hours
  // and the sellers' switch on one page instead of two rows of tabs.
  await act(async () => root.render(<OrganisationRules />));
  // The only group is the work days' pills: no row of tabs.
  expect(host.querySelector('[role="tablist"]')).toBeNull();
  expect(
    [...host.querySelectorAll('[role="group"]')].map((group) =>
      group.getAttribute("aria-label"),
    ),
  ).toEqual(["Work days"]);
  const text = host.textContent ?? "";
  for (const words of [
    "Who gets new leads",
    "Move untouched leads",
    "Work hours",
    "Sellers can reassign leads",
  ])
    expect(text).toContain(words);
  expect(text.indexOf("Who gets new leads")).toBeLessThan(
    text.indexOf("Move untouched leads"),
  );
});

it("keeps the rules for some leads and each seller's rules one tap down", async () => {
  await act(async () => root.render(<OrganisationRules />));
  expect(host.textContent).not.toContain("Try a lead");
  await open("Rules for some leads");
  expect(host.textContent).toContain("Try a lead");
  expect(host.textContent).not.toContain("All leads");
  await open("areas and limits");
  await tap("Mira Fictional");
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain(
    "Areas, languages",
  );
  expect(saveSettings).not.toHaveBeenCalled();
});
it("keeps every change a draft until the page's one Save, on the saved revision", async () => {
  await act(async () => root.render(<OrganisationRules />));
  expect(
    host.querySelector<HTMLInputElement>('[aria-label="Wait in minutes"]')
      ?.value,
  ).toBe("35");
  // Nothing to save until something changes.
  expect(host.textContent).not.toContain("Save rules");
  const move = host.querySelector<HTMLButtonElement>(
    '[role="switch"][aria-label="Move untouched leads"]',
  )!;
  expect(move.getAttribute("aria-checked")).toBe("false");
  await act(async () => move.click());
  expect(move.getAttribute("aria-checked")).toBe("true");
  expect(saveSettings).not.toHaveBeenCalled();
  await tap("Save rules");
  expect(saveSettings).toHaveBeenCalledWith(7, {
    auto_reassign: true,
    reassign_minutes: 35,
  });
  expect(saveWorkHours).not.toHaveBeenCalled();
});

it("saves work hours on the revision the settings save returned", async () => {
  vi.mocked(saveWorkHours).mockResolvedValue({
    ...team,
    settings: { ...team.settings, revision: 9 },
  } as Awaited<ReturnType<typeof readTeam>>);
  await act(async () => root.render(<OrganisationRules />));
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[role="switch"][aria-label="Sellers can reassign leads"]',
      )!
      .click(),
  );
  await tap("Sat");
  await tap("Save rules");
  expect(saveSettings).toHaveBeenCalledWith(7, {
    auto_reassign: false,
    reassign_minutes: 35,
    sellers_reassign: true,
  });
  expect(saveWorkHours).toHaveBeenCalledWith(8, {
    days: [0, 1, 2, 3, 4, 5],
    start: "09:30",
    end: "18:30",
    pause_leads: true,
    breaks: [],
  });
});

it("holds Save while the hours can't work, and Undo puts everything back", async () => {
  await act(async () => root.render(<OrganisationRules />));
  for (const day of ["Mon", "Tue", "Wed", "Thu", "Fri"]) await tap(day);
  expect(host.textContent).toContain("Pick at least one work day.");
  const save = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Save rules",
  )!;
  expect(save.disabled).toBe(true);
  await tap("Undo");
  expect(host.textContent).not.toContain("Save rules");
  expect(host.textContent).not.toContain("Pick at least one work day.");
});
