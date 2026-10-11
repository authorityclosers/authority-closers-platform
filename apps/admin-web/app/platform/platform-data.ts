import { read } from "../lib/server-api";

export type Academy = {
  id: string;
  name: string;
  status: string;
  kind: "platform" | "academy";
};
export type AcademyPage = { academies: Academy[]; nextAfterId: string | null };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isUuid = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);

/** GET /v1/platform/tenants, with defaults for anything missing. */
export function normalizeAcademies(raw: unknown): AcademyPage {
  const body = read.object(raw);
  return {
    academies: read.array(body.tenants).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.tenant_id),
        name: read.string(row.name, "Unnamed academy"),
        status: read.string(row.status, "unknown"),
        kind: row.kind === "platform" ? "platform" : "academy",
      };
    }),
    nextAfterId: isUuid(body.next_after_id) ? body.next_after_id : null,
  };
}

export const PLATFORM_PERMISSION_NAMES: Readonly<Record<string, string>> = {
  platform_access_manage: "Manage platform access and grant minutes",
  platform_tenants_read: "View academies and organisations",
  platform_catalog_read: "View the platform catalogue",
  platform_catalog_write: "Edit the platform catalogue",
  platform_catalog_publish: "Publish the platform catalogue",
  platform_organisations_manage: "Change organisation members and owners",
  platform_release_manage: "Manage releases",
  platform_billing_manage: "See billing and issue refunds",
  platform_content_safety_manage: "Withhold or release sensitive passages",
};
