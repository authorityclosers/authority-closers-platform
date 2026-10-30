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

/** What a workspace is, as Admin's directory says it (never read from a name). */
export const workspaceKindSchema = z.enum([
  "company",
  "customer",
  "personal",
  "sandbox",
  "operations",
  "other",
]);
export type WorkspaceKind = z.infer<typeof workspaceKindSchema>;
export const adminWorkspacesSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    selected_tenant_id: z.uuid().nullable(),
    workspaces: z
      .array(
        z
          .object({
            tenant_id: z.uuid(),
            name: z.string().min(1).max(200),
            kind: workspaceKindSchema,
          })
          .strict(),
      )
      .max(500),
  })
  .strict();
export type AdminWorkspaces = z.infer<typeof adminWorkspacesSchema>;

/** The words Admin's person menu badges each kind with. */
const KIND_WORDS: Record<WorkspaceKind, string> = {
  company: "Our company",
  customer: "Customer",
  personal: "Personal",
  sandbox: "Sandbox",
  operations: "Staff",
  other: "Other",
};

export class OperationsWorkspaceError extends Error {
  constructor(
    message = "Your workspace could not be verified. Check your connection and try again.",
  ) {
    super(message);
    this.name = "OperationsWorkspaceError";
  }
}
/** The workspace was selected, and it opens no Admin (or Studio) for this person. */
export class WorkspaceAccessDenied extends OperationsWorkspaceError {
  constructor(message: string) {
    super(message);
    this.name = "WorkspaceAccessDenied";
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

/**
 * The person's own workspaces as Admin names them ("AC Operations" for the
 * staff workspace) and what each is. Presentation and routing only: null when
 * unavailable, and the API still checks every selection, page and command.
 */
export async function loadAdminWorkspaces({
  fetcher = fetch,
  signal,
}: Options = {}): Promise<AdminWorkspaces | null> {
  try {
    const response = await fetcher("/v1/me/admin-workspaces", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) return null;
    const parsed = adminWorkspacesSchema.safeParse(await response.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/**
 * What each choice reads, so no two ever read the same: Admin's name when it
 * is known for this session, then what the workspace is when names repeat,
 * then the start of its id when even that repeats.
 */
export function workspaceLabels(
  choices: OperationsWorkspaces,
  known: AdminWorkspaces | null,
): Map<string, string> {
  const named =
    known &&
    known.person_id === choices.person_id &&
    known.session_id === choices.session_id
      ? new Map(known.workspaces.map((item) => [item.tenant_id, item]))
      : new Map<string, AdminWorkspaces["workspaces"][number]>();
  const labels = new Map(
    choices.workspaces.map((item) => [
      item.tenant_id,
      named.get(item.tenant_id)?.name ?? item.name,
    ]),
  );
  const steps: ((id: string, label: string) => string)[] = [
    (id, label) => {
      const kind = named.get(id)?.kind;
      return kind ? `${label} · ${KIND_WORDS[kind]}` : label;
    },
    (id, label) => `${label} · ${id.slice(0, 8)}`,
    (id, label) => `${label} · ${id}`,
  ];
  for (const step of steps) {
    const counts = new Map<string, number>();
    for (const label of labels.values()) {
      const key = label.trim().toLowerCase();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    let repeated = false;
    for (const [id, label] of labels) {
      if ((counts.get(label.trim().toLowerCase()) ?? 0) < 2) continue;
      labels.set(id, step(id, label));
      repeated = true;
    }
    if (!repeated) break;
  }
  return labels;
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
    const denied = new WorkspaceAccessDenied(
      surface === "coach"
        ? "This workspace has no Academy Studio assignment for your account. Choose another workspace or contact its administrator."
        : "This workspace has no Platform Admin access for your account. Choose another workspace or contact its administrator.",
    );
    // The server's own answer already says when the workspace opens no Admin;
    // read nothing more and say so, rather than "could not be verified".
    if (surface === "admin" && !selected.permissions.includes("admin_surface"))
      throw denied;
    const session = await loadAdminSession((input, init) =>
      fetcher(input, { ...init, signal }),
    );
    if (!operationsSessionMatches(session, choices, tenantId, surface))
      throw denied;
    return session;
  } catch (error) {
    if (error instanceof OperationsWorkspaceError) throw error;
    throw new OperationsWorkspaceError();
  }
}
