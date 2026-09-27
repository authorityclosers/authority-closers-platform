import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import {
  AcquisitionGuideRail,
  AcquisitionLowerPanels,
} from "./acquisition-dashboard-panels";

it("shows only confirmed onboarding progress", () => {
  const empty = renderToStaticMarkup(<AcquisitionGuideRail stage="empty" />);
  const selected = renderToStaticMarkup(
    <AcquisitionGuideRail stage="selected" />,
  );
  const processing = renderToStaticMarkup(
    <AcquisitionGuideRail stage="processing" />,
  );

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
      calls={[
        {
          id: "one",
          title: "A real call",
          dateLabel: "Today",
          href: "/calls/one",
        },
      ]}
      activity={[
        {
          id: "two",
          kind: "uploaded",
          title: "A real upload",
          timeLabel: "Just now",
        },
      ]}
    />,
  );
  expect(filled).toContain("A real call");
  expect(filled).toContain("A real upload");
  expect(filled).not.toContain("No saved calls yet");
});

it("shows locally verified multi-file facts without claiming a batch upload", () => {
  const files = [
    { name: "Discovery.m4a", size: 12 * 1048576 },
    { name: "Follow-up.wav", size: 9 * 1048576 },
  ];
  const selected = renderToStaticMarkup(
    <AcquisitionGuideRail
      stage="selected"
      stagedFiles={files}
      maximumFileBytes={32 * 1048576}
    />,
  );

  expect(selected).toContain("Ready to review");
  expect(selected).toContain("2 files added");
  expect(selected).toContain("2 of 2 have a supported extension");
  expect(selected).toContain("2 of 2 are 32 MB or less");
  expect(selected).toContain("One call at a time");
  expect(selected).toContain("give consent before its upload and analysis");
  expect(selected).not.toContain("Total duration");
  expect(selected).not.toContain("2 calls ready to analyse");
});

it("does not mark an unsupported or oversized staged file as validated", () => {
  const selected = renderToStaticMarkup(
    <AcquisitionGuideRail
      stage="selected"
      stagedFiles={[
        { name: "Discovery.m4a", size: 12 * 1048576 },
        { name: "notes.txt", size: 40 * 1048576 },
      ]}
      maximumFileBytes={32 * 1048576}
    />,
  );
  const single = renderToStaticMarkup(
    <AcquisitionGuideRail
      stage="selected"
      stagedFiles={[{ name: "Discovery.m4a", size: 12 * 1048576 }]}
      maximumFileBytes={32 * 1048576}
    />,
  );

  expect(selected).toContain("1 of 2 have a supported extension");
  expect(selected).toContain("1 of 2 are 32 MB or less");
  expect(single).toContain("Get started");
  expect(single).not.toContain("Ready to review");
});
