/**
 * Every workspace and what it is (GET /v1/platform/workspaces): our company,
 * customers, Personal accounts, the sandbox, and the staff workspace. The kind
 * comes from the API, never from a name; two of them used to read
 * "Authority Closers".
 */
import type { Tone } from "../ui/kit";
import { read } from "./read";

export type WorkspaceKind =
  | "company"
  | "customer"
  | "personal"
  | "sandbox"
  | "operations"
  | "other";

export type Workspace = {
  id: string;
  name: string;
  registeredName: string;
  kind: WorkspaceKind;
  status: string;
  members: number;
  calls: number;
};

const KINDS: readonly WorkspaceKind[] = [
  "company",
  "customer",
  "personal",
  "sandbox",
  "operations",
  "other",
];

/** The short badge next to a name. */
export const KIND_BADGE: Record<WorkspaceKind, string> = {
  company: "Our company",
  customer: "Customer",
  personal: "Personal",
  sandbox: "Sandbox",
  operations: "Staff",
  other: "Other",
};

/** The heading a group of workspaces sits under. */
export const KIND_GROUP: Record<WorkspaceKind, string> = {
  company: "Our company",
  customer: "Customers",
  personal: "Personal accounts",
  sandbox: "Sandbox and test",
  operations: "Staff workspace",
  other: "Other",
};

/** One line on what the workspace holds, for people new to Admin. */
export const KIND_HINT: Record<WorkspaceKind, string> = {
  company: "Our own team's organisation",
  customer: "A customer organisation",
  personal: "People using Sales Xray on their own",
  sandbox: "Fictional calls for testing, never real customers",
  operations: "Where Admin roles live; holds no calls",
  other: "Not a registered organisation",
};

export const KIND_TONE: Record<WorkspaceKind, Tone> = {
  company: "accent",
  customer: "info",
  personal: "good",
  sandbox: "warn",
  operations: "neutral",
  other: "neutral",
};

export function asKind(value: unknown): WorkspaceKind {
  return KINDS.includes(value as WorkspaceKind)
    ? (value as WorkspaceKind)
    : "other";
}

export function normalizeWorkspaces(raw: unknown): Workspace[] {
  return read.array(read.object(raw).workspaces).map((item) => {
    const row = read.object(item);
    const name = read.string(row.name, "Unnamed workspace");
    return {
      id: read.string(row.tenant_id),
      name,
      registeredName: read.string(row.registered_name, name),
      kind: asKind(row.kind),
      status: read.string(row.status, "active"),
      members: read.number(row.member_count),
      calls: read.number(row.call_count),
    };
  });
}

/** Workspaces under their group headings, in the API's order (ours first). */
export function groupWorkspaces(
  workspaces: readonly Workspace[],
): { kind: WorkspaceKind; items: Workspace[] }[] {
  return KINDS.map((kind) => ({
    kind,
    items: workspaces.filter((item) => item.kind === kind),
  })).filter((group) => group.items.length > 0);
}
