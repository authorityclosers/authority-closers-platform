// @vitest-environment happy-dom
import { act, StrictMode, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "@ac/operations-web/api";
import { StudioCourseEditor } from "./studio-course-editor";
import { PublishDraft, StudioProgram } from "./studio-runtime";
import * as videoApi from "../../../../../packages/typescript/operations-web/src/studio/studio-video-api";
import { activateStudioVideoRecoveryScope } from "../../../../../packages/typescript/operations-web/src/studio/studio-video-panel";
import * as adminSession from "@ac/operations-web/session";
import {
  activateStudioRecoveryScope,
  readStudioDraft,
  readStudioPublication,
  retainStudioPublication,
  readStudioRevision,
  retainStudioRevision,
} from "./studio-draft-recovery";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const tenantId = "11111111-1111-4111-8111-111111111111";
const programId = "22222222-2222-4222-8222-222222222222";
const versionId = "33333333-3333-4333-8333-333333333333";
const moduleId = "44444444-4444-4444-8444-444444444444";
const activityId = "55555555-5555-4555-8555-555555555555";
const addedId = "66666666-6666-4666-8666-666666666666";
const originalEtag = '"program-version-' + "a".repeat(64) + '"';
const newEtag = '"program-version-' + "b".repeat(64) + '"';

function program(): api.StudioProgramDetail {
  return {
    tenant_id: tenantId,
    id: programId,
    slug: "synthetic-course",
    title: "Synthetic sales course",
    scope: "tenant",
    access: "selected_tenant",
    versions_truncated: false,
    versions: [
      {
        id: versionId,
        version_number: 1,
        status: "draft",
        created_at: "2026-09-08T00:00:00Z",
        published_at: null,
        supersedes_version_id: null,
        content_source_ref: null,
        content_reviewed_by: null,
        content_reviewed_at: null,
        release_id: null,
        content_seed_kind: null,
        content_digest: null,
        etag: originalEtag,
        readiness: "blocked",
        blockers: ["provenance_incomplete"],
        modules: [
          {
            id: moduleId,
            position: 1,
            title: "Listen first",
            prerequisite_module_ids: [],
            activities: [
              {
                id: activityId,
                position: 1,
                kind: "REFLECTION",
                title: "Ask a clear question",
                prompt: "What would clarify their goal?",
                is_required: true,
              },
            ],
          },
        ],
      },
    ],
  };
}

function savedActivity(
  title: string,
  prompt = "What would clarify their goal?",
) {
  const next = program();
  next.versions[0].etag = newEtag;
  Object.assign(next.versions[0].modules[0].activities[0], { title, prompt });
  return { program: next, resource_id: activityId, replayed: false };
}

function problem(status: number, code: string) {
  return new api.AdminApiProblem({
    status,
    code,
    title: "Synthetic rejection",
    detail: "The draft cannot be saved yet.",
    requestId: "synthetic-request",
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

let container: HTMLDivElement;
let root: Root;
let unmounted: boolean;
let publicationRefresh: (() => void) | undefined;
let publicationPending: ((pending: boolean) => void) | undefined;
const renderPublication = vi.fn<
  ComponentProps<typeof StudioCourseEditor>["renderPublication"]
>((_version, refresh, setPending) => {
  publicationRefresh = refresh;
  publicationPending = setPending;
  return <p>Canonical publication control</p>;
});

beforeEach(() => {
  activateStudioRecoveryScope("");
  activateStudioVideoRecoveryScope("");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
  publicationRefresh = undefined;
  publicationPending = undefined;
  renderPublication.mockClear();
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockRejectedValue(new Error("Unexpected network")),
  );
  vi.spyOn(api, "appendStudioModule").mockRejectedValue(
    new Error("Unexpected module append"),
  );
  vi.spyOn(api, "createStudioRevision").mockRejectedValue(
    new Error("Unexpected revision"),
  );
  vi.spyOn(api, "updateStudioModule").mockRejectedValue(
    new Error("Unexpected module edit"),
  );
  vi.spyOn(api, "appendStudioActivity").mockRejectedValue(
    new Error("Unexpected activity append"),
  );
  vi.spyOn(api, "updateStudioActivity").mockRejectedValue(
    new Error("Unexpected activity edit"),
  );
  vi.spyOn(api, "loadStudioProgram").mockRejectedValue(
    new Error("Unexpected reload"),
  );
  let key = 0;
  vi.spyOn(api, "newIdempotencyKey").mockImplementation(
    () => `synthetic-command-${++key}`,
  );
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
});

afterEach(async () => {
  activateStudioRecoveryScope("");
  activateStudioVideoRecoveryScope("");
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function mount(
  initialProgram = program(),
  canWrite = true,
  contextKey = "synthetic-scope-1",
  recoveryContext = "",
) {
  await act(async () =>
    root.render(
      <StrictMode>
        <StudioCourseEditor
          key={contextKey}
          initialProgram={initialProgram}
          canWrite={canWrite}
          recoveryContext={recoveryContext}
          renderPublication={renderPublication}
        />
      </StrictMode>,
    ),
  );
}

function button(text: string | RegExp) {
  const found = [...container.querySelectorAll("button")]
    .reverse()
    .find((node) => {
      const label = node.textContent?.replace(/\s+/g, " ").trim() ?? "";
      return typeof text === "string" ? label === text : text.test(label);
    });
  expect(found, `button ${String(text)}`).toBeDefined();
  return found!;
}

function input(label = "Lesson title") {
  const found =
    container.querySelector(`[aria-label="${label}"]`) ??
    [...container.querySelectorAll("label")]
      .find((node) => node.textContent?.startsWith(label))
      ?.querySelector("input,textarea,select");
  expect(found, `input ${label}`).toBeDefined();
  return found as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
}

async function type(value: string, label = "Lesson title") {
  const node = input(label);
  const prototype =
    node instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : node instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(node, value);
    node.dispatchEvent(
      new Event(node instanceof HTMLSelectElement ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
}

async function click(node: HTMLElement) {
  await act(async () => node.click());
}

function expectNoMutation() {
  expect(api.createStudioRevision).not.toHaveBeenCalled();
  expect(api.appendStudioModule).not.toHaveBeenCalled();
  expect(api.updateStudioModule).not.toHaveBeenCalled();
  expect(api.appendStudioActivity).not.toHaveBeenCalled();
  expect(api.updateStudioActivity).not.toHaveBeenCalled();
}

function publishedProgram() {
  const next = program();
  Object.assign(next.versions[0], {
    status: "published",
    readiness: "immutable",
    blockers: [],
    published_at: "2026-09-09T00:00:00Z",
  });
  return next;
}
function createdRevision() {
  const next = publishedProgram();
  const draft = structuredClone(program().versions[0]);
  Object.assign(draft, {
    id: addedId,
    version_number: 2,
    supersedes_version_id: versionId,
    etag: newEtag,
  });
  next.versions.unshift(draft);
  return { program: next, resource_id: addedId, replayed: false };
}
it("creates an editable revision only after confirmation and opens the returned version", async () => {
  vi.mocked(api.createStudioRevision).mockResolvedValue(createdRevision());
  await mount(publishedProgram());
  expect(input()).toHaveProperty("readOnly", true);
  await click(button("Create editable revision"));
  expect(container.textContent).toContain(
    "Videos and other media need to be connected",
  );
  expect(container.textContent).toContain("fresh content review");
  expectNoMutation();
  await click(button("Not now"));
  expectNoMutation();
  await click(button("Create editable revision"));
  await click(button("Create draft revision"));
  expect(api.createStudioRevision).toHaveBeenCalledTimes(1);
  expect(api.createStudioRevision).toHaveBeenCalledWith(
    expect.objectContaining({
      programVersionId: versionId,
      programId,
      tenantId,
      ifMatch: originalEtag,
    }),
  );
  expect(input()).toHaveProperty("readOnly", false);
  expect(input("Course version").value).toBe(addedId);
  expect(container.textContent).toContain("Draft revision created");
});
it("opens an existing revision without creating another copy", async () => {
  const next = createdRevision().program;
  await mount(next);
  await type(versionId, "Course version");
  await click(button("Open draft v2"));
  expect(input("Course version").value).toBe(addedId);
  expectNoMutation();
});
it("freezes and recovers the exact revision command after an uncertain response", async () => {
  const scope = "revision-recovery-scope";
  activateStudioRecoveryScope(scope);
  await mount(publishedProgram(), true, "first-mount", scope);
  await click(button("Create editable revision"));
  await click(button("Create draft revision"));
  const first = vi.mocked(api.createStudioRevision).mock.calls[0][0];
  expect(readStudioRevision(scope, programId)).toEqual({
    programVersionId: versionId,
    ifMatch: originalEtag,
    idempotencyKey: first.idempotencyKey,
  });
  expect(input("Course version").disabled).toBe(true);
  await mount(publishedProgram(), true, "recovered-mount", scope);
  vi.mocked(api.createStudioRevision).mockResolvedValue({
    ...createdRevision(),
    replayed: true,
  });
  await click(button("Check revision"));
  const replay = vi.mocked(api.createStudioRevision).mock.calls[1][0];
  expect(replay).toMatchObject({
    programVersionId: first.programVersionId,
    ifMatch: first.ifMatch,
    idempotencyKey: first.idempotencyKey,
  });
  expect(readStudioRevision(scope, programId)).toBeNull();
  expect(input("Course version").value).toBe(addedId);
});
it("prevents duplicate submissions and blocks leaving while revision creation is unresolved", async () => {
  const pendingRevision = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.createStudioRevision).mockReturnValue(pendingRevision.promise);
  await mount(publishedProgram());
  await click(button("Create editable revision"));
  await click(button("Create draft revision"));
  await click(button("Creating revision…"));
  expect(api.createStudioRevision).toHaveBeenCalledTimes(1);
  const beforeUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(beforeUnload);
  expect(beforeUnload.defaultPrevented).toBe(true);
  expect(button("Publication").disabled).toBe(true);
  await act(async () => pendingRevision.resolve(createdRevision()));
  expect(input("Course version").disabled).toBe(false);
});
it.each([401, 403, 404, 410])(
  "preserves an uncertain revision across denied replay %s and recovers with the same key",
  async (status) => {
    const scope = `uncertain-access-${status}`;
    activateStudioRecoveryScope(scope);
    await mount(publishedProgram(), true, "uncertain-mount", scope);
    await click(button("Create editable revision"));
    await click(button("Create draft revision"));
    const first = readStudioRevision(scope, programId);
    vi.mocked(api.createStudioRevision).mockRejectedValue(
      problem(status, "access-denied"),
    );
    await click(button("Check revision"));
    expect(readStudioRevision(scope, programId)).toEqual(first);
    expect(input("Course version").disabled).toBe(true);
    expect(container.textContent).toContain(
      "earlier request may already have created a revision",
    );
    vi.mocked(api.createStudioRevision).mockResolvedValue({
      ...createdRevision(),
      replayed: true,
    });
    await click(button("Check revision"));
    expect(vi.mocked(api.createStudioRevision).mock.calls[2][0]).toMatchObject(
      first!,
    );
    expect(readStudioRevision(scope, programId)).toBeNull();
    expect(input("Course version").value).toBe(addedId);
  },
);
it.each([401, 403, 404, 409, 412, 422])(
  "does not loop an unaccepted revision command after %s",
  async (status) => {
    const scope = `rejection-${status}`;
    activateStudioRecoveryScope(scope);
    vi.mocked(api.createStudioRevision).mockRejectedValue(
      problem(status, "revision-rejected"),
    );
    await mount(publishedProgram(), true, "rejection-mount", scope);
    await click(button("Create editable revision"));
    await click(button("Create draft revision"));
    expect(readStudioRevision(scope, programId)).toBeNull();
    expect(container.textContent).toContain("Reopen course");
    expect(input()).toHaveProperty("readOnly", true);
    expect(container.textContent).not.toContain("Check revision");
  },
);
it("offers no revision without write access, on global content, or for superseded history", async () => {
  await mount(publishedProgram(), false);
  expect(container.textContent).not.toContain("Create editable revision");
  const global = publishedProgram();
  Object.assign(global, { scope: "global", access: "global_read_only" });
  await mount(global, true, "global-mount");
  expect(container.textContent).not.toContain("Create editable revision");
  const superseded = publishedProgram();
  superseded.versions[0].status = "superseded";
  await mount(superseded, true, "superseded-mount");
  expect(container.textContent).not.toContain("Create editable revision");
  expectNoMutation();
});
it("can recover a revision even when its source falls out of bounded course history", async () => {
  const scope = "old-revision";
  activateStudioRecoveryScope(scope);
  retainStudioRevision(scope, programId, {
    programVersionId: versionId,
    ifMatch: originalEtag,
    idempotencyKey: "old-key",
  });
  const next = program();
  next.versions = [];
  await mount(next, true, "old-source-mount", scope);
  vi.mocked(api.createStudioRevision).mockResolvedValue({
    ...createdRevision(),
    replayed: true,
  });
  await click(button("Check revision"));
  expect(input("Course version").value).toBe(addedId);
});
it("does not apply an old revision response after the editor unmounts", async () => {
  const response = deferred<api.StudioDraftMutationResponse>();
  const scope = "unmounted-revision";
  activateStudioRecoveryScope(scope);
  vi.mocked(api.createStudioRevision).mockReturnValue(response.promise);
  await mount(publishedProgram(), true, "revision-before-unmount", scope);
  await click(button("Create editable revision"));
  await click(button("Create draft revision"));
  const signal = vi.mocked(api.createStudioRevision).mock.calls[0][0].signal;
  await act(async () => root.unmount());
  unmounted = true;
  expect(signal?.aborted).toBe(true);
  await act(async () => response.resolve(createdRevision()));
  expect(readStudioRevision(scope, programId)?.idempotencyKey).toBeDefined();
});

it("does not write on mount, StrictMode, preview, or publication inspection", async () => {
  await mount();
  expect(input().value).toBe("Ask a clear question");
  await click(button("Preview"));
  expect(container.textContent).toContain("no learner progress is recorded");
  await click(button("Publication"));
  expect(container.textContent).toContain("Canonical publication control");
  expect(container.textContent).toContain(
    "Record the source and a complete content review.",
  );
  expectNoMutation();
  expect(api.loadStudioProgram).not.toHaveBeenCalled();
});

it("surfaces a learner-facing authoring hierarchy without exposing audit fields", async () => {
  await mount();
  expect(
    container.querySelector('[aria-label="Course summary"]'),
  ).toBeDefined();
  expect(container.textContent).toContain("Build the learner experience");
  expect(container.textContent).toContain(
    "Choose a section to edit. Lessons appear in learner order.",
  );
  expect(container.textContent).toContain("1 module");
  expect(container.textContent).toContain("1 lesson");
  await click(button("Publication"));
  expect(container.textContent).toContain("Review before learners see it.");
  expect(container.textContent).toContain("Review record");
  expect(container.textContent).not.toContain("Content digest");
  expect(container.textContent).not.toContain("release_id");
});

it("saves an explicit snapshot and preserves newer text typed while it is in flight", async () => {
  const request = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.updateStudioActivity).mockReturnValue(request.promise);
  await mount();
  await type("Submitted title");
  await click(button("Save changes"));
  expect(api.updateStudioActivity).toHaveBeenCalledExactlyOnceWith({
    programVersionId: versionId,
    activityId,
    title: "Submitted title",
    prompt: "What would clarify their goal?",
    ifMatch: originalEtag,
    idempotencyKey: "synthetic-command-1",
  });
  expect(button("Saving…").disabled).toBe(true);
  await type("Newer unsaved title");
  await act(async () => request.resolve(savedActivity("Submitted title")));
  expect(input().value).toBe("Newer unsaved title");
  expect(container.textContent).toContain(
    "Your newer changes still need saving",
  );
  vi.mocked(api.updateStudioActivity).mockResolvedValue(
    savedActivity("Newer unsaved title"),
  );
  await click(button("Save changes"));
  expect(vi.mocked(api.updateStudioActivity).mock.calls[1][0]).toMatchObject({
    title: "Newer unsaved title",
    ifMatch: newEtag,
    idempotencyKey: "synthetic-command-2",
  });
});

it("does not issue two commands for repeated synchronous submission", async () => {
  const request = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.updateStudioActivity).mockReturnValue(request.promise);
  await mount();
  await type("One submission");
  await act(async () => {
    const form = container.querySelector("form")!;
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
  await act(async () => request.resolve(savedActivity("One submission")));
});

it("replays unknown outcomes with the original intent even if current text is emptied", async () => {
  vi.mocked(api.updateStudioActivity).mockRejectedValueOnce(
    new TypeError("Connection lost"),
  );
  await mount();
  await type("Original command");
  await click(button("Save changes"));
  expect(container.textContent).toContain("couldn’t confirm the save");
  await type("");
  expect(button("Check save").disabled).toBe(false);
  vi.mocked(api.updateStudioActivity).mockResolvedValue({
    ...savedActivity("Original command"),
    replayed: true,
  });
  await click(button("Check save"));
  const [first, second] = vi.mocked(api.updateStudioActivity).mock.calls;
  expect(second[0]).toEqual(first[0]);
  expect(api.loadStudioProgram).not.toHaveBeenCalled();
  expect(input().value).toBe("");
  expect(container.textContent).toContain(
    "Your newer changes still need saving",
  );
});

it("requires an explicit comparison choice after a precondition conflict", async () => {
  vi.mocked(api.updateStudioActivity).mockRejectedValueOnce(
    problem(412, "studio_draft_precondition_failed"),
  );
  await mount();
  await type("My unsaved title");
  await click(button("Save changes"));
  expect(input().value).toBe("My unsaved title");
  vi.mocked(api.loadStudioProgram).mockResolvedValue(
    savedActivity("Another editor's title").program,
  );
  await click(button("Compare latest draft"));
  expect(input().value).toBe("My unsaved title");
  expect(container.textContent).toContain("Another editor's title");
  expect(button("Save changes").disabled).toBe(true);
  await click(button("Keep my edits"));
  vi.mocked(api.updateStudioActivity).mockResolvedValue(
    savedActivity("My unsaved title"),
  );
  await click(button("Save changes"));
  expect(vi.mocked(api.updateStudioActivity).mock.calls[1][0]).toMatchObject({
    title: "My unsaved title",
    ifMatch: newEtag,
    idempotencyKey: "synthetic-command-2",
  });
});

it("only replaces unsaved content after choosing the latest saved comparison", async () => {
  vi.mocked(api.updateStudioActivity).mockRejectedValueOnce(
    problem(409, "studio_draft_conflict"),
  );
  await mount();
  await type("Local text");
  await click(button("Save changes"));
  vi.mocked(api.loadStudioProgram).mockResolvedValue(
    savedActivity("Server text").program,
  );
  await click(button("Compare latest draft"));
  await click(button("Use latest saved content"));
  expect(input().value).toBe("Server text");
  expect(button("Save changes").disabled).toBe(true);
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
});

it("does not silently overwrite local text when a successful replay returns newer server content", async () => {
  vi.mocked(api.updateStudioActivity).mockResolvedValue({
    ...savedActivity("Changed after original save"),
    replayed: true,
  });
  await mount();
  await type("Original replayed edit");
  await click(button("Save changes"));
  expect(input().value).toBe("Original replayed edit");
  expect(container.textContent).toContain("Your earlier save was recorded");
  expect(button("Save changes").disabled).toBe(true);
  expect(button("Keep my edits")).toBeDefined();
});

it.each([401, 403, 404, 410])(
  "preserves copyable text and disables further mutation on HTTP %i",
  async (status) => {
    vi.mocked(api.updateStudioActivity).mockRejectedValueOnce(
      problem(status, "admin_authorization_denied"),
    );
    await mount();
    await type("Keep this text");
    await click(button("Save changes"));
    expect(input().value).toBe("Keep this text");
    expect((input() as HTMLInputElement).readOnly).toBe(true);
    expect(button("Save changes").disabled).toBe(true);
    expect(container.textContent).toContain(
      "unsaved text is still here to copy",
    );
  },
);

it.each(["published", "superseded", "no-write", "global"])(
  "never offers mutation for %s content",
  async (mode) => {
    const initial = program();
    if (mode === "published" || mode === "superseded") {
      Object.assign(initial.versions[0], {
        status: mode,
        etag: null,
        readiness: "immutable",
      });
    }
    if (mode === "global")
      Object.assign(initial, { scope: "global", access: "global_read_only" });
    await mount(initial, mode !== "no-write");
    expect((input() as HTMLInputElement).readOnly).toBe(true);
    expect(button("Save changes").disabled).toBe(true);
    expectNoMutation();
  },
);

it("requires a discard decision before switching away from unsaved activity edits", async () => {
  await mount();
  await type("Unsaved activity");
  await click(button(/01Listen first/));
  expect(container.querySelector("dialog")?.hasAttribute("open")).toBe(true);
  await click(button("Keep editing"));
  expect(input().value).toBe("Unsaved activity");
  await click(button(/01Listen first/));
  await click(button("Discard unsaved edits"));
  expect(input("Module title").value).toBe("Listen first");
  expectNoMutation();
});

it("appends a module once and selects the returned canonical resource", async () => {
  await mount();
  await click(button("Add module"));
  await type("New module", "Module title");
  const next = program();
  next.versions[0].etag = newEtag;
  next.versions[0].modules.push({
    id: addedId,
    position: 2,
    title: "New module",
    prerequisite_module_ids: [],
    activities: [],
  });
  vi.mocked(api.appendStudioModule).mockResolvedValue({
    program: next,
    resource_id: addedId,
    replayed: false,
  });
  await click(button("Add module"));
  expect(api.appendStudioModule).toHaveBeenCalledExactlyOnceWith({
    programVersionId: versionId,
    title: "New module",
    ifMatch: originalEtag,
    idempotencyKey: "synthetic-command-1",
  });
  expect(container.textContent).toContain("Edit module");
  expect(input("Module title").value).toBe("New module");
  expect(button("Save changes").disabled).toBe(true);
  expect(container.textContent).toContain(
    "Your module is ready for its first lesson",
  );
  await click(button("Add your first lesson"));
  expect(container.textContent).toContain("New lesson");
  expect(input().value).toBe("");
  expect(container.querySelectorAll('input[type="radio"]')).toHaveLength(5);
  expect(api.appendStudioModule).toHaveBeenCalledOnce();
  expect(api.appendStudioActivity).not.toHaveBeenCalled();
});

it("replaces a prior Saved message when the learner-facing text is edited again", async () => {
  vi.mocked(api.updateStudioActivity).mockResolvedValue(
    savedActivity("Saved title"),
  );
  await mount();
  await type("Saved title");
  await click(button("Save changes"));
  expect(
    container.querySelector('footer [role="status"]')?.textContent,
  ).toContain("Saved to draft");
  await type("Newer title");
  expect(container.querySelector('footer [role="status"]')?.textContent).toBe(
    "Unsaved changes",
  );
  expect(button("Save changes").disabled).toBe(false);
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
});

it("explains lesson formats without mutating a draft or clearing typed content", async () => {
  await mount();
  await click(button(/^Add lesson/));
  const formats = container.querySelector(
    "details:has(fieldset)",
  ) as HTMLDetailsElement;
  expect(formats.open).toBe(false);
  await click(formats.querySelector("summary")!);
  expect(formats.open).toBe(true);
  expect(container.querySelector("fieldset legend")?.textContent).toBe(
    "What would you like to add?",
  );
  await type("A clear lesson title");
  for (const kind of [
    "VIDEO",
    "REFLECTION",
    "IMPLEMENTATION_CHALLENGE",
    "REVIEW",
    "IMPROVE",
  ]) {
    const option = container.querySelector(
      `input[type="radio"][value="${kind}"]`,
    ) as HTMLInputElement;
    await click(option);
    expect(option.checked).toBe(true);
    expect(option.getAttribute("aria-label")).toBeTruthy();
    const hint = document.getElementById(
      option.getAttribute("aria-describedby")!,
    );
    expect(hint?.textContent).toBeTruthy();
    expect(input().value).toBe("A clear lesson title");
    expect(formats.querySelector("summary strong")?.textContent).toBe(
      option.getAttribute("aria-label"),
    );
  }
  expectNoMutation();
  await click(formats.querySelector("summary")!);
  expect(formats.open).toBe(false);
});

it("locks immutable lesson choices while creation is saving or its outcome is unknown", async () => {
  const request = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.appendStudioActivity).mockReturnValue(request.promise);
  await mount();
  await click(button(/^Add lesson/));
  await type("A video lesson");
  await click(
    container.querySelector(
      'input[type="radio"][value="VIDEO"]',
    ) as HTMLInputElement,
  );
  await click(button("Create lesson"));
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
  expect(
    (container.querySelector('input[type="checkbox"]') as HTMLInputElement)
      .disabled,
  ).toBe(true);
  await act(async () => request.reject(problem(503, "unavailable")));
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
  expect(
    (container.querySelector('input[type="checkbox"]') as HTMLInputElement)
      .disabled,
  ).toBe(true);
  expect(button("Check save")).toBeDefined();
  expect(api.appendStudioActivity).toHaveBeenCalledOnce();
});

it("appends the explicitly selected activity kind and required choice", async () => {
  await mount();
  await click(button(/^Add lesson/));
  await type("Watch the conversation");
  await click(
    container.querySelector(
      'input[type="radio"][value="VIDEO"]',
    ) as HTMLInputElement,
  );
  const required = container.querySelector(
    'input[type="checkbox"]',
  ) as HTMLInputElement;
  await click(required);
  const next = program();
  next.versions[0].etag = newEtag;
  next.versions[0].modules[0].activities.push({
    id: addedId,
    position: 2,
    kind: "VIDEO",
    title: "Watch the conversation",
    prompt: null,
    is_required: false,
  });
  vi.mocked(api.appendStudioActivity).mockResolvedValue({
    program: next,
    resource_id: addedId,
    replayed: false,
  });
  await click(button("Create lesson"));
  expect(api.appendStudioActivity).toHaveBeenCalledExactlyOnceWith({
    programVersionId: versionId,
    moduleId,
    kind: "VIDEO",
    title: "Watch the conversation",
    prompt: null,
    isRequired: false,
    ifMatch: originalEtag,
    idempotencyKey: "synthetic-command-1",
  });
  expect(input().value).toBe("Watch the conversation");
});

it("does not apply a previous actor's late response after its keyed editor unmounts", async () => {
  const request = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.updateStudioActivity).mockReturnValue(request.promise);
  await mount();
  await type("Previous actor save");
  await click(button("Save changes"));
  await mount(program(), false, "different-actor-session");
  await act(async () => request.resolve(savedActivity("Previous actor save")));
  expect(input().value).toBe("Ask a clear question");
  expect((input() as HTMLInputElement).readOnly).toBe(true);
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
});

it("does not replace a newer save's version with a late publication refresh", async () => {
  const refresh = deferred<api.StudioProgramDetail>();
  vi.mocked(api.loadStudioProgram).mockReturnValue(refresh.promise);
  await mount();
  await click(button("Publication"));
  await act(async () => publicationRefresh!());
  await click(button("Content"));
  await type("Saved after refresh began");
  vi.mocked(api.updateStudioActivity).mockResolvedValue(
    savedActivity("Saved after refresh began"),
  );
  await click(button("Save changes"));
  await act(async () => refresh.resolve(program()));
  await type("Next edit");
  vi.mocked(api.updateStudioActivity).mockResolvedValue(
    savedActivity("Next edit"),
  );
  await click(button("Save changes"));
  expect(
    vi.mocked(api.updateStudioActivity).mock.calls.at(-1)?.[0],
  ).toMatchObject({
    title: "Next edit",
    ifMatch: newEtag,
  });
});

it("does not perform a follow-up read or mutation after unmount", async () => {
  const request = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.updateStudioActivity).mockReturnValue(request.promise);
  await mount();
  await type("In-flight save");
  await click(button("Save changes"));
  await act(async () => root.unmount());
  unmounted = true;
  await act(async () => request.resolve(savedActivity("In-flight save")));
  expect(container.childElementCount).toBe(0);
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
  expect(api.loadStudioProgram).not.toHaveBeenCalled();
});

it("keeps pending publication mounted and locks content navigation until the controller resolves it", async () => {
  await mount();
  await click(button("Publication"));
  await act(async () => publicationPending!(true));
  expect(container.textContent).toContain("Canonical publication control");
  expect(button("Content").disabled).toBe(true);
  expect(button("Preview").disabled).toBe(true);
  expect(button(/01Listen first/).disabled).toBe(true);
  expect(
    (
      container.querySelector(
        '[aria-label="Course version"]',
      ) as HTMLSelectElement
    ).disabled,
  ).toBe(true);
  await act(async () => publicationPending!(false));
  expect(button("Content").disabled).toBe(false);
  await click(button("Content"));
  expect(input().value).toBe("Ask a clear question");
  expectNoMutation();
});

it("does not clear uncertain-save recovery or its leave lock when an older refresh fails", async () => {
  const refresh = deferred<api.StudioProgramDetail>();
  vi.mocked(api.loadStudioProgram).mockReturnValue(refresh.promise);
  await mount();
  await click(button("Publication"));
  await act(async () => publicationRefresh!());
  await click(button("Content"));
  await type("Unconfirmed command");
  vi.mocked(api.updateStudioActivity).mockRejectedValue(
    new TypeError("Save outcome unknown"),
  );
  await click(button("Save changes"));
  await act(async () => refresh.reject(new TypeError("Older refresh failed")));
  expect(button("Check save").disabled).toBe(false);
  expect(button(/01Listen first/).disabled).toBe(true);
  const anchor = container.querySelector(
    'a[href="/studio/programs"]',
  ) as HTMLAnchorElement;
  await click(anchor);
  expect(container.querySelector("dialog")?.hasAttribute("open")).toBe(true);
  expect(container.textContent).toContain("Resolve your save first");
  expect(
    [...container.querySelectorAll("button")].some(
      (node) => node.textContent === "Discard unsaved edits",
    ),
  ).toBe(false);
});

const recoveryScope = "same-verified-tenant/person/session/capabilities";
async function spaLeave() {
  await act(async () => root.render(<p>Another SPA page</p>));
}

it("recovers unsaved text on same-document Back only within the freshly authorized scope", async () => {
  activateStudioRecoveryScope(recoveryScope);
  await mount(program(), true, "first-mount", recoveryScope);
  await type("Recovered private edits");
  await spaLeave();
  expect(readStudioDraft(recoveryScope, programId)?.fields.title).toBe(
    "Recovered private edits",
  );
  await mount(program(), true, "back-mount", recoveryScope);
  expect(input().value).toBe("Recovered private edits");
  expect(container.textContent).toContain("unsaved edits were recovered");
  expectNoMutation();
});

it("requires comparison instead of rebasing recovered edits onto a changed ETag", async () => {
  activateStudioRecoveryScope(recoveryScope);
  await mount(program(), true, "before-back", recoveryScope);
  await type("My recovered changes");
  await spaLeave();
  await mount(
    savedActivity("Other editor's changes").program,
    true,
    "after-back",
    recoveryScope,
  );
  expect(input().value).toBe("My recovered changes");
  expect(button("Compare latest draft")).toBeDefined();
  expectNoMutation();
});

it("retains the frozen in-flight command across Back and explicitly replays it after publication", async () => {
  const original = deferred<api.StudioDraftMutationResponse>();
  vi.mocked(api.updateStudioActivity).mockReturnValueOnce(original.promise);
  activateStudioRecoveryScope(recoveryScope);
  await mount(program(), true, "before-back", recoveryScope);
  await type("Saved while away");
  await click(button("Save changes"));
  const first = vi.mocked(api.updateStudioActivity).mock.calls[0][0];
  await spaLeave();
  const published = savedActivity("Saved while away");
  Object.assign(published.program.versions[0], {
    status: "published",
    readiness: "immutable",
    etag: null,
    published_at: "2026-09-08T04:00:00Z",
  });
  await mount(published.program, true, "after-back", recoveryScope);
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
  expect(button("Check save").disabled).toBe(false);
  vi.mocked(api.updateStudioActivity).mockResolvedValueOnce({
    ...published,
    replayed: true,
  });
  await click(button("Check save"));
  expect(vi.mocked(api.updateStudioActivity).mock.calls[1][0]).toEqual(first);
  await act(async () => original.resolve(published));
  expect(readStudioDraft(recoveryScope, programId)).toBeNull();
});

it("does not restore private edits after the verified session or capabilities change", async () => {
  activateStudioRecoveryScope(recoveryScope);
  await mount(program(), true, "before-back", recoveryScope);
  await type("Previous actor private text");
  await spaLeave();
  activateStudioRecoveryScope("different-session");
  await mount(program(), true, "new-account", "different-session");
  expect(input().value).toBe("Ask a clear question");
  expectNoMutation();
});

it("can check only the frozen command when its version is outside the fresh bounded history", async () => {
  activateStudioRecoveryScope(recoveryScope);
  vi.mocked(api.updateStudioActivity).mockRejectedValueOnce(
    new TypeError("Unknown outcome"),
  );
  await mount(program(), true, "before-history", recoveryScope);
  await type("Older saved intent");
  await click(button("Save changes"));
  const original = vi.mocked(api.updateStudioActivity).mock.calls[0][0];
  await spaLeave();
  const fresh = program();
  fresh.versions = [];
  fresh.versions_truncated = true;
  await mount(fresh, true, "after-history", recoveryScope);
  expect(input("Recovered title").value).toBe("Older saved intent");
  expect(api.updateStudioActivity).toHaveBeenCalledOnce();
  vi.mocked(api.updateStudioActivity).mockResolvedValue({
    ...savedActivity("Older saved intent"),
    replayed: true,
  });
  await click(button("Check save"));
  expect(vi.mocked(api.updateStudioActivity).mock.calls[1][0]).toEqual(
    original,
  );
  expect(input().value).toBe("Older saved intent");
});

it("explicit discard clears recovery and bypasses only the subsequent unload warning", async () => {
  activateStudioRecoveryScope(recoveryScope);
  await mount(program(), true, "discard", recoveryScope);
  await type("Discard this");
  await click(button(/01Listen first/));
  await click(button("Discard unsaved edits"));
  expect(readStudioDraft(recoveryScope, programId)).toBeNull();
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);
  await type("Keep this next edit", "Module title");
  const next = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(next);
  expect(next.defaultPrevented).toBe(true);
});

it("reopens directly into publication recovery without automatically executing it", async () => {
  activateStudioRecoveryScope(recoveryScope);
  retainStudioPublication(recoveryScope, programId, {
    programVersionId: versionId,
    reason: "Reviewed",
    ifMatch: originalEtag,
    idempotencyKey: "old-publish-key",
  });
  await mount(program(), true, "publication-back", recoveryScope);
  expect(container.textContent).toContain("Canonical publication control");
  expect(button("Content").disabled).toBe(true);
  expectNoMutation();
});

it("recovers the exact publication command on a fresh published version without a second new command", async () => {
  activateStudioRecoveryScope(recoveryScope);
  const session: adminSession.AdminSessionState = {
    status: "ready",
    error: null,
    session: {
      personId: activityId,
      sessionId: moduleId,
      tenantId,
      membershipRole: "learner",
      email: "coach@example.test",
      displayName: "Synthetic coach",
      emailVerifiedAt: "2026-09-08T00:00:00Z",
      permissions: [],
      studioCapabilities: [
        {
          permission: "catalog_publish",
          scope_kind: "program",
          tenant_id: tenantId,
          program_id: programId,
        },
      ],
    },
  };
  vi.spyOn(adminSession, "useAdminSession").mockReturnValue(session);
  const request = deferred<api.ProgramVersionPublishResponse>();
  const publish = vi
    .spyOn(api, "publishProgramVersion")
    .mockReturnValueOnce(request.promise);
  const initial = program().versions[0];
  initial.readiness = "ready";
  const props = {
    programId,
    programTitle: "Synthetic sales course",
    recoveryContext: recoveryScope,
    onPublished: vi.fn(),
    onPendingChange: vi.fn(),
  };
  await act(async () =>
    root.render(<PublishDraft key="first" {...props} version={initial} />),
  );
  await type("Explicit review complete", "Publication reason");
  await click(
    container.querySelector('input[type="checkbox"]') as HTMLInputElement,
  );
  await click(button("Publish version 1"));
  const first = publish.mock.calls[0][0];
  await spaLeave();
  expect(readStudioPublication(recoveryScope, programId)).toEqual(first);
  const current = {
    ...initial,
    status: "published" as const,
    readiness: "immutable" as const,
    etag: null,
  };
  await act(async () =>
    root.render(<PublishDraft key="back" {...props} version={current} />),
  );
  expect(publish).toHaveBeenCalledOnce();
  expect(button("Check publication").disabled).toBe(false);
  const result: api.ProgramVersionPublishResponse = {
    id: versionId,
    program_id: programId,
    version_number: 1,
    status: "published",
    supersedes_version_id: null,
    published_at: "2026-09-08T04:00:00Z",
    replayed: true,
  };
  publish.mockResolvedValueOnce(result);
  await click(button("Check publication"));
  expect(publish.mock.calls[1][0]).toEqual(first);
  expect(readStudioPublication(recoveryScope, programId)).toBeNull();
  await act(async () => request.resolve(result));
  expect(props.onPublished).toHaveBeenCalledOnce();
});

function videoProgram() {
  const next = publishedProgram();
  next.versions[0].modules[0].activities.push({
    ...next.versions[0].modules[0].activities[0],
    id: addedId,
    position: 2,
    kind: "VIDEO",
    title: "Reviewed video source",
  });
  return next;
}

function prepareVideoRequests() {
  vi.spyOn(videoApi, "loadStudioActivityVideo").mockResolvedValue({
    activity_id: addedId,
    version_status: "published",
    binding: null,
  });
  vi.spyOn(videoApi, "loadStudioVideos").mockResolvedValue({
    items: [
      {
        asset_id: activityId,
        version_id: versionId,
        version_number: 1,
        label: "Private source.mp4",
        state: "ready",
        actual_bytes: 1000,
        duration_seconds: 10,
        width: 1920,
        height: 1080,
      },
    ],
    next_cursor: null,
  });
  return vi
    .spyOn(videoApi, "saveStudioActivityVideo")
    .mockRejectedValue(new TypeError("Unconfirmed response"));
}

async function beginVideoApproval() {
  await click(button(/Reviewed video source/));
  await click(
    container.querySelector('input[type="radio"]') as HTMLInputElement,
  );
  const approval = container.querySelector(
    'input[placeholder^="For example:"]',
  ) as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(approval, "Reviewed by instructor");
    approval.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click(button("Approve lesson video"));
}

it("mounts video approval outside the content form and protects all editor navigation until confirmed", async () => {
  const saveVideo = prepareVideoRequests();
  await mount(videoProgram(), true, "video", "stable-video-session");
  await beginVideoApproval();
  expect(saveVideo).toHaveBeenCalledOnce();
  expect(button("Retry same approval").closest("form")).toBeNull();
  expect(button("Preview").disabled).toBe(true);
  expect(button("Publication").disabled).toBe(true);
  expect(button(/01Listen first/).disabled).toBe(true);
  expect(
    (
      container.querySelector(
        '[aria-label="Course version"]',
      ) as HTMLSelectElement
    ).disabled,
  ).toBe(true);
  expect(button("Save changes").disabled).toBe(true);
  await click(
    container.querySelector('a[href="/studio/programs"]') as HTMLAnchorElement,
  );
  expect(container.querySelector("dialog")?.hasAttribute("open")).toBe(true);
  expect(container.textContent).toContain("Resolve your save first");
  expectNoMutation();
});

it("restores the exact pending video and selected lesson across same-session capability changes in the real Studio mount", async () => {
  const saveVideo = prepareVideoRequests();
  const detail = videoProgram();
  vi.mocked(api.loadStudioProgram).mockResolvedValue(detail);
  const session: adminSession.AdminSessionState = {
    status: "ready",
    error: null,
    session: {
      personId: activityId,
      sessionId: moduleId,
      tenantId,
      membershipRole: "learner",
      email: "coach@example.test",
      displayName: "Synthetic coach",
      emailVerifiedAt: "2026-09-08T00:00:00Z",
      permissions: [],
      studioCapabilities: ["catalog_read", "catalog_write"].map(
        (permission) => ({
          permission: permission as "catalog_read" | "catalog_write",
          scope_kind: "program" as const,
          tenant_id: tenantId,
          program_id: programId,
        }),
      ),
    },
  };
  const currentSession = vi
    .spyOn(adminSession, "useAdminSession")
    .mockReturnValue(session);
  const renderStudio = async () => {
    await act(async () => root.render(<StudioProgram programId={programId} />));
  };
  await renderStudio();
  await beginVideoApproval();
  const first = saveVideo.mock.calls[0][0];
  currentSession.mockReturnValue({
    ...session,
    session: {
      ...session.session,
      studioCapabilities: session.session.studioCapabilities.filter(
        (item) => item.permission === "catalog_read",
      ),
    },
  });
  await renderStudio();
  expect(container.textContent).not.toContain("Private source.mp4");
  expect(container.textContent).toContain(
    "earlier video request is unresolved",
  );
  currentSession.mockReturnValue(session);
  await renderStudio();
  expect(input().value).toBe("Reviewed video source");
  expect(button("Retry same approval").disabled).toBe(false);
  await click(button("Retry same approval"));
  const second = saveVideo.mock.calls[1][0];
  expect(second.idempotencyKey).toBe(first.idempotencyKey);
  expect(second.selection).toEqual(first.selection);
});
