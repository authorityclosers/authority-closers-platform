import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { AcquisitionProcessingPanel } from "./acquisition-processing-panel";

it("shows only stage completion supplied by confirmed processing rows", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      stageRows={[
        { stage: "C2", state: "completed", label: "Complete" },
        { stage: "C4", state: "running", label: "In progress" },
        { stage: "C5", state: null, label: "Not started" },
      ]}
      statusText="Checking the conversation"
      fileName="My call.m4a"
      fileMeta="M4A · 12.4 MB"
    />,
  );

  expect(markup).toContain('aria-label="Listening: Complete"');
  expect(markup).toContain('aria-label="Understanding: In progress"');
  expect(markup).toContain('aria-current="step"');
  expect(markup).toContain('data-state="completed"');
  expect(markup).toContain('data-state="active"');
  expect(markup).toContain("My call.m4a");
  expect(markup).toContain("M4A · 12.4 MB");
  expect(markup).toContain("Checking the conversation");
  expect(markup).not.toContain("1–3 minutes");
});

it("halts activity treatment for a held state and does not invent allowance or file details", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      stageRows={[{ stage: "C2", state: "held", label: "Needs attention" }]}
      statusText="Analysis paused"
      paused
    />,
  );

  expect(markup).toContain('data-paused="true"');
  expect(markup).toContain('data-animated="false"');
  expect(markup).toContain("Needs attention");
  expect(markup).toContain("Your recording");
  expect(markup).not.toContain("Unlimited testing");
  expect(markup).not.toContain("12.4 MB");
  expect(markup).not.toContain('aria-current="step"');
});
