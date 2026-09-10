// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ApiError,
  type LearnerApi,
  type LearningResponse,
} from "../lib/learner-api";
import { ProgressRuntime } from "./progress-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const learning: LearningResponse = {
  program_id: "program-1",
  program_version_id: "version-1",
  program_slug: "authority-closers-free-course",
  program_title: "Foundations",
  version_number: 1,
  enrollment_id: "enrollment-1",
  projection: {
    scope_type: "program_version",
    scope_id: "version-1",
    program_version: "1.0.0",
    projection_version: "progress-v1",
    denominator: 2,
    completed_count: 1,
    percentage: 0.5,
    predicate: "required activities completed",
    missing_module_ids: [],
    activity_reasons: [],
  },
  modules: [
    {
      id: "module-1",
      position: 1,
      title: "First conversations",
      activities: [
        {
          id: "activity-1",
          module_id: "module-1",
          program_version_id: "version-1",
          position: 1,
          kind: "video",
          title: "Start with curiosity",
          prompt: null,
          state: "completed",
          revision: 1,
          required: true,
          allowed_actions: [],
          explanation: {
            activity_id: "activity-1",
            state: "completed",
            required: true,
            reason: "completed",
            missing_activity_ids: [],
            missing_module_ids: [],
          },
        },
      ],
    },
    {
      id: "module-2",
      position: 2,
      title: "Asking better questions",
      activities: [],
    },
  ],
};

function makeApi() {
  return {
    me: vi.fn(async () => ({
      person_id: "person-1",
      email: "learner@example.com",
      display_name: "Learner",
      email_verified_at: "2026-09-01T00:00:00Z",
      selected_tenant_id: "tenant-1",
      membership_role: "learner",
      permissions: [],
    })),
    listPrograms: vi.fn(async () => ({
      items: [
        {
          id: learning.program_id,
          slug: learning.program_slug,
          title: learning.program_title,
          program_version_id: learning.program_version_id,
          version_number: 1,
          published_at: "2026-09-01T00:00:00Z",
        },
      ],
      next_cursor: null,
    })),
    learning: vi.fn(async () => learning),
    learningCollection: vi.fn(async () => ({
      items: [],
      next_cursor: null,
      saved_filter_available: false,
    })),
    insights: vi.fn<LearnerApi["insights"]>(() => new Promise(() => {})),
  };
}
let api: ReturnType<typeof makeApi>;
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  api = makeApi();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
const mount = async () => {
  await act(async () =>
    root.render(<ProgressRuntime api={api as unknown as LearnerApi} />),
  );
};
const button = (text: string) =>
  [...container.querySelectorAll<HTMLButtonElement>("button")].find((node) =>
    node.textContent?.includes(text),
  )!;

it("shows one course summary and the real completion counts, without unavailable motivation cards", async () => {
  await mount();
  expect(
    container.querySelectorAll('[data-progress-scope="course"]'),
  ).toHaveLength(1);
  expect(container.textContent).toContain("50%");
  expect(container.textContent).toContain("1 / 2");
  expect(container.textContent).not.toMatch(
    /Progress hierarchy|Canonical course projection|Descriptive telemetry|Streak unavailable|Achievements unavailable/,
  );
  expect(
    container.querySelector<HTMLAnchorElement>(".progress-scope-continue")
      ?.href,
  ).toContain(learning.program_slug);
  expect(api.insights).not.toHaveBeenCalled();
});

it("offers native expandable module details and labels unpublished modules without fake zeros", async () => {
  await mount();
  const modules = container.querySelectorAll("details");
  expect(modules).toHaveLength(2);
  expect(modules[0].open).toBe(true);
  expect(modules[1].open).toBe(false);
  expect(modules[0].querySelector("summary")?.textContent).toContain("1/1");
  expect(modules[1].querySelector("summary")?.textContent).toContain(
    "Coming soon",
  );
  // Native details owns expansion; changing scope must not reset that choice.
  modules[1].open = true;
  await act(async () => button("All learning").click());
  expect(modules[1].open).toBe(true);
});

it("loads optional insights only on request and aborts their pending read when collapsed", async () => {
  await mount();
  const toggle = button("Activity insights");
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  await act(async () => toggle.click());
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(api.insights).toHaveBeenCalledOnce();
  const signal = api.insights.mock.calls[0][1]?.signal;
  expect(signal?.aborted).toBe(false);
  await act(async () => toggle.click());
  expect(signal?.aborted).toBe(true);
  expect(container.querySelector("[data-analytics-scope]")).toBeNull();
  expect(
    container.querySelectorAll('[data-progress-scope="course"]'),
  ).toHaveLength(1);
});

it("retains a useful retry after a failed load without inventing completion", async () => {
  api.learning.mockRejectedValueOnce(new Error("network"));
  await mount();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Progress could not load",
  );
  expect(container.querySelector('[data-progress-scope="course"]')).toBeNull();
  await act(async () => button("Retry").click());
  expect(container.querySelector('[role="alert"]')).toBeNull();
  expect(container.textContent).toContain("50%");
});

it("keeps expired identity out of progress and offers normal sign-in", async () => {
  api.me.mockRejectedValueOnce(
    new ApiError(401, "Session expired", { code: "session_expired" }),
  );
  await mount();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Sign in to view your progress",
  );
  expect(container.querySelector('[data-progress-scope="course"]')).toBeNull();
  expect(api.learning).not.toHaveBeenCalled();
  expect(api.learningCollection).not.toHaveBeenCalled();
  expect(
    [...container.querySelectorAll("a")].some(
      (link) => link.textContent === "Sign in again",
    ),
  ).toBe(true);
});
