import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import {
  AcquisitionGuideRail,
  AcquisitionLowerPanels,
} from "./acquisition-dashboard-panels";

it("shows only confirmed onboarding progress", () => {
  const empty = renderToStaticMarkup(<AcquisitionGuideRail stage="empty" />);
  const selected = renderToStaticMarkup(<AcquisitionGuideRail stage="selected" />);
  const processing = renderToStaticMarkup(<AcquisitionGuideRail stage="processing" />);

  expect(empty).toContain("0/4");
  expect(selected).toContain("0/4");
  expect(processing).toContain("1/4");
  expect(processing).toContain('aria-valuenow="1"');
  expect(empty).toContain("Illustrative content, not from your calls.");
});

it("renders honest empty call and activity cards until real records are supplied", () => {
  const empty = renderToStaticMarkup(<AcquisitionLowerPanels />);
  expect(empty).toContain("No saved calls yet");
  expect(empty).toContain("No recent activity");
  expect(empty).not.toContain("Discovery Call");

  const filled = renderToStaticMarkup(
    <AcquisitionLowerPanels
      calls={[{ id: "one", title: "A real call", dateLabel: "Today", href: "/calls/one" }]}
      activity={[{ id: "two", kind: "uploaded", title: "A real upload", timeLabel: "Just now" }]}
    />,
  );
  expect(filled).toContain("A real call");
  expect(filled).toContain("A real upload");
  expect(filled).not.toContain("No saved calls yet");
});
