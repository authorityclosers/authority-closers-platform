// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { readJourney, type JourneyView } from "./journey/journey-client";
import type { LeadRow } from "./leads-client";
import { PipelineOverview } from "./pipeline-overview";
vi.mock("./journey/journey-client", () => ({ readJourney: vi.fn() }));
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
it("shows this pipeline's own stages and marks only the current stage, without inventing progress", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const stage = (key: string, label: string, archived = false) => ({
    key,
    label,
    archived,
  });
  vi.mocked(readJourney).mockResolvedValue({
    stages: [
      stage("new", "New enquiry"),
      stage("booked", "Visit booked"),
      stage("old", "Old stage", true),
    ],
  } as JourneyView);
  try {
    await act(async () =>
      root.render(
        <PipelineOverview
          name="Enquiries"
          lead={
            {
              lead_id: "fictional-lead",
              pipeline: "enquiries",
              step: "booked",
              stage_label: "Visit booked",
            } as LeadRow
          }
        />,
      ),
    );
    expect(readJourney).not.toHaveBeenCalled();
    await act(async () => {
      const details = host.querySelector("details")!;
      details.open = true;
      details.dispatchEvent(new Event("toggle"));
    });
    expect(readJourney).toHaveBeenCalledWith("enquiries");
    const rows = [...host.querySelectorAll("li")];
    expect(rows).toHaveLength(2);
    expect(rows[0].hasAttribute("aria-current")).toBe(false);
    expect(rows[1].getAttribute("aria-current")).toBe("step");
    expect(rows[1].textContent).toBe("Visit bookedCurrent");
    expect(host.textContent).not.toContain("Old stage");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
