import {
  COMPANIES_API,
  readCompany,
  readCompanyResponseBody,
} from "./prospect-company-client";
import {
  COMPANY_FIELDS,
  type CompanyFieldKey,
  type CompanyReadBinding,
  type CompanyRecord,
} from "./prospect-company-contract";
import { UUID_RE } from "./prospects-client";

type HumanValue =
  | { kind: "text"; text: string }
  | { kind: "unknown"; reason: "not_asked" | "not_mentioned" };
export type CompanySave =
  | { status: "saved"; binding: CompanyReadBinding; company: CompanyRecord }
  | { status: "invalid" | "conflict" | "unconfirmed"; message: string };

function humanFields(
  raw: unknown,
): Partial<Record<CompanyFieldKey, HumanValue>> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("invalid_company_fields");
  const entries = Object.entries(raw);
  if (!entries.length || entries.length > 4)
    throw new Error("invalid_company_fields");
  return Object.fromEntries(
    entries.map(([key, rawValue]) => {
      if (
        !Object.hasOwn(COMPANY_FIELDS, key) ||
        !rawValue ||
        typeof rawValue !== "object" ||
        Array.isArray(rawValue) ||
        Object.keys(rawValue).length !== 2
      )
        throw new Error("invalid_company_field");
      const value = rawValue as Record<string, unknown>;
      if (
        value.kind === "text" &&
        typeof value.text === "string" &&
        value.text.trim() &&
        !value.text.includes("\0") &&
        value.text.length <= (key === "name" ? 160 : 2048)
      )
        return [key, { kind: "text", text: value.text }];
      if (
        key !== "name" &&
        value.kind === "unknown" &&
        (value.reason === "not_asked" || value.reason === "not_mentioned")
      )
        return [key, { kind: "unknown", reason: value.reason }];
      throw new Error("invalid_company_value");
    }),
  );
}

/**
 * Prepared explicit Company command; no route, provider or automatic retry.
 * Server permissions remain authoritative. Only a pinned, locked read-back
 * acknowledges the save; an uncertain response must be reloaded first.
 */
export async function saveCompanyFields(
  binding: CompanyReadBinding,
  companyId: string,
  expectedRevision: number,
  values: unknown,
  options: { signal?: AbortSignal; deadlineMs?: number } = {},
): Promise<CompanySave> {
  const scope = { ...binding };
  let fields: Partial<Record<CompanyFieldKey, HumanValue>>, body: string;
  try {
    if (
      ![scope.personId, scope.tenantId, scope.sessionId, companyId].every(
        (id) => typeof id === "string" && UUID_RE.test(id),
      ) ||
      !Number.isSafeInteger(expectedRevision) ||
      expectedRevision < 1
    )
      throw new Error("invalid_company_command");
    fields = humanFields(values);
    body = JSON.stringify({ fields, expected_revision: expectedRevision });
    if (new TextEncoder().encode(body).byteLength > 40000)
      throw new Error("invalid_company_command");
  } catch {
    return {
      status: "invalid",
      message: "Supply a current company and valid field values.",
    };
  }
  let conflict = false;
  const result = await readCompany(scope, companyId, {
    ...options,
    reader: async (_, signal) => {
      const response = await fetch(
        COMPANIES_API + "/" + companyId + "/fields",
        {
          method: "PUT",
          credentials: "same-origin",
          redirect: "error",
          cache: "no-store",
          signal,
          headers: {
            accept: "application/json",
            "content-type": "application/json",
          },
          body,
        },
      );
      if (response.status === 409) conflict = true;
      if (response.status !== 200) throw new Error("company_save_rejected");
      return readCompanyResponseBody(response);
    },
  });
  if (
    result.status === "ready" &&
    result.data.revision >= expectedRevision &&
    Object.entries(fields).every(([key, requested]) => {
      const field = result.data.fields[key as CompanyFieldKey];
      return (
        field.basis === "person" &&
        field.locked === true &&
        (requested.kind === "text"
          ? field.state === "known" &&
            field.value.kind === "text" &&
            field.value.text === requested.text
          : field.state === "unknown" && field.reason === requested.reason)
      );
    })
  )
    return { status: "saved", binding: result.binding, company: result.data };
  return conflict
    ? {
        status: "conflict",
        message: "Company information changed. Reload before saving again.",
      }
    : {
        status: "unconfirmed",
        message:
          "This save could not be confirmed. Reload before saving again.",
      };
}
