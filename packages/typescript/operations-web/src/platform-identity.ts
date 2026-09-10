import { z } from "zod";
import { contextSchema, meSchema } from "./admin-identity";

export const platformPermissionSchema = z.enum([
  "platform_access_manage",
  "platform_tenants_read",
  "platform_catalog_read",
  "platform_catalog_write",
  "platform_catalog_publish",
]);
export const platformAccessSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    selected_tenant_id: z.uuid().nullable(),
    platform_permissions: z.array(platformPermissionSchema).max(5),
  })
  .strict()
  .refine(
    (value) =>
      new Set(value.platform_permissions).size ===
      value.platform_permissions.length,
  );
export type PlatformIdentity = Readonly<{
  personId: string;
  sessionId: string;
  selectedTenantId: string | null;
  email: string;
  displayName: string | null;
  permissions: readonly z.infer<typeof platformPermissionSchema>[];
}>;

/** Bound the stream while reading, not after an unlimited body allocation. */
export async function readPlatformJson(
  response: Response,
  maximumBytes = 65536,
): Promise<unknown> {
  if (!response.body) throw new Error("Response body unavailable");
  const reader = response.body.getReader();
  let count = 0;
  const chunks: Uint8Array[] = [];
  try {
    for (;;) {
      const result = await reader.read();
      if (result.done) break;
      count += result.value.byteLength;
      if (count > maximumBytes) {
        await reader.cancel();
        throw new Error("Response limit exceeded");
      }
      chunks.push(result.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(count);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}

/** Navigation admission only: API actions always re-read their exact grant. */
export function verifyPlatformIdentity(
  rawMe: unknown,
  rawContext: unknown,
  rawAccess: unknown,
): PlatformIdentity | null {
  const me = meSchema.safeParse(rawMe);
  const context = contextSchema.safeParse(rawContext);
  const access = platformAccessSchema.safeParse(rawAccess);
  if (!me.success || !context.success || !access.success) return null;
  const person = me.data,
    selected = context.data,
    projection = access.data;
  const key = (values: readonly string[]) =>
    [...new Set(values)].sort().join("\n");
  if (
    person.person_id !== selected.person_id ||
    person.person_id !== projection.person_id ||
    selected.session_id !== projection.session_id ||
    person.selected_tenant_id !== selected.tenant_id ||
    selected.tenant_id !== projection.selected_tenant_id ||
    person.membership_role !== selected.membership_role ||
    key(person.permissions) !== key(selected.permissions) ||
    projection.platform_permissions.length === 0
  )
    return null;
  return {
    personId: person.person_id,
    sessionId: selected.session_id,
    selectedTenantId: selected.tenant_id,
    email: person.email,
    displayName: person.display_name,
    permissions: projection.platform_permissions,
  };
}

export async function loadPlatformIdentity({
  fetcher = fetch,
  signal,
}: {
  fetcher?: typeof fetch;
  signal?: AbortSignal;
} = {}): Promise<PlatformIdentity | null> {
  try {
    const values: unknown[] = [];
    for (const path of ["/v1/me", "/v1/context", "/v1/me/platform-access"]) {
      const response = await fetcher(path, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: signal
          ? AbortSignal.any([signal, AbortSignal.timeout(5000)])
          : AbortSignal.timeout(5000),
        headers: { accept: "application/json" },
      });
      if (!response.ok) return null;
      values.push(await readPlatformJson(response));
    }
    if (signal?.aborted) return null;
    return verifyPlatformIdentity(values[0], values[1], values[2]);
  } catch {
    return null;
  }
}
