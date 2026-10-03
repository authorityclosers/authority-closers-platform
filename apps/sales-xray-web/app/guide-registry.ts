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

export const FIRST_CALL_GUIDE: GuideDefinition = {
  id: "first-call",
  version: "1",
  label: "First call guide",
  steps: [
    {
      id: "welcome",
      title: "Welcome to Sales Xray",
      body: "Start with one conversation. We’ll show you where to look and how to take your next step.",
      visual: "welcome",
    },
    {
      id: "listen",
      title: "Bring a real conversation",
      body: "Choose a recording you have permission to analyse. Sales Xray brings the conversation and its transcript into one place.",
      visual: "listen",
    },
    {
      id: "understand",
      title: "See the evidence",
      body: "Explore the report, then listen to the moments behind each observation. Keep the source in view as you review.",
      visual: "evidence",
    },
    {
      id: "practise",
      title: "Choose your next step",
      body: "Use the report to choose one thing to practise in your next conversation. Come back to your saved calls to review again.",
      visual: "practice",
    },
    {
      id: "upload",
      title: "Add your first call",
      body: "Click Choose a file or drop your recording here. Follow the existing privacy and language checks to start analysis.",
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
      body: "This page shows the current analysis status and any action needed. Your guide will continue when the report appears.",
      visual: "listen",
      target: PROGRESS,
      href: "/calls",
      actionLabel: "Open saved calls",
      waitForPage: true,
      advanceWhen: [{ selector: REPORT, stepId: "report" }],
    },
    {
      id: "report",
      title: "Your report, one section at a time",
      body: "Start with the overview. Use the report navigation to explore the conversation at your own pace.",
      visual: "evidence",
      target: REPORT,
      href: "/calls",
      actionLabel: "Open saved calls",
    },
    {
      id: "moments",
      title: "Listen before you decide",
      body: "Open Moments or Transcript from the report navigation. Listen to the source behind an observation, then choose what to practise next.",
      visual: "practice",
      target: "[data-report-sections]",
      href: "/calls",
      actionLabel: "Open saved calls",
    },
    // Invitation and call-policy screens are not on main yet. Register their
    // owner-only steps when those actual screens ship; never show placeholder links.
  ],
};
