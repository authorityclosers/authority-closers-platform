// @vitest-environment happy-dom
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import * as session from "@ac/operations-web/session";
import {
  StudioDashboard,
  StudioPublicationQueue,
  StudioAccountAccess,
} from "@ac/operations-web/studio-workspace";
import { CoachShell, isCoachRouteActive } from "./coach-shell";
import { CoachSettings } from "./coach-settings";
import { CoachPreferencesProvider } from "./coach-preferences";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/studio/programs/course-id",
}));
vi.mock("@ac/operations-web/session", async (original) => ({
  ...(await original<typeof import("@ac/operations-web/session")>()),
  AdminSessionProvider: ({ children }: { children: React.ReactNode }) =>
    children,
  useAdminSession: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const tenant = "11111111-1111-4111-8111-111111111111";
const course = "22222222-2222-4222-8222-222222222222";
let account: session.AdminSessionState, host: HTMLDivElement, root: Root;
function programs(): api.StudioPrograms {
  return {
    tenant_id: tenant,
    truncated: false,
    programs: [
      {
        id: course,
        title: "Discovery essentials",
        slug: "discovery",
        scope: "tenant",
        access: "selected_tenant",
        version_count: 2,
        draft_count: 1,
        current_published_version_id: course,
        latest_version: null,
      },
    ],
  };
}
function readiness(): api.StudioReadiness {
  const unavailable = {
    status: "unavailable",
    value: null,
    reason: "not measured",
  } as const;
  return {
    tenant_id: tenant,
    draft_backlog_count: 2,
    as_of: "2026-09-09T00:00:00Z",
    oldest_draft_created_at: null,
    oldest_draft_age_seconds: null,
    truncated: false,
    arrival_rate: unavailable,
    service_rate: unavailable,
    planned_capacity: unavailable,
    drafts: [
      {
        program_id: course,
        program_title: "Discovery essentials",
        program_version_id: course,
        version_number: 2,
        created_at: "2026-09-09T00:00:00Z",
        age_seconds: 0,
        etag: '"program-version-' + "a".repeat(64) + '"',
        ready: false,
        blockers: ["provenance_incomplete"],
      },
      {
        program_id: tenant,
        program_title: "Listening skills",
        program_version_id: tenant,
        version_number: 1,
        created_at: "2026-09-09T00:00:00Z",
        age_seconds: 0,
        etag: '"program-version-' + "b".repeat(64) + '"',
        ready: true,
        blockers: [],
      },
    ],
  };
}
function button(label: string) {
  return [...host.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label,
  )!;
}
async function render(content: React.ReactNode) {
  await act(async () => root.render(content));
}
beforeEach(() => {
  account = {
    status: "ready",
    error: null,
    session: {
      personId: tenant,
      sessionId: tenant,
      tenantId: tenant,
      displayName: "Test Coach",
      email: "coach@example.test",
      emailVerifiedAt: "2026-09-09T00:00:00Z",
      membershipRole: "learner",
      permissions: [],
      studioCapabilities: [
        "catalog_read",
        "catalog_write",
        "catalog_publish",
      ].map((permission) => ({
        tenant_id: tenant,
        permission: permission as
          | "catalog_read"
          | "catalog_write"
          | "catalog_publish",
        scope_kind: "program",
        program_id: course,
      })),
    },
  };
  vi.mocked(session.useAdminSession).mockImplementation(() => account);
  vi.spyOn(api, "loadStudioPrograms").mockResolvedValue(programs());
  vi.spyOn(api, "loadStudioReadiness").mockResolvedValue(readiness());
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  localStorage.clear();
});

it("mounts real course counts and direct next-action links, without inventing creation access", async () => {
  await render(<StudioDashboard />);
  expect(host.textContent).toContain("Welcome back, Test.");
  expect(host.textContent).toContain("Published courses");
  expect(
    host.querySelector('a[href="/studio/programs/' + course + '"]'),
  ).not.toBeNull();
  expect(button("Create course")).toBeUndefined();
  expect(host.textContent).not.toContain("Unavailable");
});
it("prioritizes a genuinely writable course over an earlier read-only course", async () => {
  vi.mocked(api.loadStudioPrograms).mockResolvedValue({
    ...programs(),
    programs: [
      {
        ...programs().programs[0],
        id: tenant,
        title: "Shared reference course",
        access: "global_read_only",
      },
      programs().programs[0],
    ],
  });
  await render(<StudioDashboard />);
  expect(host.querySelector(".button-primary")?.getAttribute("href")).toBe(
    `/studio/programs/${course}`,
  );
  expect(host.textContent).toContain("Shape the lessons");
});
it("keeps a global course read-only even with tenant-wide write capability", async () => {
  if (account.status !== "ready") throw new Error("ready fixture required");
  account = {
    status: "ready",
    error: null,
    session: {
      ...account.session,
      studioCapabilities: [
        ...account.session.studioCapabilities.filter(
          ({ permission }) => permission === "catalog_read",
        ),
        {
          tenant_id: tenant,
          permission: "catalog_write",
          scope_kind: "tenant",
          program_id: null,
        },
      ],
    },
  };
  vi.mocked(api.loadStudioPrograms).mockResolvedValue({
    ...programs(),
    programs: [
      {
        ...programs().programs[0],
        title: "Shared reference course",
        access: "global_read_only",
      },
    ],
  });
  await render(<StudioDashboard />);
  expect(host.textContent).toContain("EXPLORE YOUR COURSE");
  expect(host.textContent).toContain("Review this course");
  expect(host.textContent).not.toContain("Shape the lessons");
});
it("shows scoped empty state and bounded totals disclosure", async () => {
  vi.mocked(api.loadStudioPrograms).mockResolvedValue({
    tenant_id: tenant,
    programs: [],
    truncated: true,
  });
  await render(<StudioDashboard />);
  expect(host.textContent).toContain("No courses yet.");
  expect(host.textContent).toContain("first 100 courses");
});
it("rejects a course payload from another academy", async () => {
  vi.mocked(api.loadStudioPrograms).mockResolvedValue({
    ...programs(),
    tenant_id: course,
  });
  await render(<StudioDashboard />);
  expect(host.textContent).not.toContain("Discovery essentials");
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
});
it("ignores late course responses after a session change", async () => {
  let resolve!: (data: api.StudioPrograms) => void;
  vi.mocked(api.loadStudioPrograms).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  await render(<StudioDashboard />);
  account = { status: "denied", error: "Session expired", session: null };
  await render(<StudioDashboard />);
  await act(async () => resolve(programs()));
  expect(host.textContent).not.toContain("Discovery essentials");
});
it("retries a failed dashboard read", async () => {
  vi.mocked(api.loadStudioPrograms).mockRejectedValueOnce(new Error("offline"));
  await render(<StudioDashboard />);
  expect(host.querySelector('[role="alert"]')).not.toBeNull();
  await act(async () => button("Try again").click());
  expect(host.textContent).toContain("Discovery essentials");
});
it("filters real publication checks without offering blind publish actions", async () => {
  await render(<StudioPublicationQueue />);
  expect(host.textContent).toContain("Record the content source and review.");
  await act(async () => button("Ready for review").click());
  expect(host.textContent).toContain("Listening skills");
  expect(host.textContent).not.toContain("Discovery essentials");
  await act(async () => button("Needs attention").click());
  expect(host.textContent).toContain("Discovery essentials");
  expect(host.textContent).not.toContain("Listening skills");
  expect(button("Publish")).toBeUndefined();
});
it("distinguishes assigned-course access from academy-wide access", async () => {
  await render(<StudioAccountAccess />);
  expect(host.textContent).toContain("Assigned courses");
  expect(host.textContent).not.toContain("Academy-wide");
});
it("keeps one active destination for nested course routes in both menus", async () => {
  await render(
    <CoachShell>
      <h1>Course editor</h1>
    </CoachShell>,
  );
  const active = [...host.querySelectorAll('[aria-current="page"]')];
  expect(active).toHaveLength(2);
  expect(
    active.every((link) => link.getAttribute("href") === "/studio/programs"),
  ).toBe(true);
  expect(isCoachRouteActive("/studio/programs-extra", "/studio/programs")).toBe(
    false,
  );
  expect(isCoachRouteActive("/studio/programs/123", "/studio")).toBe(false);
  expect(host.querySelector('a[href="/studio/settings"]')).not.toBeNull();
  const workspace = host.querySelector(".coach-workspace") as HTMLElement;
  expect(workspace.style.getPropertyValue("--theme-action").trim()).toBe(
    "var(--signal)",
  );
  expect(workspace.style.getPropertyValue("--theme-surface").trim()).toBe(
    "var(--panel)",
  );
});
it("shows a real sign-in action when the session is denied", async () => {
  account = { status: "denied", error: "denied", session: null };
  await render(
    <CoachShell>
      <h1>Private content</h1>
    </CoachShell>,
  );
  expect(host.textContent).not.toContain("Private content");
  expect(host.querySelector('a[href="/login"]')).not.toBeNull();
});
it("saves and restores browser-only theme and reduced motion", async () => {
  await render(
    <CoachPreferencesProvider>
      <CoachSettings />
    </CoachPreferencesProvider>,
  );
  await act(async () => button("Dark").click());
  expect(document.documentElement.dataset.theme).toBe("dark");
  await act(async () =>
    (host.querySelector('[role="switch"]') as HTMLButtonElement).click(),
  );
  expect(document.documentElement.dataset.reduceMotion).toBe("true");
  await render(null);
  await render(
    <CoachPreferencesProvider>
      <CoachSettings />
    </CoachPreferencesProvider>,
  );
  expect(button("Dark").getAttribute("aria-pressed")).toBe("true");
  expect(
    host.querySelector('[role="switch"]')?.getAttribute("aria-checked"),
  ).toBe("true");
});
it("keeps appearance usable and tells the truth when browser storage fails", async () => {
  await render(
    <CoachPreferencesProvider>
      <CoachSettings />
    </CoachPreferencesProvider>,
  );
  vi.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  await act(async () => button("Dark").click());
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(host.textContent).toContain("couldn’t save your preference");
});
it("does not claim success when sign-out fails", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(new Response("", { status: 503 }));
  await render(
    <CoachPreferencesProvider>
      <CoachSettings />
    </CoachPreferencesProvider>,
  );
  await act(async () => button("Sign out").click());
  expect(fetcher).toHaveBeenCalledWith("/v1/auth/logout", {
    method: "POST",
    credentials: "same-origin",
  });
  expect(host.textContent).toContain("couldn’t confirm sign-out");
  expect(button("Sign out").disabled).toBe(false);
});
