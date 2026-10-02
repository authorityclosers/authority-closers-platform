export type SalesXrayWorkspace = Readonly<{
  tenant_id: string;
  kind: "personal" | "organisation";
  name: string;
  role: "owner" | "admin" | "member" | null;
  sales_xray_enabled: boolean;
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
      ]) ||
      !text(item.tenant_id) ||
      !text(item.name) ||
      (item.kind !== "personal" && item.kind !== "organisation") ||
      (item.role !== null &&
        item.role !== "owner" &&
        item.role !== "admin" &&
        item.role !== "member") ||
      typeof item.sales_xray_enabled !== "boolean" ||
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
  const response = await fetch("/v1/me/sales-xray-workspaces", {
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
