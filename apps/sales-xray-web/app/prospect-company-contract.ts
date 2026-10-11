import {
  parseProfileFields,
  type ProfileField,
} from "./prospect-profile-contract";
import { UUID_RE } from "./prospects-client";

export const COMPANY_FIELDS = {
  name: "Company name",
  industry: "Industry",
  city: "City",
  size: "Business size",
} as const;
export type CompanyFieldKey = keyof typeof COMPANY_FIELDS;
export type CompanyRecord = {
  company_id: string;
  name: string;
  revision: number;
  origin: "person" | "detected";
  confirmed_at: string | null;
  can_edit: boolean;
  can_confirm: boolean;
  fields: Record<CompanyFieldKey, ProfileField>;
  people: { prospect_id: string; name: string }[];
};
export type CompanyReadBinding = {
  personId: string;
  tenantId: string;
  sessionId: string;
};
export type CompanyListPage = {
  companies: CompanyRecord[];
  total: number;
  next_offset: number | null;
};

function invalid(): never {
  throw new Error("Companies are unavailable. Try again.");
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 160): string {
  if (typeof value !== "string" || !value.trim() || value.length > max)
    invalid();
  return value;
}
function uuid(value: unknown): string {
  const id = text(value, 36);
  if (!UUID_RE.test(id)) invalid();
  return id;
}

/** Literal company fields only. This codec does not extract or match identity. */
export function parseCompany(value: unknown): CompanyRecord {
  try {
    const row = record(value);
    const fields = record(row.fields ?? {});
    if (
      !Number.isSafeInteger(row.revision) ||
      (row.revision as number) < 1 ||
      !["person", "detected"].includes(text(row.origin)) ||
      Object.keys(fields).some((key) => !Object.hasOwn(COMPANY_FIELDS, key)) ||
      (row.confirmed_at != null &&
        (typeof row.confirmed_at !== "string" ||
          !Number.isFinite(Date.parse(row.confirmed_at))))
    )
      invalid();
    const parsed = {} as CompanyRecord["fields"];
    for (const key of Object.keys(COMPANY_FIELDS) as CompanyFieldKey[]) {
      if (fields[key] === undefined) {
        parsed[key] = { state: "unknown", reason: "not_mentioned" };
        continue;
      }
      // Reuse the text/evidence/history codec, not prospect business semantics.
      // Company size is a literal phrase; it is never renamed person headcount.
      const codec = key === "name" ? "name" : "business";
      parsed[key] = parseProfileFields({ [codec]: fields[key] })[codec]!;
      const fact = parsed[key];
      if (fact.state === "known" && !Number.isFinite(Date.parse(fact.set_at)))
        invalid();
    }
    const name = text(row.name);
    if (
      parsed.name.state === "known" &&
      (parsed.name.value.kind !== "text" || parsed.name.value.text !== name)
    )
      invalid();
    const rawPeople = row.people ?? [];
    if (!Array.isArray(rawPeople) || rawPeople.length > 100) invalid();
    const people = rawPeople.map((raw) => {
      const person = record(raw);
      return { prospect_id: uuid(person.prospect_id), name: text(person.name) };
    });
    if (
      new Set(people.map((person) => person.prospect_id)).size !== people.length
    )
      invalid();
    for (const key of ["can_edit", "can_confirm"])
      if (row[key] !== undefined && typeof row[key] !== "boolean") invalid();
    return {
      company_id: uuid(row.company_id),
      name,
      revision: row.revision as number,
      origin: row.origin as CompanyRecord["origin"],
      confirmed_at: (row.confirmed_at as string | null | undefined) ?? null,
      can_edit: row.can_edit === true,
      can_confirm: row.can_confirm === true,
      fields: parsed,
      people,
    };
  } catch {
    return invalid();
  }
}

/** Response authority is exact. A role/name never implies a company grant. */
export function parseCompanyList(value: unknown, binding: CompanyReadBinding) {
  const row = record(value);
  if (
    row.schema !== "ac.sales-xray.companies/1" ||
    row.person_id !== binding.personId ||
    row.tenant_id !== binding.tenantId ||
    row.session_id !== binding.sessionId ||
    !Object.values(binding).every((id) => UUID_RE.test(id)) ||
    !Array.isArray(row.companies) ||
    row.companies.length > 20 ||
    !Number.isSafeInteger(row.total) ||
    (row.total as number) < row.companies.length ||
    (row.next_offset !== null &&
      (!Number.isSafeInteger(row.next_offset) ||
        (row.next_offset as number) < 0))
  )
    invalid();
  const companies = row.companies.map(parseCompany);
  if (
    new Set(companies.map((company) => company.company_id)).size !==
    companies.length
  )
    invalid();
  return {
    companies,
    total: row.total as number,
    next_offset: row.next_offset as number | null,
  };
}

export function parseCompanyDetail(
  value: unknown,
  binding: CompanyReadBinding,
  companyId: string,
): CompanyRecord {
  const row = record(value);
  if (
    row.schema !== "ac.sales-xray.company/1" ||
    row.person_id !== binding.personId ||
    row.tenant_id !== binding.tenantId ||
    row.session_id !== binding.sessionId ||
    !Object.values(binding).every((id) => UUID_RE.test(id)) ||
    !UUID_RE.test(companyId)
  )
    invalid();
  const company = parseCompany(row.company);
  if (company.company_id !== companyId) invalid();
  return company;
}
