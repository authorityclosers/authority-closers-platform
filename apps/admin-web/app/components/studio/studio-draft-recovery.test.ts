// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  activateStudioRecoveryScope,
  clearStudioDraft,
  clearStudioPublication,
  readStudioDraft,
  readStudioPublication,
  retainStudioDraft,
  retainStudioPublication,
  retainStudioRevision,
  readStudioRevision,
  clearStudioRevision,
  type StudioDraftRecovery,
} from "./studio-draft-recovery";

const scope = "synthetic-tenant/person/session/capabilities";
function draft(): StudioDraftRecovery {
  const fields = {
    title: "Private draft",
    prompt: "Private instructions",
    kind: "REFLECTION" as const,
    isRequired: true,
  };
  return {
    versionId: "version",
    selection: { type: "activity", moduleId: "module", activityId: "activity" },
    fields,
    baseline: { ...fields, title: "Saved title" },
    etag: "saved-etag",
    state: "unknown",
    pending: {
      versionId: "version",
      selection: {
        type: "activity",
        moduleId: "module",
        activityId: "activity",
      },
      fields,
      ifMatch: "saved-etag",
      idempotencyKey: "frozen-key",
    },
  };
}
const publication = {
  programVersionId: "version",
  reason: "Reviewed",
  ifMatch: "saved-etag",
  idempotencyKey: "publication-key",
};
beforeEach(() => {
  vi.useFakeTimers();
  activateStudioRecoveryScope("");
  activateStudioRecoveryScope(scope);
});
afterEach(() => {
  activateStudioRecoveryScope("");
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("returns independent snapshots and preserves the exact unknown command", () => {
  const original = draft();
  retainStudioDraft(scope, "course", original);
  original.fields.title = "Later changes";
  const restored = readStudioDraft(scope, "course")!;
  expect(restored.fields.title).toBe("Private draft");
  expect(restored.pending?.idempotencyKey).toBe("frozen-key");
  restored.pending!.fields.title = "Caller cannot change retained intent";
  expect(readStudioDraft(scope, "course")!.pending!.fields.title).toBe(
    "Private draft",
  );
});
it("retains revision intent independently without erasing draft or publication recovery", () => {
  retainStudioDraft(scope, "course", draft());
  retainStudioPublication(scope, "course", publication);
  const revision = {
    programVersionId: "source",
    ifMatch: "original-etag",
    idempotencyKey: "revision-key",
  };
  retainStudioRevision(scope, "course", revision);
  revision.idempotencyKey = "changed";
  expect(readStudioRevision(scope, "course")?.idempotencyKey).toBe(
    "revision-key",
  );
  clearStudioDraft(scope, "course");
  clearStudioPublication(scope, "course");
  expect(readStudioRevision(scope, "course")?.programVersionId).toBe("source");
  clearStudioRevision(scope, "course");
  expect(readStudioRevision(scope, "course")).toBeNull();
});
it("expires and scope-isolates revision commands", () => {
  const revision = {
    programVersionId: "source",
    ifMatch: "etag",
    idempotencyKey: "key",
  };
  retainStudioRevision(scope, "course", revision);
  vi.advanceTimersByTime(30 * 60 * 1000);
  expect(readStudioRevision(scope, "course")).toBeNull();
  retainStudioRevision(scope, "course", revision);
  activateStudioRecoveryScope("other-session");
  retainStudioRevision(scope, "course", revision);
  activateStudioRecoveryScope(scope);
  expect(readStudioRevision(scope, "course")).toBeNull();
});
it("keeps draft and publication recovery independent and explicitly clears each", () => {
  retainStudioDraft(scope, "course", draft());
  retainStudioPublication(scope, "course", publication);
  clearStudioDraft(scope, "course");
  expect(readStudioDraft(scope, "course")).toBeNull();
  expect(readStudioPublication(scope, "course")).toEqual(publication);
  clearStudioPublication(scope, "course");
  expect(readStudioPublication(scope, "course")).toBeNull();
});
it("purges on a changed verified actor/session/capability scope and rejects late old writes", () => {
  retainStudioDraft(scope, "course", draft());
  retainStudioPublication(scope, "course", publication);
  activateStudioRecoveryScope("new-verified-scope");
  retainStudioDraft(scope, "course", draft());
  expect(readStudioDraft(scope, "course")).toBeNull();
  activateStudioRecoveryScope(scope);
  expect(readStudioDraft(scope, "course")).toBeNull();
  expect(readStudioPublication(scope, "course")).toBeNull();
});
it("expires actual retained data after 30 idle minutes", () => {
  retainStudioDraft(scope, "course", draft());
  retainStudioPublication(scope, "course", publication);
  vi.advanceTimersByTime(30 * 60 * 1000 - 1);
  expect(readStudioDraft(scope, "course")).not.toBeNull();
  vi.advanceTimersByTime(1);
  expect(readStudioDraft(scope, "course")).toBeNull();
  expect(readStudioPublication(scope, "course")).toBeNull();
});
it("bounds retention to ten courses and never mixes their commands", () => {
  for (let index = 0; index < 11; index++)
    retainStudioPublication(scope, `course-${index}`, {
      ...publication,
      idempotencyKey: `key-${index}`,
    });
  expect(readStudioPublication(scope, "course-0")).toBeNull();
  expect(readStudioPublication(scope, "course-10")?.idempotencyKey).toBe(
    "key-10",
  );
  expect(readStudioPublication(scope, "unrelated")).toBeNull();
});
it("never reads or writes browser storage", () => {
  const get = vi.spyOn(Storage.prototype, "getItem");
  const set = vi.spyOn(Storage.prototype, "setItem");
  retainStudioDraft(scope, "course", draft());
  readStudioDraft(scope, "course");
  expect(get).not.toHaveBeenCalled();
  expect(set).not.toHaveBeenCalled();
});
it("does not retain or return recovery in a server-render environment", () => {
  vi.stubGlobal("window", undefined);
  retainStudioDraft(scope, "course", draft());
  expect(readStudioDraft(scope, "course")).toBeNull();
  vi.unstubAllGlobals();
  expect(readStudioDraft(scope, "course")).toBeNull();
});
