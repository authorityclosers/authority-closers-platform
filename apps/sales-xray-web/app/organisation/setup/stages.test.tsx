import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OrganisationStages } from "./stages";
import { notify } from "../../notice-center";
import {
  applyTemplate,
  previewTemplate,
  readJourney,
  readPipelines,
  readTemplates,
  saveStages,
  type TemplatePreview,
} from "../../leads/journey/journey-client";
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
vi.mock("../../leads/journey/journey-view", () => ({
  JourneyTab: () => <div>Advanced setup</div>,
}));
vi.mock("../../leads/journey/ad-platforms", () => ({
  AdPlatforms: () => <div>Ad platform settings</div>,
}));
vi.mock("../../leads/journey/journey-client", async (original) => ({
  ...(await original<typeof import("../../leads/journey/journey-client")>()),
  readJourney: vi.fn(),
  readPipelines: vi.fn(),
  readTemplates: vi.fn(),
  saveStages: vi.fn(),
  previewTemplate: vi.fn(),
  applyTemplate: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
const stage = (
  key: string,
  label: string,
  kind: string,
  milestone: string,
  leads = 0,
  extra: object = {},
) => ({
  key,
  label,
  kind,
  kindWords: kind,
  milestone,
  meaning: milestone,
  archived: false,
  origin: "saved",
  leads,
  visible: true,
  color: null,
  coldLabel: null,
  ...extra,
});
const view = {
  version: 3,
  industry: null,
  savedAt: null,
  savedBy: null,
  canEdit: true,
  kinds: {},
  meanings: {},
  stages: [
    stage("new", "Enquiry", "new", "lead", 1, { coldLabel: "Fresh list" }),
    stage("nc", "No answer", "not_connected", "unreachable"),
    stage("talk", "Talking", "follow_up", "contacted", 2),
    stage("visit", "Visit", "interested", "appointment_booked"),
    stage("won", "Won", "won", "won", 3),
    stage("lost", "Lost", "lost", "lost", 1),
  ],
};
const copy = () => JSON.parse(JSON.stringify(view));
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readJourney).mockResolvedValue(copy());
  vi.mocked(readPipelines).mockResolvedValue({
    pipelines: [],
    sources: {},
    canEdit: true,
  });
  vi.mocked(readTemplates).mockResolvedValue([
    {
      id: "recommended",
      name: "Recommended",
      blurb: "",
      icon: "spark",
      stages: [{ label: "New Lead", kind: "new", milestone: "lead" }],
    },
  ]);
  vi.mocked(saveStages).mockResolvedValue({ ...copy(), version: 4 });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});
const button = (name: string) =>
  [...host.querySelectorAll("button")].find(
    (item) =>
      item.getAttribute("aria-label") === name || item.textContent === name,
  );
// Saves run one after another on a promise chain: let it finish.
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
async function tap(name: string, item = button(name)) {
  expect(item, name).toBeDefined();
  await act(async () => item!.click());
  await settle();
}
const starting = (words: string) =>
  [...host.querySelectorAll("button")].find(
    (item) =>
      item.textContent?.startsWith(words) && !item.getAttribute("aria-label"),
  );
async function enter(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const sent = () => vi.mocked(saveStages).mock.calls.at(-1)!;
const byKey = (key: string) => sent()[1].find((item) => item.key === key);

it("saves a new name at once and offers Undo", async () => {
  await act(async () => root.render(<OrganisationStages />));
  expect(host.textContent).toContain("Enquiry");
  expect(saveStages).not.toHaveBeenCalled();
  await tap("Rename Talking");
  await enter(
    host.querySelector<HTMLInputElement>('input[aria-label="Stage name"]')!,
    "Visit booked",
  );
  await tap("Done");
  expect(saveStages).toHaveBeenCalledTimes(1);
  expect(sent()[0]).toBe(3);
  expect(sent()[2]).toBe("main");
  expect(byKey("talk")).toMatchObject({
    label: "Visit booked",
    kind: "follow_up",
    milestone: "contacted",
  });
  const saved = vi
    .mocked(notify)
    .mock.calls.map(([notice]) => notice)
    .find((notice) => notice.action?.label === "Undo");
  expect(saved?.title).toBe("Renamed Visit booked");
  await act(async () => saved!.action!.run());
  await settle();
  expect(saveStages).toHaveBeenCalledTimes(2);
  // Undo saves the list as it was, on the version the first save made.
  expect(sent()[0]).toBe(4);
  expect(byKey("talk")?.label).toBe("Talking");
});

it("names the first stage on both sides and previews either side", async () => {
  await act(async () => root.render(<OrganisationStages />));
  expect(host.textContent).toContain("Cold Leads: Fresh list");
  const preview = () =>
    host.querySelector('[aria-label^="What sellers see"]')!.textContent;
  expect(preview()).toContain("Enquiry");
  await tap("Cold");
  expect(preview()).toContain("Fresh list");
  expect(preview()).not.toContain("Enquiry");
  await tap("Rename Enquiry");
  await enter(
    host.querySelector<HTMLInputElement>(
      'input[aria-label="Cold Leads name"]',
    )!,
    "Unworked",
  );
  await tap("Done");
  expect(byKey("new")).toMatchObject({
    label: "Enquiry",
    coldLabel: "Unworked",
  });
});

it("hides a stage from sellers, never the first one", async () => {
  await act(async () => root.render(<OrganisationStages />));
  expect(button("Sellers see Enquiry")?.disabled).toBe(true);
  await tap("Sellers see Talking");
  expect(byKey("talk")?.visible).toBe(false);
  expect(byKey("new")?.visible).toBe(true);
});

it("moves a stage with the keyboard and keeps the first stage first", async () => {
  await act(async () => root.render(<OrganisationStages />));
  expect(button("Enquiry stays first")?.disabled).toBe(true);
  const grip = button("Move Visit")!;
  await act(async () => {
    grip.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }),
    );
  });
  await settle();
  expect(sent()[1].map((item) => item.key)).toEqual([
    "new",
    "nc",
    "visit",
    "talk",
    "won",
    "lost",
  ]);
});

it("asks where a removed stage's leads go and moves them there", async () => {
  await act(async () => root.render(<OrganisationStages />));
  await tap("More for Talking");
  await tap("Remove stage");
  expect(saveStages).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Where do the 2 leads go?");
  // Never back into the first stage.
  expect(button("Enquiry")).toBeUndefined();
  await tap("Visit", starting("Visit"));
  expect(byKey("talk")?.archived).toBe(true);
  expect(sent()[3]).toEqual({ talk: "visit" });
});

it("changes a stage's meaning and adds a ready stage before Won", async () => {
  await act(async () => root.render(<OrganisationStages />));
  await tap("Meaning of Visit: Meeting");
  await tap("Interested");
  expect(byKey("visit")).toMatchObject({
    kind: "interested",
    milestone: "qualified",
  });
  await tap("Add stage");
  await tap("Payment pending", starting("Payment pending"));
  const order = sent()[1].map((item) => item.key ?? item.label);
  expect(order.indexOf("Payment pending")).toBe(order.indexOf("won") - 1);
  expect(
    sent()[1].find((item) => item.label === "Payment pending"),
  ).toMatchObject({
    kind: "interested",
    milestone: "negotiation",
  });
});

it("uses the recommended stages, sending each stage's leads by meaning", async () => {
  vi.mocked(previewTemplate).mockResolvedValue({
    template: "recommended",
    stages: [
      stage("new", "New Lead", "new", "lead"),
      stage("open_leads", "Open Leads", "follow_up", "contacted"),
      stage(
        "meeting_scheduled",
        "Meeting Scheduled",
        "interested",
        "appointment_booked",
      ),
    ],
    landings: [
      {
        fromKey: "talk",
        fromLabel: "Talking",
        toKey: "new",
        toLabel: "New Lead",
        leads: 2,
        choices: ["new", "open_leads", "meeting_scheduled"],
      },
    ],
  } as TemplatePreview);
  vi.mocked(applyTemplate).mockResolvedValue({ ...copy(), version: 5 });
  await act(async () => root.render(<OrganisationStages />));
  await tap("Use recommended");
  const confirm = [...host.querySelectorAll("button")].filter(
    (item) => item.textContent === "Use recommended",
  );
  await tap("Use recommended", confirm.at(-1));
  expect(applyTemplate).toHaveBeenCalledWith(3, "recommended", "main", {
    talk: "open_leads",
  });
});
