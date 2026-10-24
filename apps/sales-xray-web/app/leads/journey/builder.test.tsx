// @vitest-environment happy-dom
import { Sparkles } from "lucide-react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  TemplateBuilder,
  asksWords,
  movable,
  nextWords,
  placesOf,
} from "./builder";
import type {
  JourneyView,
  StageView,
  TemplatePreview,
  TemplateView,
} from "./journey-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const stage = (
  key: string,
  label: string,
  kind: StageView["kind"],
  extra: Partial<StageView> = {},
): StageView => ({
  key,
  label,
  kind,
  kindWords: kind,
  milestone: "lead",
  meaning: "",
  archived: false,
  origin: "template",
  leads: 0,
  ...extra,
});

const OPEN = [
  "new",
  "not_connected",
  "interested",
  "discussion_incomplete",
  "meeting_scheduled",
  "demo_completed",
];

const PREVIEW: TemplatePreview = {
  template: "inside_sales_demos",
  stages: [
    stage("new", "New Lead", "new", { moves: ["interested", "junk"] }),
    stage("not_connected", "Not Connected", "not_connected", {
      needs: ["nc_reason"],
      milestone: "unreachable",
    }),
    stage("interested", "Interested (In Follow-Up)", "interested", {
      needs: ["next_action"],
      moves: ["discussion_incomplete", "meeting_scheduled"],
      milestone: "qualified",
    }),
    stage("discussion_incomplete", "Discussion Incomplete", "follow_up", {
      needs: ["next_action"],
      milestone: "contacted",
    }),
    stage("meeting_scheduled", "Meeting / Demo Scheduled", "interested", {
      needs: ["meeting"],
      milestone: "appointment_booked",
    }),
    stage("demo_completed", "Demo / Zoom Meeting Completed", "interested", {
      milestone: "appointment_done",
    }),
    stage("won", "Closed / Won", "won", { milestone: "won" }),
    stage("lost", "Closed / Lost", "lost", {
      needs: ["reason"],
      milestone: "lost",
    }),
    stage("junk", "Junk Lead", "junk", {
      needs: ["reason"],
      milestone: "disqualified",
    }),
    stage("contacted", "Contacted", "follow_up", {
      archived: true,
      milestone: "contacted",
    }),
  ],
  landings: [
    {
      fromKey: "contacted",
      fromLabel: "Contacted",
      toKey: "discussion_incomplete",
      toLabel: "Discussion Incomplete",
      leads: 11,
      choices: OPEN,
    },
    {
      fromKey: "new",
      fromLabel: "New enquiry",
      toKey: "new",
      toLabel: "New Lead",
      leads: 4,
      choices: OPEN,
    },
    {
      fromKey: "junk",
      fromLabel: "Junk",
      toKey: "junk",
      toLabel: "Junk Lead",
      leads: 2,
      choices: [],
    },
  ],
};

const VIEW: JourneyView = {
  version: 3,
  industry: "real_estate",
  savedAt: null,
  savedBy: null,
  canEdit: true,
  kinds: {},
  meanings: {},
  stages: [
    stage("new", "New enquiry", "new", { leads: 4 }),
    stage("contacted", "Contacted", "follow_up", {
      leads: 11,
      milestone: "contacted",
    }),
  ],
};

const TEMPLATES: TemplateView[] = [
  {
    id: "real_estate",
    name: "Real estate",
    blurb: "From enquiry to site visit to booking.",
    icon: "building",
    stages: [],
  },
  {
    id: "inside_sales_demos",
    name: "Inside sales with demos",
    blurb: "Call, book a demo, close. Junk kept apart.",
    icon: "phone",
    stages: [],
  },
];

it("says what a stage asks and where a lead goes next", () => {
  expect(asksWords({ needs: ["next_action"] })).toBe("Asks when to follow up");
  expect(asksWords({ needs: [] })).toBeNull();
  const labels = new Map([
    ["interested", "Interested"],
    ["junk", "Junk Lead"],
  ]);
  expect(nextWords({ moves: ["interested", "junk"] }, labels)).toBe(
    "Then Interested · Junk Lead",
  );
  expect(nextWords({ moves: null }, labels)).toBeNull();
});

it("places each stage's leads on its closest stage until one is picked", () => {
  expect(movable(PREVIEW).map((row) => row.fromKey)).toEqual([
    "contacted",
    "new",
  ]);
  expect(placesOf(PREVIEW, {})).toEqual({
    contacted: "discussion_incomplete",
    new: "new",
  });
  expect(placesOf(PREVIEW, { contacted: "interested", new: "won" })).toEqual({
    contacted: "interested",
    new: "new",
  });
  // A stage that means the same comes first: a booked visit is a booked meeting.
  const booked: TemplatePreview = {
    ...PREVIEW,
    stages: PREVIEW.stages.map((item) =>
      item.key === "meeting_scheduled"
        ? { ...item, milestone: "appointment_booked" }
        : item,
    ),
    landings: [
      {
        fromKey: "site_visit_booked",
        fromLabel: "Site visit booked",
        toKey: "interested",
        toLabel: "Interested (In Follow-Up)",
        leads: 5,
        choices: OPEN,
      },
    ],
  };
  expect(
    placesOf(
      booked,
      {},
      new Map([["site_visit_booked", "appointment_booked"]]),
    ),
  ).toEqual({ site_visit_booked: "meeting_scheduled" });
});

let container: HTMLDivElement;
let root: Root;
let sent: { url: string; body: unknown }[];

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      sent.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      const body = url.endsWith("/journey/template/preview")
        ? PREVIEW
        : { ...VIEW, version: 4, industry: "inside_sales_demos" };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

const button = (text: string) =>
  [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  )!;

async function press(text: string) {
  await act(async () => {
    button(text).click();
  });
}

it("walks from a kind of business to saved stages, with today's leads placed", async () => {
  const saved = vi.fn();
  await act(async () =>
    root.render(
      <TemplateBuilder
        view={VIEW}
        templates={TEMPLATES}
        first={false}
        iconFor={() => Sparkles}
        onCancel={() => undefined}
        onSaved={saved}
        onFailed={() => undefined}
      />,
    ),
  );
  expect(container.textContent).toContain("Change your kind of business");
  expect(container.textContent).toContain("Step 1 of 4");

  await press("Inside sales with demos");
  await press("See the stages");
  expect(container.textContent).toContain("The stages you get");
  expect(container.textContent).toContain("Interested (In Follow-Up)");
  expect(container.textContent).toContain("Asks when to follow up");
  expect(container.textContent).not.toContain("Contacted");
  // Where a lead goes next shows on a tap, one stage at a time.
  expect(container.textContent).not.toContain("Then Discussion Incomplete");
  await press("Interested (In Follow-Up)");
  expect(container.textContent).toContain(
    "Then Discussion Incomplete · Meeting / Demo Scheduled",
  );

  await press("Next");
  expect(container.textContent).toContain("Where your leads go");
  expect(container.textContent).toContain("11 leads");
  expect(container.textContent).toContain("Junk leads stay Junk.");
  const select = container.querySelector<HTMLSelectElement>("select")!;
  expect(select.value).toBe("discussion_incomplete");
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )!.set!.call(select, "interested");
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });

  await press("Next");
  expect(container.textContent).toContain("Check and save");
  expect(container.textContent).toContain(
    "11 leads: Contacted → Interested (In Follow-Up)",
  );

  await press("Use these stages");
  const install = sent.find((item) => item.url.endsWith("/journey/template"));
  expect(install?.body).toEqual({
    expectedVersion: 3,
    template: "inside_sales_demos",
    map: { contacted: "interested", new: "new" },
  });
  expect(saved).toHaveBeenCalledTimes(1);
});
