/** Organisation reads and changes against the selected session workspace. */
import { acquisition, AcquisitionError } from "../acquisition-client";
import type { ActivityDay } from "../dashboard/dashboard-data";

export type OrgRole = "owner" | "admin" | "member";

export const organisationDetailFields = [
  "name",
  "legal_name",
  "gstin",
  "address",
  "industry",
  "team_size",
  "website",
  "city",
] as const;
export type OrganisationDetails = Record<
  (typeof organisationDetailFields)[number],
  string
>;
export type OrganisationSettings = OrganisationDetails & {
  tenant_id: string;
  logo_url: string | null;
};

export type Organisation = {
  tenantId: string;
  name: string;
  role: OrgRole;
  verifiedDomains: string[];
  autoJoin: boolean;
  memberCount: number;
};

export type OrgMember = {
  name: string | null;
  email: string | null;
  role: OrgRole;
  joinedAt: string | null;
  lastActiveAt: string | null;
  minutesUsed30d: number;
  calls30d: number;
} & (
  | { status: "active"; personId: string; inviteId: null }
  | { status: "invited"; personId: null; inviteId: string }
);

/** Counts over the same permitted calls that `calls` lists. */
export type ActivityCounts = {
  calls: number;
  recordedMinutes: number;
  reportsReady: number;
};

export type OrgActivity = {
  members: Array<{
    personId: string;
    calls: number;
    minutes: number;
    reportsReady: number;
    lastCallAt: string | null;
  }>;
  /** UTC days with at least one permitted call; empty on older servers. */
  perDay: Array<ActivityCounts & { date: string }>;
  /** People with at least one permitted call; empty on older servers. */
  perRep: Array<ActivityCounts & { personId: string; name: string }>;
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
  constructor(
    readonly status: number,
    detail?: string,
  ) {
    super(detail || "That change was not saved. Try again.");
  }
}

/** True when the organisation API is not deployed on this server yet. */
export const notLive = (error: unknown) =>
  error instanceof OrgApiError &&
  (error.status === 404 || error.status === 405);

export const noOrganisationSelected = (error: unknown) =>
  error instanceof OrgApiError &&
  error.status === 404 &&
  error.message === "No organisation selected.";

async function call(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {},
  requestKey?: string,
): Promise<unknown> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET")
    headers.set("Idempotency-Key", requestKey ?? crypto.randomUUID());
  const response = await fetch(`/v1/organisation${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers,
  });
  if (!response.ok) {
    const problem = obj(await response.json().catch(() => null));
    throw new OrgApiError(response.status, text(problem.detail) ?? undefined);
  }
  return response.status === 204 ? null : response.json();
}

const text = (value: unknown) => (typeof value === "string" ? value : null);
const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;
const list = (value: unknown) => (Array.isArray(value) ? value : []);
const obj = (value: unknown) =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

const exact = (value: unknown, keys: string[]) => {
  const data = obj(value);
  return (
    !Array.isArray(value) &&
    Object.keys(data).length === keys.length &&
    keys.every((key) => Object.hasOwn(data, key))
  );
};
const id = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(value);
const nullableText = (value: unknown) =>
  value === null || typeof value === "string";
const date = (value: unknown) =>
  value === null ||
  (typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T/.test(value) &&
    Number.isFinite(Date.parse(value)));
const count = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;
const validRole = (value: unknown): value is OrgRole =>
  value === "owner" || value === "admin" || value === "member";

export function parseOrganisation(value: unknown): Organisation {
  const data = obj(value);
  if (
    !exact(value, [
      "tenant_id",
      "name",
      "role",
      "verified_domains",
      "auto_join",
      "member_count",
    ]) ||
    !id(data.tenant_id) ||
    typeof data.name !== "string" ||
    !data.name.trim() ||
    !validRole(data.role) ||
    !Array.isArray(data.verified_domains) ||
    !data.verified_domains.every((item) => typeof item === "string") ||
    typeof data.auto_join !== "boolean" ||
    !count(data.member_count) ||
    !Number.isInteger(data.member_count)
  )
    throw new Error("Invalid organisation response.");
  return {
    tenantId: data.tenant_id,
    name: data.name,
    role: data.role,
    verifiedDomains: data.verified_domains,
    autoJoin: data.auto_join,
    memberCount: data.member_count,
  };
}

export function parseMembers(value: unknown): OrgMember[] {
  const data = obj(value);
  if (!exact(value, ["members"]) || !Array.isArray(data.members))
    throw new Error("Invalid organisation members response.");
  const identities = new Set<string>();
  return data.members.map((raw) => {
    const item = obj(raw);
    const identity =
      item.status === "active" && id(item.person_id) && item.invite_id === null
        ? {
            status: "active" as const,
            personId: item.person_id,
            inviteId: null,
          }
        : item.status === "invited" &&
            item.person_id === null &&
            id(item.invite_id) &&
            item.role !== "owner"
          ? {
              status: "invited" as const,
              personId: null,
              inviteId: item.invite_id,
            }
          : null;
    if (
      !exact(raw, [
        "person_id",
        "invite_id",
        "name",
        "email",
        "role",
        "status",
        "joined_at",
        "last_active_at",
        "minutes_used_30d",
        "calls_30d",
      ]) ||
      !identity ||
      !nullableText(item.name) ||
      !nullableText(item.email) ||
      !validRole(item.role) ||
      !date(item.joined_at) ||
      !date(item.last_active_at) ||
      !count(item.minutes_used_30d) ||
      !count(item.calls_30d) ||
      !Number.isInteger(item.calls_30d)
    )
      throw new Error("Invalid organisation member response.");
    const key = `${identity.status}:${identity.personId ?? identity.inviteId}`;
    if (identities.has(key))
      throw new Error("Duplicate organisation member response.");
    identities.add(key);
    return {
      ...identity,
      name: item.name as string | null,
      email: item.email as string | null,
      role: item.role,
      joinedAt: item.joined_at as string | null,
      lastActiveAt: item.last_active_at as string | null,
      minutesUsed30d: item.minutes_used_30d,
      calls30d: item.calls_30d,
    };
  });
}

export async function readOrganisation(
  signal?: AbortSignal,
): Promise<Organisation> {
  return parseOrganisation(await call("", { signal }));
}

export function parseOrganisationSettings(
  value: unknown,
  tenantId: string,
): OrganisationSettings {
  const data = obj(value);
  if (
    !exact(value, [...organisationDetailFields, "tenant_id", "logo_url"]) ||
    !id(data.tenant_id) ||
    data.tenant_id !== tenantId ||
    !organisationDetailFields.every(
      (field) => typeof data[field] === "string",
    ) ||
    !nullableText(data.logo_url)
  )
    throw new Error("Invalid organisation settings response.");
  return data as OrganisationSettings;
}

export async function readOrganisationSettings(
  tenantId: string,
  signal?: AbortSignal,
) {
  return parseOrganisationSettings(
    await call("/settings", { signal }),
    tenantId,
  );
}

export async function saveOrganisationSettings(
  tenantId: string,
  details: OrganisationDetails,
  requestKey: string,
  signal?: AbortSignal,
) {
  if (
    !/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/.test(
      requestKey,
    )
  )
    throw new Error("A canonical UUIDv4 request key is required.");
  const body = Object.fromEntries(
    organisationDetailFields.map((field) => [field, details[field]]),
  );
  return parseOrganisationSettings(
    await call(
      "/settings",
      {
        method: "PUT",
        body: JSON.stringify(body),
        signal,
      },
      requestKey,
    ),
    tenantId,
  );
}

export async function readMembers(signal?: AbortSignal): Promise<OrgMember[]> {
  return parseMembers(await call("/members", { signal }));
}

const counts = (item: Record<string, unknown>): ActivityCounts => ({
  calls: num(item.calls),
  recordedMinutes: num(item.recorded_minutes),
  reportsReady: num(item.reports_ready),
});

export async function readActivity(signal?: AbortSignal): Promise<OrgActivity> {
  const data = obj(await call("/activity?days=30", { signal }));
  return {
    perDay: list(data.per_day).map((raw) => {
      const item = obj(raw);
      return { date: text(item.date) ?? "", ...counts(item) };
    }),
    perRep: list(data.per_rep).map((raw) => {
      const item = obj(raw);
      return {
        personId: text(item.person_id) ?? "",
        name: text(item.name) ?? "",
        ...counts(item),
      };
    }),
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

/**
 * Finished analyses from durable receipts (AUT-1392), for live owners and
 * admins. These count former members and claimed uploads, so they can differ
 * from the saved calls that `readActivity` lists.
 */
export type ReceiptActivity = {
  /** Exactly 30 India calendar days, oldest first; the last is today. */
  days: ActivityDay[];
  analysedLast30Days: number;
  analysedPrevious30Days: number;
  /** In the API's order. */
  people: Array<{
    personId: string;
    name: string;
    analysed: number;
    analysedSeconds: number;
    previous: number;
  }>;
};

export class ReceiptActivityError extends Error {}

const DAY_KEYS = ["date", "analysed", "analysed_seconds"];
const PERSON_KEYS = [
  "person_id",
  "name",
  "analysed_last_30_days",
  "analysed_seconds_last_30_days",
  "analysed_previous_30_days",
];
const whole = (value: unknown) => {
  if (!Number.isSafeInteger(value) || (value as number) < 0)
    throw new ReceiptActivityError();
  return value as number;
};
const sum = <T>(items: T[], pick: (item: T) => number) =>
  items.reduce((total, item) => total + pick(item), 0);

/** Exact fields only, and every total must agree across days and people. */
export function parseReceiptActivity(value: unknown): ReceiptActivity {
  const data = obj(value);
  if (
    !exact(value, [
      "timezone",
      "days",
      "analysed_last_30_days",
      "analysed_previous_30_days",
      "people",
    ]) ||
    data.timezone !== "Asia/Kolkata" ||
    !Array.isArray(data.days) ||
    data.days.length !== 30 ||
    !Array.isArray(data.people)
  )
    throw new ReceiptActivityError();
  const days = data.days.map((raw: unknown): ActivityDay => {
    const day = obj(raw);
    if (
      !exact(raw, DAY_KEYS) ||
      typeof day.date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(day.date)
    )
      throw new ReceiptActivityError();
    return {
      date: day.date,
      analysed: whole(day.analysed),
      analysedSeconds: whole(day.analysed_seconds),
    };
  });
  days.forEach((day, index) => {
    if (index > 0 && day.date <= days[index - 1].date)
      throw new ReceiptActivityError();
  });
  const seen = new Set<string>();
  const people = data.people.map((raw: unknown) => {
    const person = obj(raw);
    if (
      !exact(raw, PERSON_KEYS) ||
      !id(person.person_id) ||
      seen.has(person.person_id) ||
      typeof person.name !== "string"
    )
      throw new ReceiptActivityError();
    seen.add(person.person_id);
    return {
      personId: person.person_id,
      name: person.name,
      analysed: whole(person.analysed_last_30_days),
      analysedSeconds: whole(person.analysed_seconds_last_30_days),
      previous: whole(person.analysed_previous_30_days),
    };
  });
  const analysedLast30Days = whole(data.analysed_last_30_days);
  const analysedPrevious30Days = whole(data.analysed_previous_30_days);
  if (
    sum(days, (day) => day.analysed) !== analysedLast30Days ||
    sum(people, (person) => person.analysed) !== analysedLast30Days ||
    sum(days, (day) => day.analysedSeconds) !==
      sum(people, (person) => person.analysedSeconds) ||
    sum(people, (person) => person.previous) !== analysedPrevious30Days
  )
    throw new ReceiptActivityError();
  return { days, analysedLast30Days, analysedPrevious30Days, people };
}

/** Null when this server does not serve the read yet (404). */
export async function readReceiptActivity(
  signal?: AbortSignal,
): Promise<ReceiptActivity | null> {
  try {
    return parseReceiptActivity(
      await acquisition("/organisation/activity", { signal }),
    );
  } catch (error) {
    if (error instanceof AcquisitionError && error.status === 404) return null;
    throw error;
  }
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

export const revokeInvite = (inviteId: string) =>
  call(`/invites/${encodeURIComponent(inviteId)}`, { method: "DELETE" });

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
