import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OrganisationStages } from "./stages";
import {
  readJourney,
  readPipelines,
  readTemplates,
  saveJourney,
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
  saveJourney: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
const view = {
  version: 3,
  industry: null,
  savedAt: null,
  savedBy: null,
  canEdit: true,
  kinds: { new: "New", follow_up: "In talks", won: "Won", lost: "Lost" },
  meanings: {},
  stages: [
    {
      key: "new",
      label: "Enquiry",
      kind: "new",
      kindWords: "New",
      milestone: "lead",
      meaning: "An enquiry",
      archived: false,
      origin: "saved",
      leads: 1,
    },
    {
      key: "talk",
      label: "Talking",
      kind: "follow_up",
      kindWords: "In talks",
      milestone: "contact",
      meaning: "Talks started",
      archived: false,
      origin: "saved",
      leads: 2,
    },
    {
      key: "won",
      label: "Won",
      kind: "won",
      kindWords: "Won",
      milestone: "sale",
      meaning: "A sale",
      archived: false,
      origin: "saved",
      leads: 3,
    },
    {
      key: "lost",
      label: "Lost",
      kind: "lost",
      kindWords: "Lost",
      milestone: "lost",
      meaning: "Closed",
      archived: false,
      origin: "saved",
      leads: 1,
    },
  ],
} as const;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readJourney).mockResolvedValue(JSON.parse(JSON.stringify(view)));
  vi.mocked(readPipelines).mockResolvedValue({
    pipelines: [],
    sources: {},
    canEdit: true,
  });
  vi.mocked(readTemplates).mockResolvedValue([]);
  vi.mocked(saveJourney).mockResolvedValue(JSON.parse(JSON.stringify(view)));
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
it("puts saved stage controls first and preserves meanings until an explicit save", async () => {
  await act(async () => root.render(<OrganisationStages />));
  expect(host.textContent).toContain("Enquiry");
  expect(host.textContent).not.toContain("How lead stages work");
  expect(saveJourney).not.toHaveBeenCalled();
  await tap("Talking");
  const input = host.querySelector<HTMLInputElement>('input[maxlength="40"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Visit booked");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await tap("Apply name");
  expect(saveJourney).not.toHaveBeenCalled();
  await tap("Save stages");
  expect(saveJourney).toHaveBeenCalledWith(
    3,
    expect.arrayContaining([
      expect.objectContaining({
        key: "talk",
        label: "Visit booked",
        kind: "follow_up",
        milestone: "contact",
      }),
    ]),
    "main",
  );
});
it("keeps the initial stage's order protected", async () => {
  await act(async () => root.render(<OrganisationStages />));
  // The arrows wait behind Reorder, so the list reads as one calm list.
  expect(host.querySelector('[aria-label="Move Enquiry later"]')).toBeNull();
  await tap("Reorder");
  expect(
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Done")
      ?.getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    host.querySelector<HTMLButtonElement>('[aria-label="Move Enquiry earlier"]')
      ?.disabled,
  ).toBe(true);
  expect(
    host.querySelector<HTMLButtonElement>('[aria-label="Move Enquiry later"]')
      ?.disabled,
  ).toBe(true);
  expect(
    host.querySelector<HTMLButtonElement>('[aria-label="Move Lost later"]')
      ?.disabled,
  ).toBe(true);
});
