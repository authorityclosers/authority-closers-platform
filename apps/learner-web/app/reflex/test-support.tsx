import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, vi } from "vitest";
import type {
  LearnerApi,
  LearningResponse,
  LearningCourseSummaryResponse,
  LearningActivityResponse,
} from "../lib/learner-api";
import type {
  PracticeEngineApi,
  PracticeProgress,
} from "../lib/practice-engine-api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
export const program = {
  id: "course-a",
  slug: "authority-closers-free-course",
  title: "Clearer conversations",
  program_version_id: "version-a",
  version_number: 1,
  published_at: "2026-10-01T00:00:00Z",
};
export function activity(
  id: string,
  state: string,
  kind = "VIDEO",
): LearningActivityResponse {
  return {
    id,
    module_id: "module-a",
    program_version_id: "version-a",
    position: 1,
    title: `Step ${id}`,
    kind,
    prompt: null,
    state,
    revision: 1,
    required: true,
    allowed_actions:
      state === "locked" || state === "completed" ? [] : ["save_draft"],
    explanation: {
      activity_id: id,
      state,
      required: true,
      reason: "fixture",
      missing_module_ids: state === "locked" ? ["module-a"] : [],
      missing_activity_ids: [],
    },
  };
}
export function learning(): LearningResponse {
  return {
    program_id: program.id,
    program_slug: program.slug,
    program_title: program.title,
    program_version_id: "version-a",
    version_number: 1,
    enrollment_id: "enrollment-a",
    modules: [
      {
        id: "module-a",
        position: 1,
        title: "Listen first",
        activities: [
          activity("done", "completed"),
          activity("next", "in_progress", "REFLECTION"),
        ],
      },
      {
        id: "module-b",
        position: 2,
        title: "Build on it",
        activities: [activity("locked", "locked")],
      },
      {
        id: "module-c",
        position: 3,
        title: "Revisit",
        activities: [activity("review", "completed")],
      },
      {
        id: "module-d",
        position: 4,
        title: "Try a question",
        activities: [
          activity("ready", "available", "IMPLEMENTATION_CHALLENGE"),
        ],
      },
    ],
    projection: {
      scope_type: "program",
      scope_id: program.id,
      program_version: "version-a",
      projection_version: "v1",
      denominator: 5,
      completed_count: 2,
      percentage: 0.4,
      predicate: "fixture",
      missing_module_ids: [],
      activity_reasons: [],
      next_activity_id: "next",
    },
  };
}
export const summary: LearningCourseSummaryResponse = {
  program_id: program.id,
  program_slug: program.slug,
  program_title: program.title,
  program_version_id: "version-a",
  version_number: 1,
  enrollment_id: "enrollment-a",
  enrolled_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-28T00:00:00Z",
  state: "in_progress",
  saved_state: "unavailable",
  projection: learning().projection,
};
export function apiMock(items = [summary]) {
  return {
    me: vi.fn().mockResolvedValue({
      person_id: "fictional-mira",
      display_name: "Mira Example",
      email: "mira@example.test",
      selected_tenant_id: "academy",
      membership_role: "learner",
      permissions: [],
    }),
    onboarding: vi.fn().mockResolvedValue({ status: "completed" }),
    learningCollection: vi.fn().mockResolvedValue({ items, next_cursor: null }),
    learning: vi.fn().mockResolvedValue(learning()),
    listPrograms: vi
      .fn()
      .mockResolvedValue({ items: [program], next_cursor: null }),
    enrollFree: vi.fn().mockResolvedValue({ created: true }),
    calendar: vi.fn(),
    upNext: vi.fn(),
    plans: vi.fn(),
  } as unknown as LearnerApi & {
    upNext: ReturnType<typeof vi.fn>;
    plans: ReturnType<typeof vi.fn>;
  };
}
export function progress(): PracticeProgress {
  return {
    profile: {
      timezone: "Asia/Kolkata",
      revision: 1,
      pending_timezone: null,
      pending_effective_at: null,
    },
    credits_balance: 990,
    xp_total: 1000,
    actual_practice_days_this_week: 3,
    policy_version: "fixture",
    recent_attempts: Array.from({ length: 6 }, (_, i) => ({
      id: `attempt-${i}`,
      set_id: "next-move",
      set_version: 1,
      title: `Practice ${i}`,
      state: i === 0 ? "in_progress" : "completed",
      revision: 1,
      acknowledged_count: i === 0 ? 1 : 3,
      item_count: 3,
      issued_at: "2026-10-28T00:00:00Z",
      completed_at: i === 0 ? null : "2026-10-28T00:05:00Z",
    })),
    recent_awards: [],
    purchases_enabled: false,
    course_progress_affected: false,
  };
}
export const engineMock = () =>
  ({
    progress: vi.fn().mockResolvedValue(progress()),
    issue: vi.fn(),
  }) as unknown as PracticeEngineApi;
export function assertCopy(element: HTMLElement) {
  expect(element.textContent).not.toMatch(
    /catalog details returned by the server|canonical|projection|\bpoor\b|mastery|\bcredits?\b|\bXP\b|\bpoints?\b|\bprice\b|\bcosts?\b|[$₹€£]|\b(?:INR|USD|rupees?|dollars?)\b/i,
  );
  expect(element.querySelector('a[href="/leaderboard"]')).toBeNull();
  expect(element.querySelector("h1")).toBeNull();
}
export function harness() {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });
  return {
    get el() {
      return container;
    },
    async mount(content: ReactNode) {
      await act(async () => {
        root.render(content);
      });
    },
    async click(element: Element | null) {
      expect(element).not.toBeNull();
      await act(async () => {
        (element as HTMLElement).click();
      });
    },
    button(text: string) {
      return (
        [...container.querySelectorAll("button")].find((item) =>
          item.textContent?.includes(text),
        ) ?? null
      );
    },
    link(text: string) {
      return (
        [...container.querySelectorAll("a")].find((item) =>
          item.textContent?.includes(text),
        ) ?? null
      );
    },
  };
}
