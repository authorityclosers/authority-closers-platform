import type { StudioActivityKind } from "../admin-api";

export type StudioSelection = {
  type: "module" | "activity" | "new-module" | "new-activity";
  moduleId: string;
  activityId?: string;
};
export type StudioFields = {
  title: string;
  prompt: string;
  kind: StudioActivityKind;
  isRequired: boolean;
};
export type StudioDraftCommand = {
  selection: StudioSelection;
  fields: StudioFields;
  versionId: string;
  ifMatch: string;
  idempotencyKey: string;
};
export type StudioDraftRecovery = {
  versionId: string;
  selection: StudioSelection;
  fields: StudioFields;
  baseline: StudioFields;
  etag: string | null;
  pending: StudioDraftCommand | null;
  state: "dirty" | "unknown" | "conflict" | "denied";
};
export type StudioPublicationCommand = {
  programVersionId: string;
  reason: string;
  ifMatch: string;
  idempotencyKey: string;
};
export type StudioRevisionCommand = {
  programVersionId: string;
  ifMatch: string;
  idempotencyKey: string;
};
type Recovery = {
  draft?: StudioDraftRecovery;
  publication?: StudioPublicationCommand;
  revision?: StudioRevisionCommand;
};

/** Same-document intent only, never authorization or a saved catalog snapshot.
 * Explicitly browser-only: no SSR cache, localStorage, sessionStorage or cookies.
 */
const lifetime = 30 * 60 * 1000;
let scope = "";
const drafts = new Map<
  string,
  { value: Recovery; expires: number; timer: ReturnType<typeof setTimeout> }
>();

function remove(programId: string) {
  const previous = drafts.get(programId);
  if (previous) clearTimeout(previous.timer);
  drafts.delete(programId);
}

export function activateStudioRecoveryScope(context: string) {
  if (typeof window === "undefined" || context === scope) return;
  for (const key of drafts.keys()) remove(key);
  scope = context;
}

function read(context: string, programId: string): Recovery | null {
  if (typeof window === "undefined" || !context || context !== scope)
    return null;
  const draft = drafts.get(programId);
  if (!draft) return null;
  if (draft.expires <= Date.now()) {
    remove(programId);
    return null;
  }
  return structuredClone(draft.value);
}

function write(
  context: string,
  programId: string,
  part: Partial<Recovery>,
  clear?: keyof Recovery,
) {
  if (typeof window === "undefined" || !context || context !== scope) return;
  const value = { ...read(context, programId), ...structuredClone(part) };
  if (clear) delete value[clear];
  remove(programId);
  if (!value.draft && !value.publication && !value.revision) return;
  const timer = setTimeout(() => remove(programId), lifetime);
  drafts.set(programId, { value, expires: Date.now() + lifetime, timer });
  if (drafts.size > 10) remove(drafts.keys().next().value!);
}

export const readStudioDraft = (context: string, programId: string) =>
  read(context, programId)?.draft ?? null;
export const readStudioPublication = (context: string, programId: string) =>
  read(context, programId)?.publication ?? null;
export const retainStudioDraft = (
  context: string,
  programId: string,
  draft: StudioDraftRecovery,
) => write(context, programId, { draft });
export const retainStudioPublication = (
  context: string,
  programId: string,
  publication: StudioPublicationCommand,
) => write(context, programId, { publication });
export const clearStudioDraft = (context: string, programId: string) =>
  write(context, programId, {}, "draft");
export const clearStudioPublication = (context: string, programId: string) =>
  write(context, programId, {}, "publication");
export const readStudioRevision = (context: string, programId: string) =>
  read(context, programId)?.revision ?? null;
export const retainStudioRevision = (
  context: string,
  programId: string,
  revision: StudioRevisionCommand,
) => write(context, programId, { revision });
export const clearStudioRevision = (context: string, programId: string) =>
  write(context, programId, {}, "revision");
