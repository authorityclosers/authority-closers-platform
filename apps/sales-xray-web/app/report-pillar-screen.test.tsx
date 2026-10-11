import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ReportModes } from "./report-modes";
import { REPORT_PILLARS } from "./report-pillars";
import {
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let cleanup: (() => void) | null = null;
afterEach(() => {
  cleanup?.();
  cleanup = null;
});

async function mount(
  report: typeof amitReport,
  transcript?: typeof amitTranscript,
) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const select = vi.fn();
  await act(async () =>
    root.render(
      <ReportModes
        structure="pillars"
        initialView="story"
        panels={[
          {
            id: "prospect",
            label: "Old buyer profile",
            content: "full profile content",
          },
        ]}
        documentData={{ report, transcript }}
        onSelectEvidence={select}
      />,
    ),
  );
  cleanup = () => {
    act(() => root.unmount());
    host.remove();
  };
  return { host, select };
}

const pillar = (host: HTMLElement, id: string) =>
  host.querySelector<HTMLElement>(`[data-report-pillar="${id}"]`)!;

it("tells the call as six pillars in the spec's order, without profile or coaching panels", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  expect(
    [...host.querySelectorAll("[data-report-mode-section]")].map((e) =>
      e.getAttribute("data-report-mode-section"),
    ),
  ).toEqual(REPORT_PILLARS.map((p) => p.id));
  expect(host.textContent).not.toContain("full profile content");
  // Practice exercises belong to Coaching, not the Report.
  expect(host.textContent).not.toContain(
    amitReport.overview!.practice!.instructions,
  );
  const picture = pillar(host, "overview").textContent;
  expect(picture).toContain("Follow-up Set");
  expect(picture).toContain("As heard on the call");
  expect(picture).toContain("Strongest part");
  expect(picture).toContain("Biggest concern");
  expect(picture).toContain("Next step");
  expect(picture).not.toContain("This report doesn't cover");
});

it("plays the exact quoted moment from any pillar", async () => {
  const { host, select } = await mount(amitReport, amitTranscript);
  const strongest = amitReport.strengths[0].evidence[0];
  const button = pillar(host, "overview").querySelector<HTMLButtonElement>(
    'button[aria-label="Play 18:42: Strongest part"]',
  )!;
  await act(async () => button.click());
  expect(select).toHaveBeenCalledWith(strongest, "Strongest part");
});

it("shows eight compact skill rows that expand to evidence and Coaching", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  const skills = pillar(host, "skills");
  const rows = skills.querySelectorAll("details > summary");
  // Eight skills plus the collapsed deeper analysis.
  expect(rows).toHaveLength(9);
  expect(rows[0].textContent).toContain("Human Connection & Trust");
  expect(rows[0].textContent).toContain("Strongly Demonstrated");
  expect(rows[1].textContent).toContain("Needs Attention");
  expect(skills.querySelectorAll('a[href^="/coaching?focus="]')).toHaveLength(
    8,
  );
  expect(skills.textContent).toContain("Explore deeper analysis");
});

it("keeps moments to five, then shows all on request", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  const moments = pillar(host, "missed");
  expect(moments.querySelectorAll("ol > li").length).toBeLessThanOrEqual(5);
  const more = [...moments.querySelectorAll("button")].find((b) =>
    b.textContent?.startsWith("View all"),
  );
  expect(more).toBeDefined();
  await act(async () => more!.click());
  expect(moments.querySelectorAll("ol > li").length).toBeGreaterThan(5);
  expect(moments.textContent).toContain("Important Miss");
  expect(moments.textContent).toContain("You moved toward");
  expect(moments.textContent).toContain("What was missed");
});

it("ends where the deal stands, with links to the prospect and Coaching", async () => {
  const { host } = await mount(amitReport, amitTranscript);
  const deal = pillar(host, "facts");
  expect(deal.textContent).toContain("Commitment quality");
  expect(deal.textContent).toContain("Clear");
  expect(deal.textContent).toContain("Friday · 4:00 PM");
  expect(deal.textContent).toContain("Still needs to become clear");
  expect(deal.querySelector('a[href="/prospects"]')).not.toBeNull();
  expect(deal.textContent).toContain("View Prospect Information");
  expect(deal.textContent).toContain("View Personalized Coaching");
  // The end strip names the next event, not just "Agreed".
  expect(
    deal.querySelector('dl[aria-label="Report summary"]')?.textContent,
  ).toContain("Friday · 4:00 PM");
});

it("opens a sparse older report with honest, one-line gaps", async () => {
  const { host } = await mount(syntheticReport);
  const picture = pillar(host, "overview");
  expect(picture.textContent).toContain("Outcome not recorded");
  expect(picture.textContent).toContain("Only a person records won or lost");
  expect(picture.textContent).toContain("This report doesn't cover:");
  expect(
    pillar(host, "skills").querySelectorAll("details > summary").length,
  ).toBeGreaterThanOrEqual(8);
  // Never invents a strength or a next event to fill the page.
  expect(pillar(host, "facts").textContent).toContain("Next event date");
});
