export const ACCOUNT_PROFILE_PATH = "/v1/me/sales-xray-profile";
export const ACCOUNT_PROFILE_ELIGIBILITY_PATH =
  "/v1/me/sales-xray-profile/write-eligibility";

export type AccountProfileRecord = Readonly<{
  name: string | null;
  email: string;
  phone_number_e164: string | null;
  phone_verified: boolean;
  profile_complete: boolean;
  revision: number;
}>;

export type AccountProfileUpdate = Readonly<{
  full_name: string;
  phone_number_e164: string;
  expected_revision: number;
}>;

export type AccountProfileEligibility =
  | "eligible"
  | "unauthenticated"
  | "not_ready";

export class AccountProfileRequestError extends Error {
  constructor(
    readonly status: number,
    message = "profile_request_failed",
  ) {
    super(message);
    this.name = "AccountProfileRequestError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseProfile(value: unknown): AccountProfileRecord {
  if (
    !isRecord(value) ||
    !(typeof value.name === "string" || value.name === null) ||
    typeof value.email !== "string" ||
    !(
      typeof value.phone_number_e164 === "string" ||
      value.phone_number_e164 === null
    ) ||
    typeof value.phone_verified !== "boolean" ||
    typeof value.profile_complete !== "boolean" ||
    !Number.isSafeInteger(value.revision) ||
    Number(value.revision) < 0
  ) {
    throw new Error("invalid_profile_response");
  }
  return value as AccountProfileRecord;
}

export async function readAccountProfile(
  signal?: AbortSignal,
): Promise<AccountProfileRecord> {
  const response = await fetch(ACCOUNT_PROFILE_PATH, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new AccountProfileRequestError(response.status);
  return parseProfile(await response.json());
}

export async function updateAccountProfile(
  input: AccountProfileUpdate,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(ACCOUNT_PROFILE_PATH, {
    method: "PUT",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(input),
    signal,
  });
  if (!response.ok) throw new AccountProfileRequestError(response.status);
}

export async function readAccountProfileEligibility(
  signal?: AbortSignal,
): Promise<AccountProfileEligibility> {
  const response = await fetch(ACCOUNT_PROFILE_ELIGIBILITY_PATH, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
    signal,
  });
  if (response.status === 204) return "eligible";
  if (response.status === 401) return "unauthenticated";
  if (response.status === 403) return "not_ready";
  throw new AccountProfileRequestError(response.status);
}

export function validE164Phone(value: string): boolean {
  return /^\+[1-9][0-9]{6,14}$/.test(value);
}

/** Normalize the supported Indian national format and formatted international numbers. */
export function normalizeProfilePhoneInput(
  value: string,
  country: "IN" | "US" | "CA" | "GB" | "AU" | "AE" | "OTHER",
): string {
  const compact = value.trim().replace(/[\s().-]/g, "");
  if (country === "IN" && /^[0-9]{10}$/.test(compact)) return `+91${compact}`;
  return compact;
}
