import { z } from "zod";

export const membershipRoleSchema = z.enum([
  "owner",
  "admin",
  "support",
  "learner",
]);
const permissionsSchema = z.array(z.string().min(1).max(64)).max(64);

export const meSchema = z
  .object({
    person_id: z.uuid(),
    email: z.string().email(),
    display_name: z.string().nullable(),
    email_verified_at: z.string().min(1),
    selected_tenant_id: z.uuid().nullable(),
    membership_role: membershipRoleSchema.nullable(),
    permissions: permissionsSchema,
  })
  .strict();

export const contextSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    tenant_id: z.uuid().nullable(),
    membership_role: membershipRoleSchema.nullable(),
    permissions: permissionsSchema,
  })
  .strict();

export const studioPermissionSchema = z.enum([
  "catalog_read",
  "catalog_write",
  "catalog_publish",
  "learner_diagnose",
  "learning_review",
]);

export const studioCapabilitySchema = z.discriminatedUnion("scope_kind", [
  z
    .object({
      permission: studioPermissionSchema,
      scope_kind: z.literal("tenant"),
      tenant_id: z.uuid(),
      program_id: z.null(),
    })
    .strict(),
  z
    .object({
      permission: studioPermissionSchema,
      scope_kind: z.literal("program"),
      tenant_id: z.uuid(),
      program_id: z.uuid(),
    })
    .strict(),
]);

export const adminAccessSchema = z
  .object({
    person_id: z.uuid(),
    session_id: z.uuid(),
    tenant_id: z.uuid(),
    studio_capabilities: z.array(studioCapabilitySchema),
  })
  .strict()
  .superRefine((access, context) => {
    const seen = new Set<string>();
    for (const capability of access.studio_capabilities) {
      const key = `${capability.permission}:${capability.scope_kind}:${capability.program_id}`;
      if (capability.tenant_id !== access.tenant_id || seen.has(key)) {
        context.addIssue({
          code: "custom",
          message:
            "Studio scopes must be unique and match the selected academy.",
        });
      }
      seen.add(key);
    }
  });

export type StudioPermission = z.infer<typeof studioPermissionSchema>;
export type StudioCapability = z.infer<typeof studioCapabilitySchema>;
export type AdminIdentity = Readonly<{
  me: z.infer<typeof meSchema>;
  context: z.infer<typeof contextSchema> & {
    tenant_id: string;
    membership_role: z.infer<typeof membershipRoleSchema>;
  };
  studioCapabilities: readonly StudioCapability[];
}>;

function permissionKey(permissions: readonly string[]) {
  return [...new Set(permissions)].sort().join("\n");
}

/** All inputs come from canonical API reads; this object is never command authority. */
export function verifyAdminIdentity(
  rawMe: unknown,
  rawContext: unknown,
  rawAccess: unknown,
): AdminIdentity | null {
  const me = meSchema.safeParse(rawMe);
  const context = contextSchema.safeParse(rawContext);
  const access = adminAccessSchema.safeParse(rawAccess);
  if (!me.success || !context.success || !access.success) return null;
  const person = me.data;
  const selected = context.data;
  const scopes = access.data;
  if (
    !selected.tenant_id ||
    !selected.membership_role ||
    person.person_id !== selected.person_id ||
    person.selected_tenant_id !== selected.tenant_id ||
    person.membership_role !== selected.membership_role ||
    permissionKey(person.permissions) !== permissionKey(selected.permissions) ||
    scopes.person_id !== selected.person_id ||
    scopes.session_id !== selected.session_id ||
    scopes.tenant_id !== selected.tenant_id
  )
    return null;
  const legacyAdmin =
    selected.membership_role !== "learner" &&
    selected.permissions.includes("admin_surface");
  if (!legacyAdmin && scopes.studio_capabilities.length === 0) return null;
  return {
    me: person,
    context: {
      ...selected,
      tenant_id: selected.tenant_id,
      membership_role: selected.membership_role,
    },
    studioCapabilities: scopes.studio_capabilities,
  };
}
