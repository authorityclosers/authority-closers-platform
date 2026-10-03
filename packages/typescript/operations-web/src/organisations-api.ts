import { z } from "zod";
import { AdminApiProblem } from "./admin-api";

export const platformOrganisationsSchema = z
  .object({
    organisations: z.array(
      z
        .object({
          tenant_id: z.uuid(),
          name: z.string().min(1),
          member_count: z.number().int().nonnegative(),
          created_at: z.string().min(1),
        })
        .strict(),
    ),
  })
  .strict();

export type PlatformOrganisations = z.infer<typeof platformOrganisationsSchema>;

export const organisationMemberSchema = z
  .object({
    person_id: z.uuid().nullable(),
    invite_id: z.uuid().nullable(),
    name: z.string().nullable(),
    email: z.string().nullable(),
    role: z.enum(["owner", "admin", "member"]),
    status: z.enum(["active", "invited"]),
    joined_at: z.iso.datetime({ offset: true }).nullable(),
    last_active_at: z.iso.datetime({ offset: true }).nullable(),
    minutes_used_30d: z.number().nonnegative(),
    calls_30d: z.number().int().nonnegative(),
  })
  .strict();
export const organisationMembersSchema = z
  .object({
    members: z.array(organisationMemberSchema),
  })
  .strict();
export const organisationOwnerTransferSchema = z
  .object({
    owner: organisationMemberSchema,
    former_owner: organisationMemberSchema,
  })
  .strict();
export type OrganisationMember = z.infer<typeof organisationMemberSchema>;
export type OrganisationCommand = { reason: string } & (
  | { kind: "add"; email: string; role: "admin" | "member" }
  | { kind: "role"; person_id: string; role: "admin" | "member" }
  | { kind: "remove" | "transfer"; person_id: string }
  | { kind: "revoke"; invite_id: string }
);
type RequestOptions = { fetcher?: typeof fetch; signal?: AbortSignal };

async function memberRequest(
  path: string,
  init: RequestInit,
  fetcher: typeof fetch,
) {
  const response = await fetcher(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
  const payload: unknown =
    response.status === 204
      ? undefined
      : await response.json().catch(() => undefined);
  if (!response.ok) {
    const problem =
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>)
        : {};
    throw new AdminApiProblem({
      status: response.status,
      code:
        typeof problem.code === "string"
          ? problem.code
          : `http_${response.status}`,
      title:
        typeof problem.title === "string"
          ? problem.title
          : "Admin request rejected",
      detail:
        typeof problem.detail === "string"
          ? problem.detail
          : "The admin request was rejected.",
      requestId:
        typeof problem.request_id === "string" ? problem.request_id : null,
    });
  }
  return payload;
}

function organisationPath(tenantId: string) {
  return `/v1/platform/organisations/${z.uuid().parse(tenantId)}`;
}

export async function loadOrganisationMembers(
  tenantId: string,
  { fetcher = fetch, signal }: RequestOptions = {},
) {
  return organisationMembersSchema.parse(
    await memberRequest(
      organisationPath(tenantId) + "/members",
      { method: "GET", headers: { accept: "application/json" }, signal },
      fetcher,
    ),
  );
}

export async function changePlatformOrganisation(
  tenantId: string,
  command: OrganisationCommand,
  { fetcher = fetch, signal }: RequestOptions = {},
) {
  const reason = z.string().trim().min(3).max(200).parse(command.reason);
  let path = organisationPath(tenantId),
    method: string;
  let body: object = { reason };
  switch (command.kind) {
    case "add":
      path += "/members";
      method = "POST";
      body = {
        reason,
        email: z.email().parse(command.email.trim()),
        role: z.enum(["admin", "member"]).parse(command.role),
      };
      break;
    case "role":
      path += `/members/${z.uuid().parse(command.person_id)}`;
      method = "PATCH";
      body = { reason, role: z.enum(["admin", "member"]).parse(command.role) };
      break;
    case "remove":
      path += `/members/${z.uuid().parse(command.person_id)}`;
      method = "DELETE";
      break;
    case "transfer":
      path += "/owner";
      method = "POST";
      body = { reason, person_id: z.uuid().parse(command.person_id) };
      break;
    case "revoke":
      path += `/invites/${z.uuid().parse(command.invite_id)}`;
      method = "DELETE";
      break;
  }
  const result = await memberRequest(
    path,
    {
      method,
      signal,
      body: JSON.stringify(body),
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
    },
    fetcher,
  );
  if (command.kind === "remove" || command.kind === "revoke") {
    return z.undefined().parse(result);
  }
  return command.kind === "transfer"
    ? organisationOwnerTransferSchema.parse(result)
    : organisationMemberSchema.parse(result);
}

export async function loadPlatformOrganisations({
  fetcher = fetch,
  signal,
}: {
  fetcher?: typeof fetch;
  signal?: AbortSignal;
} = {}): Promise<PlatformOrganisations> {
  const response = await fetcher("/v1/platform/organisations", {
    method: "GET",
    headers: { accept: "application/json" },
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const problem =
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>)
        : {};
    const text = (key: string, fallback: string) =>
      typeof problem[key] === "string" && problem[key].trim()
        ? problem[key]
        : fallback;
    throw new AdminApiProblem({
      status: response.status,
      code: text("code", `http_${response.status}`),
      title: text("title", "Admin request rejected"),
      detail: text("detail", "The admin request was rejected."),
      requestId:
        typeof problem.request_id === "string" ? problem.request_id : null,
    });
  }
  return platformOrganisationsSchema.parse(payload);
}
