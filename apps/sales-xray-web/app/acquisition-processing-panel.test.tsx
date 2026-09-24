import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import Link from "next/link";
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

it("puts the confirmed status and recovery actions before stage and file details", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      stageRows={[
        { stage: "C2", state: "queued", label: "Queued" },
        { stage: "C4", state: null, label: "Not started" },
        { stage: "C5", state: null, label: "Not started" },
      ]}
      statusText="Ready for your approval"
      waitingForApproval
      accepted={false}
      fileName="Synthetic full recording filename.m4a"
    >
      <button type="button">Check status</button>
      <Link href="/?call=synthetic-id">This call’s link</Link>
      <button type="button">Review analysis plan</button>
    </AcquisitionProcessingPanel>,
  );

  expect(markup).toContain(">Ready to analyse</h2>");
  expect(markup).not.toContain(">Processing your call</h2>");
  const latestStatus = markup.indexOf("Ready for your approval");
  const guidance = markup.indexOf("analysis approval is not confirmed yet");
  const checkStatus = markup.indexOf("Check status");
  const callLink = markup.indexOf("This call’s link");
  const recoveryAction = markup.indexOf("Review analysis plan");
  const stageTrail = markup.indexOf('aria-label="Processing stages"');
  const fileDetails = markup.indexOf(">Uploaded file</h3>");
  expect(latestStatus).toBeGreaterThan(-1);
  expect(guidance).toBeGreaterThan(latestStatus);
  expect(checkStatus).toBeGreaterThan(guidance);
  expect(callLink).toBeGreaterThan(checkStatus);
  expect(recoveryAction).toBeGreaterThan(callLink);
  expect(stageTrail).toBeGreaterThan(recoveryAction);
  expect(fileDetails).toBeGreaterThan(stageTrail);
  expect(markup).toContain("Synthetic full recording filename.m4a");
  expect(markup.match(/Review analysis plan/g)).toHaveLength(1);
});

it("keeps paused C5 recovery actions and the uploaded-file card in distinct flow sections", () => {
  const markup = renderToStaticMarkup(
    <AcquisitionProcessingPanel
      stageRows={[
        { stage: "C2", state: "completed", label: "Complete" },
        { stage: "C4", state: "completed", label: "Complete" },
        { stage: "C5", state: "uncertain", label: "Paused · needs attention" },
      ]}
      statusText="Analysis paused"
      paused
      fileName="Discovery call.m4a"
      fileMeta="42 min · 28.4 MB"
      submissionId="call-c5"
      progress={{
        state: "held",
        local_state: "completed",
        failure_code: null,
        has_report: false,
        automatic_progression: true,
        stages: [
          { stage: "C2", state: "completed" },
          { stage: "C4", state: "completed" },
          { stage: "C5", state: "uncertain" },
        ],
      }}
    >
      <button type="button">Check status</button>
      <button type="button">Review and continue analysis</button>
    </AcquisitionProcessingPanel>,
  );

  expect(markup).toContain(
    'aria-label="Writing your coaching report: Paused · needs attention"',
  );
  expect(markup).toContain("Uploaded file");
  expect(markup).toContain("Discovery call.m4a");
  expect(markup).toContain("Check status");
  expect(markup).toContain("Review and continue analysis");
  expect(markup.indexOf("Uploaded file")).toBeLessThan(
    markup.indexOf("Check status"),
  );
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
