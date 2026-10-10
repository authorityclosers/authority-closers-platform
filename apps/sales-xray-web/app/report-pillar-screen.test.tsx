import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ReportModes } from "./report-modes";
import { REPORT_PILLARS } from "./report-pillars";
import { syntheticReport } from "./review-fixture/report/synthetic-report";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("renders the six Report pillars, eight expandable skills and exact clickable quotes without coaching/profile panels", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const select = vi.fn();
  try {
    await act(async () =>
      root.render(
        <ReportModes
          structure="pillars"
          initialView="reading"
          panels={[
            {
              id: "prospect",
              label: "Old buyer profile",
              content: "full profile content",
            },
          ]}
          documentData={{ report: syntheticReport }}
          onSelectEvidence={select}
        />,
      ),
    );
    expect(
      [...host.querySelectorAll("[data-report-mode-section]")].map((e) =>
        e.getAttribute("data-report-mode-section"),
      ),
    ).toEqual(REPORT_PILLARS.map((p) => p.id));
    expect(
      host.querySelectorAll(
        '[data-report-pillar="skills"] > details[class*="skill"]',
      ),
    ).toHaveLength(8);
    expect(host.textContent).not.toContain("full profile content");
    expect(host.textContent).not.toContain(
      syntheticReport.overview!.practice!.instructions,
    );
    expect(host.textContent).toContain("Not established in this report");
    const source = syntheticReport.strengths[0].evidence[0];
    const button = host.querySelector<HTMLButtonElement>(
      '[data-report-pillar="moments"] button[aria-label^="Play source moment"]',
    )!;
    await act(async () => button.click());
    expect(select).toHaveBeenCalledWith(source, expect.any(String));
    expect(host.querySelector('a[href="/prospects"]')).not.toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
