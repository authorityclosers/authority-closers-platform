import type {
  ActivityKind,
  ActivityViewModel,
  CertificateViewModel,
  LearnerViewModel,
  ModuleViewModel,
  ProgramViewModel,
} from "./view-models";

const watchActivity: ActivityViewModel = {
  id: "watch",
  order: 1,
  title: "Notice the real question",
  eyebrow: "Watch",
  kind: "VIDEO",
  status: "PREVIEW",
  duration: "06 min",
  objective: "Spot the moment a conversation moves from information to intent.",
  prompt: "Watch for the question underneath the question.",
  evidenceLabel: "Media progress evidence contract pending integration",
  helperText:
    "Static transcript copy only. No media, captions, timeline, or completion event is connected.",
};

const reflectActivity: ActivityViewModel = {
  id: "reflect",
  order: 2,
  title: "Name the signal",
  eyebrow: "Reflect",
  kind: "REFLECTION",
  status: "PREVIEW",
  duration: "04 min",
  objective:
    "Turn an observation into a sentence you can use on your next call.",
  prompt: "Where do you usually rush past the useful signal?",
  evidenceLabel: "Draft revision contract pending integration",
  helperText:
    "The disabled input stores nothing and does not submit a response.",
};

const implementActivity: ActivityViewModel = {
  id: "implement",
  order: 3,
  title: "Try the clean interruption",
  eyebrow: "Implement",
  kind: "IMPLEMENTATION_CHALLENGE",
  status: "PREVIEW",
  duration: "03 min",
  objective:
    "Practice one low-friction move that creates room for a better answer.",
  prompt: "Choose the response that keeps the conversation honest.",
  evidenceLabel: "Learner evidence submission contract pending integration",
  helperText: "The choices are practice prompts, not a scored assessment.",
};

const reviewActivity: ActivityViewModel = {
  id: "review",
  order: 4,
  title: "Make the attempt legible",
  eyebrow: "Review",
  kind: "REVIEW",
  status: "LOCKED",
  duration: "05 min",
  objective:
    "Describe what happened so another person can respond to the work, not the story around it.",
  prompt: "What would a thoughtful reviewer need to see?",
  evidenceLabel: "Append-only human review contract pending integration",
  helperText:
    "This human-review renderer remains unavailable until its parent module unlocks.",
};

const improveActivity: ActivityViewModel = {
  id: "improve",
  order: 5,
  title: "Choose the next rep",
  eyebrow: "Improve",
  kind: "IMPROVE",
  status: "LOCKED",
  duration: "04 min",
  objective: "Turn feedback into one specific change you can repeat.",
  prompt: "What will you do differently in the next conversation?",
  evidenceLabel: "Superseding improvement record contract pending integration",
  helperText:
    "This renderer remains unavailable until canonical progression unlocks its parent module.",
};

const firstModule: ModuleViewModel = {
  id: "module-01",
  number: "01",
  title: "Find the signal",
  summary:
    "Slow down long enough to hear what the other person is actually deciding.",
  prerequisite: "Start here. No prerequisite.",
  status: "AVAILABLE",
  activities: [watchActivity, reflectActivity, implementActivity],
};

const secondModule: ModuleViewModel = {
  id: "module-02",
  number: "02",
  title: "Make the work useful",
  summary: "Carry an attempt through review and into a better next repetition.",
  prerequisite: "Unlocks after the first module is complete.",
  status: "LOCKED",
  activities: [reviewActivity, improveActivity],
};

export const freeCourse: ProgramViewModel = {
  slug: "free-course",
  title: "The First Conversation Lab",
  eyebrow: "Free course preview",
  shortDescription:
    "A five-step practice loop for clearer, more deliberate conversations.",
  description:
    "This small course preview walks one idea from observation to a repeatable next move. The copy and learner data on this screen are deterministic demo content until the approved content and API contracts are connected.",
  previewLabel: "Preview content · not connected to an account",
  formatLabel: "5 activities · sequential practice",
  learningLoop: ["Watch", "Reflect", "Implement", "Review", "Improve"],
  modules: [firstModule, secondModule],
};

export const demoLearner: LearnerViewModel = {
  displayName: "Demo learner",
  initials: "DL",
  workspaceLabel: "Preview workspace",
  currentProgramSlug: freeCourse.slug,
  previewProgressLabel: "Preview path · 0 verified completions",
  nextActivityId: "reflect",
  draftSeamLabel:
    "No draft is stored. This card marks where durable learner work can appear after integration.",
};

export const demoCertificate: CertificateViewModel = {
  id: "preview-certificate",
  learnerName: "Demo learner",
  programTitle: freeCourse.title,
  issuedLabel: "Not issued · preview only",
  certificateStatus: "PREVIEW_NOT_ISSUED",
  distinction: "Course completion is separate from competency certification.",
};

const activityKindLabels: Record<ActivityKind, string> = {
  VIDEO: "Video",
  REFLECTION: "Reflection",
  IMPLEMENTATION_CHALLENGE: "Implementation challenge",
  REVIEW: "Review",
  IMPROVE: "Improve",
};

export function activityKindLabel(kind: ActivityKind): string {
  return activityKindLabels[kind];
}

export function getProgramBySlug(slug: string): ProgramViewModel | undefined {
  return slug === freeCourse.slug ? freeCourse : undefined;
}

export function getModuleById(
  program: ProgramViewModel,
  moduleId: string,
): ModuleViewModel | undefined {
  return program.modules.find((module) => module.id === moduleId);
}

export function getActivityById(
  activityId: string,
): ActivityViewModel | undefined {
  return getActivityLocationById(activityId)?.activity;
}

export type ActivityLocation = {
  activity: ActivityViewModel;
  module: ModuleViewModel;
};

export function getActivityLocationById(
  activityId: string,
): ActivityLocation | undefined {
  for (const courseModule of freeCourse.modules) {
    const activity = courseModule.activities.find(
      (item) => item.id === activityId,
    );

    if (activity) {
      return { activity, module: courseModule };
    }
  }

  return undefined;
}

export function isModulePayloadAllowed(
  courseModule: ModuleViewModel | undefined,
): boolean {
  return courseModule !== undefined && courseModule.status !== "LOCKED";
}

export function isActivityPayloadAllowed(
  location: ActivityLocation | undefined,
): boolean {
  return (
    location !== undefined &&
    isModulePayloadAllowed(location.module) &&
    location.activity.status !== "LOCKED"
  );
}
