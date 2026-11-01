export type GuideStep = Readonly<{
  id: string;
  title: string;
  body: string;
  visual: "welcome" | "listen" | "evidence" | "practice";
  target?: string;
  href?: string;
  actionLabel?: string;
  /** Follow an existing page state; the guide never starts an analysis. */
  advanceWhen?: readonly Readonly<{ selector: string; stepId: string }>[];
  waitForPage?: boolean;
  ownerOnly?: boolean;
  available?: boolean;
}>;

export type GuideDefinition = Readonly<{
  id: string;
  version: string;
  label: string;
  steps: readonly GuideStep[];
  /** Closing it keeps it closed for later versions too. */
  rememberOff?: boolean;
}>;

export function eligibleGuideSteps(
  guide: GuideDefinition,
  isOrgOwner: boolean,
) {
  return guide.steps.filter(
    (step) => step.available !== false && (!step.ownerOnly || isOrgOwner),
  );
}

const UPLOAD = '[role="group"][aria-label="Add sales call audio files"]';
const PROGRESS = 'section[aria-label="Analysis progress"]';
const REPORT = "[data-report-modes]";

// Phone words and the phone flow (phone personas ph2-30, 1 Nov 2026: the
// guide opened over My Growth, spoke only of uploading, and said "Click" and
// "drop" on a phone). Six short steps, opened only where a call is added.
export const FIRST_CALL_GUIDE: GuideDefinition = {
  id: "first-call",
  version: "1",
  label: "First call guide",
  rememberOff: true,
  steps: [
    {
      id: "welcome",
      title: "Welcome to Sales X-Ray",
      body: "Each call with a lead can become a report: what they said, what holds them back and your next step.",
      visual: "welcome",
    },
    {
      id: "listen",
      title: "Calls from Leads come in by themselves",
      body: "In the Sales X-Ray phone app, tap Call on a lead. Once call recording is set up, the recording comes in after the call. Any other call, you add here.",
      visual: "listen",
    },
    {
      id: "upload",
      title: "Add a recording",
      body: "Choose a file and pick the call’s recording, then answer the privacy and language questions to start.",
      visual: "listen",
      target: UPLOAD,
      href: "/analysis/new",
      actionLabel: "Open new analysis",
      waitForPage: true,
      advanceWhen: [
        { selector: REPORT, stepId: "report" },
        { selector: PROGRESS, stepId: "progress" },
      ],
    },
    {
      id: "progress",
      title: "Follow your analysis",
      body: "This shows how far it has got and anything you need to do. The guide carries on when the report is ready.",
      visual: "listen",
      target: PROGRESS,
      href: "/calls",
      actionLabel: "Open saved calls",
      waitForPage: true,
      advanceWhen: [{ selector: REPORT, stepId: "report" }],
    },
    {
      id: "report",
      title: "Your report, one part at a time",
      body: "Start with the summary and the next step. Open any other part when you want more.",
      visual: "evidence",
      target: REPORT,
      href: "/calls",
      actionLabel: "Open saved calls",
    },
    {
      id: "moments",
      title: "Listen before you decide",
      body: "Open Moments or Transcript and play the part behind a point. Then pick one thing to try on your next call.",
      visual: "practice",
      target: "[data-report-sections]",
      href: "/calls",
      actionLabel: "Open saved calls",
    },
    // Invitation and call-policy screens are not on main yet. Register their
    // owner-only steps when those actual screens ship; never show placeholder links.
  ],
};
