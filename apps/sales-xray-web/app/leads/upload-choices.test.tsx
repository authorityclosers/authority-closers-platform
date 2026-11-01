import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { RepView } from "./leads-client";
import { firstChoices, type UploadChoices } from "./bulk-upload";
import {
  overLimitLines,
  sharesLine,
  UploadChoicesFields,
} from "./upload-choices";
import { readJourney } from "./journey/journey-client";

vi.mock("./journey/journey-client", async (original) => ({
  ...(await original<typeof import("./journey/journey-client")>()),
  readJourney: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
// The choices as the fields last changed them.
const changes = vi.fn<(value: UploadChoices) => void>();
const seen = () => changes.mock.calls.at(-1)![0];
const team = [
  { person_id: "p1", name: "asha example" },
  { person_id: "p2", name: "ravi sample" },
] as RepView[];
const stage = (
  key: string,
  label: string,
  kind: string,
  milestone: string,
) => ({
  key,
  label,
  kind,
  milestone,
  archived: false,
  coldLabel: key === "new" ? "Unworked" : null,
});

function Harness({ canManage }: { canManage: boolean }) {
  const [value, setValue] = useState(() => firstChoices(canManage));
  return (
    <UploadChoicesFields
      canManage={canManage}
      team={team}
      fresh={5}
      pipeline=""
      value={value}
      onChange={(next) => {
        setValue(next);
        changes(next);
      }}
    />
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readJourney).mockResolvedValue({
    stages: [
      stage("new", "New Lead", "new", "lead"),
      stage("open_leads", "Open Leads", "follow_up", "contacted"),
      stage("interested", "Interested", "interested", "qualified"),
      stage("won", "Won", "won", "won"),
    ],
  } as never);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});
// The stages arrive from a read: let it finish.
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const tap = async (words: string) => {
  const found = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === words,
  );
  expect(found, words).toBeDefined();
  await act(async () => found!.click());
};

it("splits new leads evenly among the salespeople picked and says what's left", async () => {
  await act(async () => root.render(<Harness canManage />));
  await settle();
  await tap("Salespeople I pick");
  const counts = [
    ...host.querySelectorAll<HTMLInputElement>('input[type="number"]'),
  ];
  expect(counts.map((input) => input.value)).toEqual(["3", "2"]);
  expect(host.textContent).toContain("Asha Example");
  expect(host.textContent).toContain("Every new lead has a salesperson.");
  // One person off: the other takes all five.
  const boxes = host.querySelectorAll<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  await act(async () => boxes[1].click());
  expect(seen().off).toEqual(["p2"]);
  expect(sharesLine(seen(), team, 5)).toBe("Asha Example 5.");
  // More than there are is said plainly.
  const asha = host.querySelector<HTMLInputElement>(
    'input[aria-label="New leads for Asha Example"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(asha, "7");
    asha.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).toContain("That's 2 more than the 5 new leads.");
});

it("offers the first stage by its Cold name, Open Leads and Interested", async () => {
  await act(async () => root.render(<Harness canManage={false} />));
  await settle();
  expect(host.textContent).toContain("They go on your desk.");
  const group = host.querySelector('[aria-label="Starting stage"]')!;
  expect(
    [...group.querySelectorAll("button")].map((item) => item.textContent),
  ).toEqual(["Unworked", "Open Leads", "Interested"]);
  await tap("Open Leads");
  expect(seen().step).toBe("open_leads");
  await tap("Inbound Leads");
  expect(seen().side).toBe("live");
  expect(group.textContent).toContain("New Lead");
});

it("says where the leads go in a line for each choice", () => {
  const base = firstChoices(true);
  expect(sharesLine(base, team, 5)).toBe("Given out by the lead rules.");
  expect(sharesLine({ ...base, assign: "none" }, team, 5)).toBe(
    "All 5 stay unassigned.",
  );
  expect(
    sharesLine(
      { ...base, assign: "people", counts: { p1: 2, p2: 1 } },
      team,
      5,
    ),
  ).toBe("Asha Example 2 · Ravi Sample 1 · 2 unassigned.");
});

// ph1-17 (phone personas, 1 Nov 2026): the limit warning came only after.
it("says before the import who it takes past their limit", () => {
  const priya = {
    person_id: "p",
    name: "priya fictional",
    max_open: 50,
    open_leads: 2,
  } as RepView;
  const choices = {
    side: "inbound",
    assign: "people",
    off: [],
    counts: null,
  } as unknown as UploadChoices;
  expect(overLimitLines(choices, [priya], 900)).toEqual([
    "Priya Fictional would have 902 open leads, 852 over the limit of 50.",
  ]);
  expect(overLimitLines(choices, [{ ...priya, max_open: null }], 900)).toEqual(
    [],
  );
});

it("never warns for a Cold list: the limit counts Inbound only (ph1-17)", () => {
  const priya = {
    person_id: "p",
    name: "priya fictional",
    max_open: 50,
    open_leads: 2,
  } as RepView;
  const cold = {
    side: "cold",
    assign: "people",
    off: [],
    counts: null,
  } as unknown as UploadChoices;
  expect(overLimitLines(cold, [priya], 900)).toEqual([]);
});
