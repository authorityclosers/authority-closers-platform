import { z } from "zod";
import { loadAdminSession, type AdminSession } from "./admin-api";
import { contextSchema } from "./admin-identity";

export type OperationsSurface = "admin" | "coach";
const workspaceSchema = z
  .object({ tenant_id: z.uuid(), name: z.string().min(1).max(200) })
  .strict();
export const operationsWorkspacesSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    selected_tenant_id: z.uuid().nullable(),
    workspaces: z.array(workspaceSchema),
  })
  .strict()
  .superRefine((value, context) => {
    const ids = value.workspaces.map((item) => item.tenant_id);
    if (new Set(ids).size !== ids.length)
      context.addIssue({
        code: "custom",
        message: "Workspace identities must be unique.",
      });
  });
export type OperationsWorkspaces = z.infer<typeof operationsWorkspacesSchema>;
export class OperationsWorkspaceError extends Error {
  constructor(
    message = "Your workspace could not be verified. Check your connection and try again.",
  ) {
    super(message);
    this.name = "OperationsWorkspaceError";
  }
}
type Options = { fetcher?: typeof fetch; signal?: AbortSignal };

export async function loadOperationsWorkspaces({
  fetcher = fetch,
  signal,
}: Options = {}): Promise<OperationsWorkspaces | null> {
  let response: Response;
  try {
    response = await fetcher("/v1/me/workspaces", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: { accept: "application/json" },
    });
  } catch {
    throw new OperationsWorkspaceError();
  }
  if (response.status === 401) return null;
  if (!response.ok) throw new OperationsWorkspaceError();
  try {
    return operationsWorkspacesSchema.parse(await response.json());
  } catch {
    throw new OperationsWorkspaceError();
  }
}

export function operationsSessionMatches(
  session: AdminSession,
  choices: OperationsWorkspaces,
  tenantId: string,
  surface: OperationsSurface,
): boolean {
  return (
    session.personId === choices.person_id &&
    session.sessionId === choices.session_id &&
    session.tenantId === tenantId &&
    choices.workspaces.some((item) => item.tenant_id === tenantId) &&
    (surface === "admin"
      ? session.permissions.includes("admin_surface")
      : session.studioCapabilities.some((item) => item.tenant_id === tenantId))
  );
}

/** Selection changes only canonical session context, never memberships or grants. */
export async function selectOperationsWorkspace(
  choices: OperationsWorkspaces,
  tenantId: string,
  surface: OperationsSurface,
  { fetcher = fetch, signal }: Options = {},
): Promise<AdminSession> {
  if (!choices.workspaces.some((item) => item.tenant_id === tenantId))
    throw new OperationsWorkspaceError(
      "Choose a workspace listed for your account.",
    );
  try {
    const response = await fetcher("/v1/context", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ tenant_id: tenantId }),
    });
    if (!response.ok) throw new OperationsWorkspaceError();
    const selected = contextSchema.parse(await response.json());
    if (
      selected.person_id !== choices.person_id ||
      selected.session_id !== choices.session_id ||
      selected.tenant_id !== tenantId
    )
      throw new OperationsWorkspaceError();
    const session = await loadAdminSession((input, init) =>
      fetcher(input, { ...init, signal }),
    );
    if (!operationsSessionMatches(session, choices, tenantId, surface))
      throw new OperationsWorkspaceError(
        surface === "coach"
          ? "This workspace has no Academy Studio assignment for your account. Choose another workspace or contact its administrator."
          : "This workspace has no Platform Admin access for your account. Choose another workspace or contact its administrator.",
      );
    return session;
  } catch (error) {
    if (error instanceof OperationsWorkspaceError) throw error;
    throw new OperationsWorkspaceError();
  }
}
