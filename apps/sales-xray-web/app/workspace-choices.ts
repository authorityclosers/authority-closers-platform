import type { SalesXrayWorkspace } from "./sales-xray-workspaces";
type Workspace = Readonly<{
  tenant_id: string;
  name: string;
}>;

type IdentityWorkspaceChoices = Readonly<{
  person_id: string;
  session_id: string;
  selected_tenant_id: string | null;
  workspaces: readonly Workspace[];
}>;

export type WorkspaceChoices = IdentityWorkspaceChoices &
  Readonly<{
    salesXrayWorkspaces?: readonly SalesXrayWorkspace[];
  }>;

export type ViewState =
  | { kind: "loading" }
  | { kind: "unauthenticated" }
  | { kind: "ready"; choices: WorkspaceChoices }
  | { kind: "empty"; choices: WorkspaceChoices }
  | { kind: "unavailable"; message: string }
  | {
      kind: "chooser" | "selecting";
      choices: WorkspaceChoices;
      selectedTenantId?: string;
      error?: string;
    };

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

/** Keep the chooser boundary strict: every identity value comes from the API. */
export function parseWorkspaceChoices(
  value: unknown,
): IdentityWorkspaceChoices | null {
  if (!isRecord(value)) return null;
  const keys = ["person_id", "session_id", "selected_tenant_id", "workspaces"];
  if (Object.keys(value).some((key) => !keys.includes(key))) return null;
  if (!nonEmptyString(value.person_id) || !nonEmptyString(value.session_id))
    return null;
  if (
    value.selected_tenant_id !== null &&
    !nonEmptyString(value.selected_tenant_id)
  )
    return null;
  if (!Array.isArray(value.workspaces)) return null;
  const workspaces: Workspace[] = [];
  const ids = new Set<string>();
  for (const item of value.workspaces) {
    if (!isRecord(item)) return null;
    const itemKeys = ["tenant_id", "name"];
    if (Object.keys(item).some((key) => !itemKeys.includes(key))) return null;
    if (!nonEmptyString(item.tenant_id) || !nonEmptyString(item.name))
      return null;
    if (ids.has(item.tenant_id)) return null;
    ids.add(item.tenant_id);
    workspaces.push({ tenant_id: item.tenant_id, name: item.name });
  }
  if (value.selected_tenant_id !== null && !ids.has(value.selected_tenant_id))
    return null;
  return {
    person_id: value.person_id,
    session_id: value.session_id,
    selected_tenant_id: value.selected_tenant_id,
    workspaces,
  };
}
