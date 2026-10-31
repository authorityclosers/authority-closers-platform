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
    stage("talk", "Talking", "follow_up", "contacted", 2),
    stage("nc", "No answer", "not_connected", "unreachable"),
    stage("visit", "Visit", "interested", "appointment_booked"),
    stage("won", "Won", "won", "won", 3),
    stage("lost", "Lost", "lost", "lost", 1),
  ],
};
const copy = () => JSON.parse(JSON.stringify(view));
const recommended = (labels: string[]) => [
  {
    id: "recommended",
    name: "Recommended",
    blurb: "",
    icon: "spark",
    stages: labels.map((label) => ({
      label,
      kind: "new" as const,
      milestone: "lead",
    })),
  },
];
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
  vi.mocked(readTemplates).mockResolvedValue(recommended(["New Lead"]));
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
async function enter(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function leave(input: HTMLInputElement) {
  await act(async () => {
    input.focus();
    input.blur();
  });
  await settle();
}
const sent = () => vi.mocked(saveStages).mock.calls.at(-1)!;
const byKey = (key: string) => sent()[1].find((item) => item.key === key);
const render = async () => {
  await act(async () => root.render(<OrganisationStages />));
  await settle();
};

it("keeps the screen to a title, one line, the preview and plain rows", async () => {
  await render();
  expect(host.querySelector("h2")?.textContent).toBe("Lead stages");
  expect(host.textContent).toContain("What your sellers see");
  for (const word of [
    "journey",
    "pipeline",
    "meaning",
    "kind",
    "template",
    "step",
  ])
    expect(host.textContent?.toLowerCase()).not.toContain(word);
  // No counts, chips or help on the rows: the name, and the Cold name beside the first.
  const rows = host.querySelectorAll('[aria-label="Your lead stages"] > li');
  expect(rows).toHaveLength(6);
  expect(button("Rename Enquiry")?.textContent).toBe("EnquiryFresh list");
  expect(button("Rename Talking")?.textContent).toBe("Talking");
  expect(host.textContent).not.toMatch(/\d+ leads?/);
});

it("saves a new name at once and offers Undo", async () => {
  await render();
  await tap("Rename Talking");
  const input = host.querySelector<HTMLInputElement>(
    'input[aria-label="Stage name"]',
  )!;
  await enter(input, "Visit booked");
  await leave(input);
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
  expect(saved?.title).toBe("Renamed");
  await act(async () => saved!.action!.run());
  await settle();
  expect(saveStages).toHaveBeenCalledTimes(2);
  // Undo saves the list as it was, on the version the first save made.
  expect(sent()[0]).toBe(4);
  expect(byKey("talk")?.label).toBe("Talking");
});

it("previews either side and names the first stage on Cold from More", async () => {
  // A phone: the preview starts folded, so the stages come first; one tap opens it.
  const phone = vi
    .spyOn(window, "matchMedia")
    .mockReturnValue({ matches: false } as MediaQueryList);
  await render();
  phone.mockRestore();
  expect(host.querySelector('[aria-label^="What sellers see"]')).toBeNull();
  await tap("Preview what sellers see");
  const preview = () =>
    host.querySelector('[aria-label^="What sellers see"]')!.textContent;
  expect(preview()).toContain("Enquiry");
  await tap("Cold Leads");
  expect(preview()).toContain("Fresh list");
  expect(preview()).not.toContain("Enquiry");
  await tap("More for Enquiry");
  const cold = [...host.querySelectorAll("label")]
    .find((item) => item.textContent?.startsWith("Name on Cold Leads"))!
    .querySelector("input")!;
  await enter(cold, "Unworked");
  await leave(cold);
  expect(byKey("new")).toMatchObject({
    label: "Enquiry",
    coldLabel: "Unworked",
  });
});

it("hides a stage from sellers, never the first one", async () => {
  await render();
  expect(button("Sellers see Enquiry")?.disabled).toBe(true);
  await tap("Sellers see Talking");
  expect(byKey("talk")?.visible).toBe(false);
  expect(byKey("new")?.visible).toBe(true);
});

it("moves a stage with the keyboard and keeps the first stage first", async () => {
  await render();
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
    "talk",
    "visit",
    "nc",
    "won",
    "lost",
  ]);
});

it("removing a stage with leads asks where they go and moves them there", async () => {
  await render();
  await tap("More for Talking");
  await tap("Remove stage");
  expect(saveStages).not.toHaveBeenCalled();
  expect(host.textContent).toContain("Move 2 leads to");
  // Never back into the first stage.
  const choices = [...host.querySelectorAll("button")].filter(
    (item) =>
      !item.getAttribute("aria-label") &&
      ["No answer", "Visit", "Enquiry"].includes(item.textContent ?? ""),
  );
  expect(choices.map((item) => item.textContent)).toEqual([
    "No answer",
    "Visit",
  ]);
  await tap("Visit", choices[1]);
  expect(byKey("talk")?.archived).toBe(true);
  expect(sent()[3]).toEqual({ talk: "visit" });
});

it("changes what a stage counts as and adds a ready stage before Won", async () => {
  await render();
  await tap("More for Visit");
  await tap("Interested");
  expect(byKey("visit")).toMatchObject({
    kind: "interested",
    milestone: "qualified",
  });
  await tap("Payment pending");
  const order = sent()[1].map((item) => item.key ?? item.label);
  expect(order.indexOf("Payment pending")).toBe(order.indexOf("won") - 1);
  expect(
    sent()[1].find((item) => item.label === "Payment pending"),
  ).toMatchObject({ kind: "interested", milestone: "negotiation" });
});

it("offers the recommended stages only when the list differs, by matching stage", async () => {
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
  await render();
  await tap("Use recommended");
  const confirm = [...host.querySelectorAll("button")].filter(
    (item) => item.textContent === "Use recommended",
  );
  await tap("Use recommended", confirm.at(-1));
  expect(applyTemplate).toHaveBeenCalledWith(3, "recommended", "main", {
    talk: "open_leads",
  });
});

it("hides Use recommended when the list is the recommended one", async () => {
  vi.mocked(readTemplates).mockResolvedValue(
    recommended(view.stages.map((item) => item.label)),
  );
  await render();
  expect(button("Use recommended")).toBeUndefined();
});
