import { ORG_ROLES, type OrgRole } from "./organisation/organisation-api";
import { earlyFetch } from "./early-reads";

export type SalesXrayWorkspace = Readonly<{
  tenant_id: string;
  kind: "personal" | "organisation";
  name: string;
  role: OrgRole | null;
  sales_xray_enabled: boolean;
  logo_url?: string | null;
}>;

export type SalesXrayWorkspaceChoices = Readonly<{
  selected_tenant_id: string | null;
  workspaces: readonly SalesXrayWorkspace[];
}>;

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;
const exact = (value: Record<string, unknown>, keys: string[]) =>
  Object.keys(value).length === keys.length &&
  keys.every((key) => Object.hasOwn(value, key));

export function parseSalesXrayWorkspaces(
  value: unknown,
): SalesXrayWorkspaceChoices | null {
  if (!record(value) || !exact(value, ["selected_tenant_id", "workspaces"]))
    return null;
  if (value.selected_tenant_id !== null && !text(value.selected_tenant_id))
    return null;
  if (!Array.isArray(value.workspaces)) return null;
  const workspaces: SalesXrayWorkspace[] = [];
  const ids = new Set<string>();
  for (const item of value.workspaces) {
    if (
      !record(item) ||
      !exact(item, [
        "tenant_id",
        "kind",
        "name",
        "role",
        "sales_xray_enabled",
        ...(Object.hasOwn(item, "logo_url") ? ["logo_url"] : []),
      ]) ||
      !text(item.tenant_id) ||
      !text(item.name) ||
      (item.kind !== "personal" && item.kind !== "organisation") ||
      (item.role !== null && !ORG_ROLES.includes(item.role as OrgRole)) ||
      typeof item.sales_xray_enabled !== "boolean" ||
      (item.logo_url !== undefined &&
        item.logo_url !== null &&
        (typeof item.logo_url !== "string" ||
          item.kind !== "organisation" ||
          !/^\/v1\/me\/sales-xray-workspaces\/[\da-f-]{36}\/logo\/[\da-f-]{36}$/i.test(
            item.logo_url,
          ) ||
          item.logo_url.split("/")[4] !== item.tenant_id)) ||
      ids.has(item.tenant_id)
    )
      return null;
    ids.add(item.tenant_id);
    workspaces.push(item as SalesXrayWorkspace);
  }
  if (value.selected_tenant_id !== null && !ids.has(value.selected_tenant_id))
    return null;
  return { selected_tenant_id: value.selected_tenant_id, workspaces };
}

export async function readSalesXrayWorkspaces(signal: AbortSignal) {
  const response = await earlyFetch("/v1/me/sales-xray-workspaces", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new Error("sales_xray_workspace_read_rejected");
  const choices = parseSalesXrayWorkspaces(await response.json());
  if (!choices) throw new Error("sales_xray_workspace_shape_invalid");
  return choices;
}
