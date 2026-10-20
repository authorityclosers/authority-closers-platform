// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  FIXTURE_POINTERS,
  ReportPreview,
  notInAppYet,
  shownPointers,
} from "./report-preview";
import { IndustryDefault, VersionEditor } from "./report-settings";
import {
  industryName,
  normalizeReportSettings,
  withValue,
  type Parameter,
} from "./report-settings-data";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const V1 = {
  report: {
    style: "guided",
    complexity: "standard",
    parts: { overview: true, analysis: true, outcome: true },
    pointers: FIXTURE_POINTERS.map((pointer) => pointer.id),
    max_pointers: 27,
    show_scores: true,
    show_evidence: true,
    show_how_to_improve: true,
  },
  prospect: {
    enabled: true,
    complexity: "standard",
    sections: Object.fromEntries(
      [
        "quality",
        "chips",
        "facts",
        "problem",
        "wants",
        "blockers",
        "personal",
        "follow_up",
        "next_action",
        "buyer_info",
      ].map((key) => [key, true]),
    ),
    show_inferred: true,
  },
  coaching: {
    enabled: true,
    complexity: "standard",
    show_moments: true,
    max_moments: 5,
    show_across_calls: true,
    tone: "supportive",
  },
};

const PARAMETERS: Parameter[] = [
  {
    key: "report.style",
    surface: "report",
    label: "Report style",
    help: "",
    kind: "choice",
    choices: [
      { value: "guided", label: "Guided" },
      { value: "compact", label: "Compact" },
      { value: "scorecard", label: "Scorecard" },
    ],
    minimum: null,
    maximum: null,
    applies: "display",
    inApp: false,
    tunable: true,
    signals: [],
  },
  {
    key: "report.parts.outcome",
    surface: "report",
    label: "Final Call Outcome",
    help: "",
    kind: "toggle",
    choices: [],
    minimum: null,
    maximum: null,
    applies: "display",
    inApp: true,
    tunable: false,
    signals: [],
  },
];

const html = (settings: Record<string, unknown>) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <ReportPreview settings={settings} baseline={V1} parameters={PARAMETERS} />,
  );
  return host;
};

it("shows version 1 whole: three parts, all 27 pointers, every section, five moments", () => {
  const host = html(V1);
  expect(host.textContent).toContain("a fictional rooftop-solar call");
  expect(host.textContent).toContain("64 / 100");
  expect(host.textContent).toContain("27 of 27 pointers");
  expect(host.textContent).toContain("Final Call Outcome");
  expect(
    host.querySelectorAll('[aria-label="Prospect preview"] dt'),
  ).toHaveLength(10);
  expect(
    host.querySelectorAll('[aria-label="Coaching preview"] li'),
  ).toHaveLength(5);
  expect(host.querySelector('[role="note"]')).toBeNull();
});

it("follows the style, detail, pointer list and toggles of a version", () => {
  let settings = withValue(V1, "report.style", "scorecard");
  settings = withValue(settings, "report.max_pointers", 5);
  settings = withValue(settings, "report.show_scores", false);
  settings = withValue(settings, "report.parts.outcome", false);
  settings = withValue(settings, "prospect.show_inferred", false);
  settings = withValue(settings, "coaching.tone", "direct");
  settings = withValue(settings, "coaching.max_moments", 2);
  const host = html(settings);
  expect(host.textContent).toContain("5 of 27 pointers");
  expect(host.textContent).not.toContain("64 / 100");
  expect(host.textContent).not.toContain("Final Call Outcome");
  expect(
    host.querySelectorAll('[aria-label="Prospect preview"] dt'),
  ).toHaveLength(8);
  expect(host.textContent).toContain("You skipped it here");
  expect(
    host.querySelectorAll('[aria-label="Coaching preview"] li'),
  ).toHaveLength(2);
  // The style isn't in the app yet: the preview says so; the parts are.
  expect(host.querySelector('[role="note"]')?.textContent).toContain(
    "Not in the app yet: Report style.",
  );
  expect(
    shownPointers(
      withValue(V1, "report.pointers", ["pricing", "x", "call_opening"]),
    ).map((pointer) => pointer.id),
  ).toEqual(["pricing", "call_opening"]);
  expect(
    notInAppYet(withValue(V1, "report.parts.outcome", false), V1, PARAMETERS),
  ).toEqual([]);
  const simple = html(withValue(V1, "report.complexity", "simple"));
  expect(simple.querySelector("q")).toBeNull(); // simple shows no evidence or tips
  expect(html(withValue(V1, "prospect.enabled", false)).textContent).toContain(
    "The Prospect tab is off.",
  );
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const DATA = normalizeReportSettings({
  parameters: [],
  versions: [
    { number: 1, label: "Version 1 · today's report", settings: V1 },
    { number: 2, label: "Compact", base_number: 1, settings: V1 },
  ],
  general_version_number: 2,
  industry_profiles: [
    { id: "real_estate", name: "Real estate" },
    { id: "home_services", name: "Home services & solar" },
  ],
});

const button = (text: string) =>
  [...host.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  )!;

async function typeInto(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("names industries from the lead-stage profiles", async () => {
  expect(DATA.industryProfiles).toHaveLength(2);
  expect(industryName("home_services", DATA.industryProfiles)).toBe(
    "Home services & solar",
  );
  expect(industryName("unknown_id", DATA.industryProfiles)).toBe("unknown_id");
  expect(industryName(null, DATA.industryProfiles)).toBeNull();
  await act(async () =>
    root.render(
      <IndustryDefault
        versions={DATA.versions}
        profiles={DATA.industryProfiles}
      />,
    ),
  );
  const options = [
    ...host.querySelectorAll('select[aria-label="Industry"] option'),
  ];
  expect(options.map((option) => option.textContent)).toEqual([
    "Choose an industry",
    "Real estate",
    "Home services & solar",
  ]);
  expect(button("Set industry default").disabled).toBe(true);
});

it("saves and publishes a version to everyone in one go, with the default it saw", async () => {
  const fetcher = vi.fn(
    async (path: string) =>
      new Response(
        JSON.stringify(
          path.endsWith("/versions") ? { number: 3 } : { version_number: 3 },
        ),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <VersionEditor
        parameters={DATA.parameters}
        versions={DATA.versions}
        profiles={DATA.industryProfiles}
        generalVersionNumber={2}
      />,
    ),
  );
  await act(async () => button("New version").click());
  expect(
    host.querySelector('[aria-label="Preview on a fictional call"]'),
  ).not.toBeNull();
  await typeInto(
    host.querySelector<HTMLInputElement>('input[aria-label="Version name"]')!,
    "Shorter report",
  );
  await act(async () => button("Save and publish to everyone").click());
  const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
  expect(calls.map(([path]) => path)).toEqual([
    "/v1/admin/conversation/report-settings/versions",
    "/v1/admin/conversation/report-settings/choices",
  ]);
  expect(JSON.parse(String(calls[1][1].body))).toEqual({
    scope: "general",
    version_number: 3,
    expected_version_number: 2,
    reason: "Published version 3",
  });
  expect(refresh).toHaveBeenCalled();
  expect(button("New version")).toBeDefined(); // the editor closed
});
