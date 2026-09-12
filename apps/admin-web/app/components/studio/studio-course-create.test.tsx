// @vitest-environment happy-dom
import { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import * as session from "@ac/operations-web/session";
import {
  StudioCourseCreate,
  activateStudioCourseCreationScope,
} from "../../../../../packages/typescript/operations-web/src/studio/studio-course-create";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const tenant = "11111111-1111-4111-8111-111111111111";
const programId = "22222222-2222-4222-8222-222222222222";
const versionId = "33333333-3333-4333-8333-333333333333";
let container: HTMLDivElement, root: Root;
let account: session.AdminSessionState;
function response(): api.StudioDraftMutationResponse {
  return {
    resource_id: versionId,
    replayed: false,
    program: {
      tenant_id: tenant,
      id: programId,
      slug: "course-id",
      title: "Sales foundations",
      scope: "tenant",
      access: "selected_tenant",
      versions_truncated: false,
      versions: [
        {
          id: versionId,
          version_number: 1,
          status: "draft",
          created_at: "2026-09-09T00:00:00Z",
          published_at: null,
          supersedes_version_id: null,
          content_source_ref: null,
          content_reviewed_by: null,
          content_reviewed_at: null,
          release_id: null,
          content_seed_kind: null,
          content_digest: null,
          etag: '"program-version-' + "a".repeat(64) + '"',
          readiness: "blocked",
          blockers: ["provenance_incomplete"],
          modules: [],
        },
      ],
    },
  };
}
function button(text: string) {
  return [...container.querySelectorAll("button")].find(
    (element) => element.textContent?.trim() === text,
  )!;
}
async function click(text: string) {
  await act(async () => button(text).click());
}
async function type(text: string) {
  const input = container.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount() {
  await act(async () => root.render(<StudioCourseCreate />));
}
async function remount() {
  await act(async () => root.render(null));
  await mount();
}
beforeEach(() => {
  activateStudioCourseCreationScope("reset-" + crypto.randomUUID());
  account = {
    status: "ready",
    error: null,
    session: {
      personId: crypto.randomUUID(),
      sessionId: crypto.randomUUID(),
      tenantId: tenant,
      displayName: "Test coach",
      email: "test@example.test",
      emailVerifiedAt: "2026-09-09T00:00:00Z",
      membershipRole: "learner",
      permissions: [],
      studioCapabilities: ["catalog_read", "catalog_write"].map(
        (permission) => ({
          permission: permission as "catalog_read" | "catalog_write",
          scope_kind: "tenant",
          tenant_id: tenant,
          program_id: null,
        }),
      ),
    },
  };
  vi.spyOn(session, "useAdminSession").mockImplementation(() => account);
  vi.spyOn(api, "createStudioCourse").mockRejectedValue(
    new Error("Unexpected network"),
  );
  vi.spyOn(api, "newIdempotencyKey").mockReturnValue("exact-key");
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(
    function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  );
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (
    this: HTMLDialogElement,
  ) {
    this.removeAttribute("open");
  });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

it("creates only on explicit submit, then offers the canonical first module route", async () => {
  vi.mocked(api.createStudioCourse).mockResolvedValue(response());
  await mount();
  await click("Create course");
  expect(container.querySelector("dialog")?.open).toBe(true);
  expect(button("Create draft").disabled).toBe(true);
  expect(api.createStudioCourse).not.toHaveBeenCalled();
  await type("Sales foundations");
  await click("Create draft");
  expect(api.createStudioCourse).toHaveBeenCalledOnce();
  expect(api.createStudioCourse).toHaveBeenCalledWith({
    title: "Sales foundations",
    tenantId: tenant,
    idempotencyKey: "exact-key",
  });
  expect(container.textContent).toContain("Your course is saved");
  expect(container.querySelector("a")?.getAttribute("href")).toBe(
    `/studio/programs/${programId}`,
  );
  await click("Close");
  await click("Create course");
  expect(container.querySelector("input")?.value).toBe("");
});

it("keeps unsent typing when closed and reopened", async () => {
  await mount();
  await click("Create course");
  await type("In progress");
  await click("Close");
  await click("Create course");
  expect(container.querySelector("input")?.value).toBe("In progress");
  expect(api.createStudioCourse).not.toHaveBeenCalled();
});

it("locks the submitted title and reuses the exact key after uncertainty and denied retry", async () => {
  await mount();
  await click("Create course");
  await type("Sales foundations");
  await click("Create draft");
  expect(container.querySelector("input")?.disabled).toBe(true);
  vi.mocked(api.createStudioCourse).mockRejectedValue(
    new api.AdminApiProblem({
      status: 403,
      code: "denied",
      title: "Denied",
      detail: "Denied",
      requestId: null,
    }),
  );
  await click("Check saved course");
  expect(container.querySelector("input")?.disabled).toBe(true);
  vi.mocked(api.createStudioCourse).mockResolvedValue({
    ...response(),
    replayed: true,
  });
  await click("Check saved course");
  expect(api.createStudioCourse).toHaveBeenCalledTimes(3);
  expect(
    vi
      .mocked(api.createStudioCourse)
      .mock.calls.every(
        ([input]) =>
          input.idempotencyKey === "exact-key" &&
          input.title === "Sales foundations",
      ),
  ).toBe(true);
  expect(container.textContent).toContain("Your course is saved");
});

it("requires academy-wide read and write hints rather than a role or one-course assignment", async () => {
  if (account.status !== "ready") throw new Error("fixture");
  account = {
    ...account,
    session: {
      ...account.session,
      studioCapabilities: account.session.studioCapabilities.map(
        (capability) => ({
          ...capability,
          scope_kind: "program",
          program_id: programId,
        }),
      ),
    },
  };
  await mount();
  expect(container.querySelector("button")).toBeNull();
});

it("does not expose previous input to a different verified session", async () => {
  await mount();
  await click("Create course");
  await type("Private draft");
  await click("Create draft");
  if (account.status !== "ready") throw new Error("fixture");
  account = {
    ...account,
    session: { ...account.session, sessionId: crypto.randomUUID() },
  };
  await mount();
  await click("Create course");
  expect(container.textContent).not.toContain("Private draft");
  expect(container.querySelector("input")?.value).toBe("");
});

it("retains an ambiguous command across same-session permission removal", async () => {
  await mount();
  await click("Create course");
  await type("Sales foundations");
  await click("Create draft");
  const original = account;
  if (account.status !== "ready") throw new Error("fixture");
  account = {
    ...account,
    session: { ...account.session, studioCapabilities: [] },
  };
  await mount();
  expect(container.querySelector("dialog")).toBeNull();
  account = original;
  await mount();
  expect(container.querySelector("input")?.value).toBe("Sales foundations");
  expect(button("Check saved course")).toBeDefined();
});

it("ignores a late original receipt after its remounted retry finished and a newer course started", async () => {
  let finishOriginal!: (value: api.StudioDraftMutationResponse) => void;
  vi.mocked(api.newIdempotencyKey)
    .mockReturnValueOnce("course-a")
    .mockReturnValueOnce("course-b");
  vi.mocked(api.createStudioCourse)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOriginal = resolve;
        }),
    )
    .mockResolvedValueOnce(response())
    .mockRejectedValue(new Error("Connection lost"));
  await mount();
  await click("Create course");
  await type("Sales foundations");
  await click("Create draft");
  await remount();
  await click("Check saved course");
  await click("Close");
  await click("Create course");
  await type("Advanced sales");
  await click("Create draft");
  await act(async () => finishOriginal(response()));
  await remount();
  expect(container.querySelector("input")?.value).toBe("Advanced sales");
  expect(container.querySelector("input")?.disabled).toBe(true);
  await click("Check saved course");
  expect(vi.mocked(api.createStudioCourse).mock.calls.at(-1)?.[0]).toEqual({
    tenantId: tenant,
    title: "Advanced sales",
    idempotencyKey: "course-b",
  });
});

it("does not retain an old identity's late receipt in the newly verified session", async () => {
  let finishOriginal!: (value: api.StudioDraftMutationResponse) => void;
  vi.mocked(api.createStudioCourse).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOriginal = resolve;
      }),
  );
  await mount();
  await click("Create course");
  await type("Private draft");
  await click("Create draft");
  if (account.status !== "ready") throw new Error("fixture");
  account = {
    ...account,
    session: { ...account.session, sessionId: crypto.randomUUID() },
  };
  await mount();
  await act(async () => finishOriginal(response()));
  await remount();
  await click("Create course");
  expect(container.querySelector("input")?.value).toBe("");
  expect(container.textContent).not.toContain("Your course is saved");
});
