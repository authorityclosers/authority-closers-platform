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

  expect(markup).toContain('aria-label="Transcribing your call: Complete"');
  expect(markup).toContain(
    'aria-label="Checking the conversation: In progress"',
  );
  expect(markup).toContain('aria-current="step"');
  expect(markup).toContain('data-state="completed"');
  expect(markup).toContain('data-state="running"');
  expect(markup).toContain('data-stage="C4"');
  expect(markup).toContain("My call.m4a");
  expect(markup).toContain("M4A · 12.4 MB");
  expect(markup).toContain("Checking the conversation");
  expect(markup).not.toContain("1–3 minutes");
});

it("halts activity treatment for a held state and does not invent allowance or file details", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      stageRows={[
        { stage: "C2", state: "completed", label: "Complete" },
        { stage: "C4", state: "uncertain", label: "Paused · needs attention" },
      ]}
      statusText="Analysis paused"
      paused
      submissionId="call-one"
      progress={{
        state: "held",
        local_state: "completed",
        failure_code: null,
        has_report: false,
        automatic_progression: false,
        stages: [
          { stage: "C2", state: "completed" },
          { stage: "C4", state: "uncertain" },
        ],
      }}
    />,
  );

  expect(markup).toContain('data-paused="true"');
  expect(markup).toContain('data-animated="false"');
  expect(markup).toContain("Needs attention");
  expect(markup).toContain("Your recording");
  expect(markup).toContain("The completed transcript stays attached");
  expect(markup).toContain(
    "This stage needs checking before analysis can continue",
  );
  expect(markup).not.toContain("Unlimited testing");
  expect(markup).not.toContain("12.4 MB");
  expect(markup).not.toContain('aria-current="step"');
});

it("renders a static fixture with no live-call timer, saved-work claim, or action", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      staticPreview
      stageRows={[
        { stage: "C2", state: "completed", label: "Complete" },
        { stage: "C4", state: "running", label: "In progress" },
      ]}
      statusText="Checking the conversation"
      submissionId="00000000-0000-4000-8000-000000000001"
      progress={{
        state: "active",
        local_state: "completed",
        failure_code: null,
        has_report: false,
        automatic_progression: true,
        stages: [
          { stage: "C2", state: "completed" },
          { stage: "C4", state: "running" },
        ],
      }}
      fileName="Example call.wav"
    >
      <button type="button">Check status</button>
    </AcquisitionProcessingPanel>,
  );
  expect(markup).toContain("Example processing state");
  expect(markup).toContain("No call was uploaded or analysed");
  expect(markup).toContain("Example audio");
  expect(markup).toContain('data-animated="false"');
  expect(markup).toContain('data-fixture="true"');
  expect(markup).not.toContain("LAST CONFIRMED STATUS");
  expect(markup).not.toContain("Uploaded file");
  expect(markup).not.toContain("Your recording is saved");
  expect(markup).not.toContain("Check status");
});
