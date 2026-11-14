/**
 * The tester programme's reads and writes (owner, 13 Nov 2026). Our own list
 * says where a person stands; nothing here guesses at Google Group membership.
 *
 * GET  /v1/sales-xray/testers/me  none | waiting | approved | ready | declined
 * POST /v1/sales-xray/testers/me  {phone_model, role, business}: join once
 */
import { TESTERS } from "./testers-config";

export type TesterState =
  | "none"
  | "waiting"
  | "approved"
  | "ready"
  | "declined";
export type TesterRole = "owner" | "manager" | "seller" | "other";

export const ROLES: readonly { key: TesterRole; label: string }[] = [
  { key: "owner", label: "Business owner" },
  { key: "manager", label: "Sales manager" },
  { key: "seller", label: "Salesperson" },
  { key: "other", label: "Other" },
];

export type TesterMe = Readonly<{
  state: TesterState;
  email: string;
  phoneModel: string | null;
  listed: boolean;
}>;

export type TesterRead = TesterMe | "signed_out" | "unavailable";

const PATH = "/v1/sales-xray/testers/me";
const STATES: readonly TesterState[] = [
  "none",
  "waiting",
  "approved",
  "ready",
  "declined",
];

export function parseTesterMe(raw: unknown): TesterMe | null {
  if (typeof raw !== "object" || raw === null) return null;
  const item = raw as Record<string, unknown>;
  const state = item.state;
  if (
    typeof state !== "string" ||
    !(STATES as readonly string[]).includes(state) ||
    typeof item.email !== "string" ||
    !item.email.includes("@")
  )
    return null;
  return {
    state: state as TesterState,
    email: item.email.slice(0, 320),
    phoneModel:
      typeof item.phone_model === "string" && item.phone_model
        ? item.phone_model.slice(0, 80)
        : null,
    listed: item.listed === true,
  };
}

export async function readTesterMe(signal?: AbortSignal): Promise<TesterRead> {
  let response: Response;
  try {
    response = await fetch(PATH, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: { accept: "application/json" },
    });
  } catch {
    return "unavailable";
  }
  if (response.status === 401 || response.status === 403) return "signed_out";
  if (!response.ok) return "unavailable";
  return (
    parseTesterMe(await response.json().catch(() => null)) ?? "unavailable"
  );
}

export type JoinResult =
  | { ok: true; me: TesterMe }
  | { ok: false; message: string };

export async function joinTesters(body: {
  phone_model: string;
  role: TesterRole;
  business: string;
}): Promise<JoinResult> {
  let response: Response;
  try {
    response = await fetch(PATH, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, message: "No connection. Try again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : null;
    return {
      ok: false,
      message:
        typeof detail === "string" && detail.length < 200
          ? detail
          : response.status === 401
            ? "Your sign-in ended. Sign in again."
            : "That didn't go through. Try again.",
    };
  }
  const me = parseTesterMe(payload);
  return me
    ? { ok: true, me }
    : { ok: false, message: "That didn't go through. Try again." };
}

/** Signs out, so the person can join with the Google account their Play Store uses. */
export async function switchAccount(): Promise<void> {
  try {
    await fetch("/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    // The sign-in page still lets them choose.
  }
  window.location.assign(new URL(SIGN_IN, window.location.origin).href);
}

/** Sign in, then come back here. */
export const SIGN_IN = "/login?next=%2Ftesters";

const APP = /\bSalesXrayApp\/\d/;

/** An Android phone's browser, not the Sales X-Ray app itself. */
export function isAndroidBrowser(
  userAgent: string | null | undefined,
): boolean {
  const agent = userAgent ?? "";
  return /\bAndroid\b/i.test(agent) && !APP.test(agent);
}

/**
 * The phone's model for the form, where Chrome tells us (client hints), e.g.
 * "Redmi 13 5G" or "CPH2581". Only a suggestion: the person can change it.
 */
export async function phoneModelHint(): Promise<string | null> {
  const data = (
    navigator as Navigator & {
      userAgentData?: {
        getHighEntropyValues?: (hints: string[]) => Promise<{ model?: string }>;
      };
    }
  ).userAgentData;
  try {
    const values = await data?.getHighEntropyValues?.(["model"]);
    const model = values?.model?.trim();
    return model && model !== "K" ? model.slice(0, 80) : null;
  } catch {
    return null;
  }
}

export const PLAY_STEPS = {
  optIn: TESTERS.optInUrl,
  play: TESTERS.playUrl,
} as const;
