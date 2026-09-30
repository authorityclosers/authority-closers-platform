/**
 * Organisation reads and changes (contract in AUT-443). Until the server
 * serves these routes they answer 404, and the UI says the feature is not live
 * yet instead of showing anything invented.
 */

export type OrgRole = "owner" | "admin" | "member";

export type Organisation = {
  tenantId: string;
  name: string;
  role: OrgRole;
  verifiedDomains: string[];
  autoJoin: boolean;
  memberCount: number;
};

export type OrgMember = {
  personId: string;
  name: string | null;
  email: string;
  role: OrgRole;
  status: "active" | "invited";
  joinedAt: string | null;
  lastActiveAt: string | null;
  minutesUsed30d: number;
  calls30d: number;
};

export type OrgActivity = {
  members: Array<{
    personId: string;
    calls: number;
    minutes: number;
    reportsReady: number;
    lastCallAt: string | null;
  }>;
  calls: Array<{
    id: string;
    ownerPersonId: string;
    ownerName: string | null;
    label: string | null;
    createdAt: string;
    durationSeconds: number;
    state: string;
    hasReport: boolean;
  }>;
};

export class OrgApiError extends Error {
  constructor(readonly status: number) {
    super(`organisation_${status}`);
  }
}

/** True when the organisation API is not deployed on this server yet. */
export const notLive = (error: unknown) =>
  error instanceof OrgApiError &&
  (error.status === 404 || error.status === 405);

async function call(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {},
): Promise<unknown> {
  const response = await fetch(`/v1/organisation${path}`, {
    credentials: "same-origin",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) throw new OrgApiError(response.status);
  return response.status === 204 ? null : response.json();
}

const text = (value: unknown) => (typeof value === "string" ? value : null);
const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;
const role = (value: unknown): OrgRole =>
  value === "owner" || value === "admin" ? value : "member";
const list = (value: unknown) => (Array.isArray(value) ? value : []);
const obj = (value: unknown) =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export async function readOrganisation(
  signal?: AbortSignal,
): Promise<Organisation> {
  const data = obj(await call("", { signal }));
  return {
    tenantId: text(data.tenant_id) ?? "",
    name: text(data.name) ?? "",
    role: role(data.role),
    verifiedDomains: list(data.verified_domains).filter(
      (item): item is string => typeof item === "string",
    ),
    autoJoin: data.auto_join === true,
    memberCount: num(data.member_count),
  };
}

export async function readMembers(signal?: AbortSignal): Promise<OrgMember[]> {
  const data = obj(await call("/members", { signal }));
  return list(data.members).map((raw) => {
    const item = obj(raw);
    return {
      personId: text(item.person_id) ?? "",
      name: text(item.name),
      email: text(item.email) ?? "",
      role: role(item.role),
      status: item.status === "invited" ? "invited" : "active",
      joinedAt: text(item.joined_at),
      lastActiveAt: text(item.last_active_at),
      minutesUsed30d: num(item.minutes_used_30d),
      calls30d: num(item.calls_30d),
    };
  });
}

export async function readActivity(signal?: AbortSignal): Promise<OrgActivity> {
  const data = obj(await call("/activity?days=30", { signal }));
  return {
    members: list(data.members).map((raw) => {
      const item = obj(raw);
      return {
        personId: text(item.person_id) ?? "",
        calls: num(item.calls),
        minutes: num(item.minutes),
        reportsReady: num(item.reports_ready),
        lastCallAt: text(item.last_call_at),
      };
    }),
    calls: list(data.calls).map((raw) => {
      const item = obj(raw);
      return {
        id: text(item.id) ?? "",
        ownerPersonId: text(item.owner_person_id) ?? "",
        ownerName: text(item.owner_name),
        label: text(item.label),
        createdAt: text(item.created_at) ?? "",
        durationSeconds: num(item.duration_seconds),
        state: text(item.state) ?? "",
        hasReport: item.has_report === true,
      };
    }),
  };
}

export const addMember = (email: string, memberRole: OrgRole) =>
  call("/members", {
    method: "POST",
    body: JSON.stringify({ email, role: memberRole }),
  });

export const changeRole = (personId: string, memberRole: OrgRole) =>
  call(`/members/${encodeURIComponent(personId)}`, {
    method: "PATCH",
    body: JSON.stringify({ role: memberRole }),
  });

export const removeMember = (personId: string) =>
  call(`/members/${encodeURIComponent(personId)}`, { method: "DELETE" });

export const transferOwnership = (personId: string) =>
  call("/owner", {
    method: "POST",
    body: JSON.stringify({ person_id: personId }),
  });

export const saveDomains = (verifiedDomains: string[], autoJoin: boolean) =>
  call("/domains", {
    method: "PUT",
    body: JSON.stringify({
      verified_domains: verifiedDomains,
      auto_join: autoJoin,
    }),
  });
