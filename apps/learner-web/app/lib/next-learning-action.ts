import type { LearningActivityResponse, LearningResponse } from "./learner-api";

/** Guidance from the same canonical response; never an authorization decision. */
export function firstActionableActivity(
  learning: LearningResponse,
): LearningActivityResponse | undefined {
  const activities = learning.modules.flatMap((module) => module.activities);
  const hasServerPointer = Object.prototype.hasOwnProperty.call(
    learning.projection,
    "next_activity_id",
  );
  const pointer = learning.projection.next_activity_id;
  if (hasServerPointer && pointer === null) return undefined;

  const isActionable = (activity: LearningActivityResponse) => {
    const state = activity.state.toLowerCase();
    return (
      (state === "available" || state === "in_progress") &&
      activity.allowed_actions.length > 0 &&
      // The explanation includes both activity and module requiredness.
      (!hasServerPointer || activity.explanation.required)
    );
  };
  const pointed = activities.find((activity) => activity.id === pointer);
  if (pointed && isActionable(pointed)) return pointed;

  // Older responses retain their ordered fallback. A stale modern pointer
  // may fall back only to action-enabled work in the required path.
  return activities.find(isActionable);
}
