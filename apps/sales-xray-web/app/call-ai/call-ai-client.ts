/**
 * AI on calls (owner, 21 Oct 2026): how much AI runs on each seller's recorded
 * calls. /v1/sales-xray/call-ai. Every member can read the levels; only the
 * organisation's owners and admins change them, and the server enforces them
 * before any paid step whatever this page shows.
 *
 * Reads keep the fields the screens use and drop anything malformed, so a new
 * API field never breaks the page.
 */

import { displayName } from "../display-name";

const API = "/v1/sales-xray/call-ai";

export type CallAiLevel = "off" | "data_only" | "auto" | "full";

export const CALL_AI_LEVELS: readonly CallAiLevel[] = [
  "off",
  "data_only",
  "auto",
  "full",
];

export const LEVEL_NAMES: Record<CallAiLevel, string> = {
  off: "Off",
  data_only: "Data only",
  auto: "Auto",
  full: "Full",
};

/** The same words the API sends, for when its list is missing. */
const LEVEL_HINTS: Record<CallAiLevel, string> = {
  off: "Calls are saved and logged on the lead. No AI reads them.",
  data_only:
    "Transcript and lead facts for the CRM, WhatsApp and automations. No report or coaching.",
  auto: "Sales X-Ray picks per call. Until call types arrive, every call gets the full report.",
  full: "The full report and coaching on every call.",
};

export type CallAiPerson = {
  person_id: string;
  name: string;
  level: CallAiLevel;
};

export type CallAiSettings = {
  revision: number | null;
  default: CallAiLevel;
  people: CallAiPerson[];
  you: { level: CallAiLevel; source: "person" | "organisation" };
  levels: { id: CallAiLevel; name: string; hint: string }[];
  can_edit: boolean;
};

export class CallAiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "CallAiError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in to see this.",
  403: "Only the organisation's owners and admins can change AI on calls.",
  404: "That person is not in this organisation.",
  409: "Someone changed these settings. Open them again.",
  422: "Choose Off, Data only, Auto or Full.",
};

export const isLevel = (value: unknown): value is CallAiLevel =>
  typeof value === "string" &&
  (CALL_AI_LEVELS as readonly string[]).includes(value);

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

/** The settings the screens use; anything malformed falls back to "Full", as the server does. */
export function parseCallAi(value: unknown): CallAiSettings {
  const item = record(value);
  const people = Array.isArray(item.people) ? item.people : [];
  const you = record(item.you);
  const levels = Array.isArray(item.levels) ? item.levels : [];
  const parsedLevels = levels
    .map(record)
    .filter((level) => isLevel(level.id))
    .map((level) => ({
      id: level.id as CallAiLevel,
      name:
        typeof level.name === "string"
          ? level.name
          : LEVEL_NAMES[level.id as CallAiLevel],
      hint:
        typeof level.hint === "string"
          ? level.hint
          : LEVEL_HINTS[level.id as CallAiLevel],
    }));
  return {
    revision:
      typeof item.revision === "number" && Number.isInteger(item.revision)
        ? item.revision
        : null,
    default: isLevel(item.default) ? item.default : "full",
    people: people
      .map(record)
      .filter(
        (person) =>
          typeof person.person_id === "string" && isLevel(person.level),
      )
      .map((person) => ({
        person_id: person.person_id as string,
        name:
          typeof person.name === "string"
            ? displayName(person.name)
            : "A seller",
        level: person.level as CallAiLevel,
      })),
    you: {
      level: isLevel(you.level) ? you.level : "full",
      source: you.source === "person" ? "person" : "organisation",
    },
    levels: parsedLevels.length
      ? parsedLevels
      : CALL_AI_LEVELS.map((id) => ({
          id,
          name: LEVEL_NAMES[id],
          hint: LEVEL_HINTS[id],
        })),
    can_edit: item.can_edit === true,
  };
}

/** One seller's level and where it comes from. */
export function levelFor(
  settings: CallAiSettings,
  personId: string,
): { level: CallAiLevel; own: boolean } {
  const own = settings.people.find((person) => person.person_id === personId);
  return own
    ? { level: own.level, own: true }
    : { level: settings.default, own: false };
}

async function request(path: string, init: RequestInit = {}) {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new CallAiError("Sales Xray isn't answering. Try again.", 0);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new CallAiError(
      detail ?? FALLBACK[response.status] ?? "Something went wrong. Try again.",
      response.status,
    );
  }
  return parseCallAi(await response.json());
}

const put = (body: unknown): RequestInit => ({
  method: "PUT",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const readCallAi = (signal?: AbortSignal) => request("", { signal });

export const saveCallAiDefault = (
  revision: number | null,
  level: CallAiLevel,
) => request("/default", put({ expected_revision: revision, level }));

/** One seller's own level; null puts them back on the organisation's default. */
export const saveCallAiPerson = (
  revision: number | null,
  personId: string,
  level: CallAiLevel | null,
) =>
  request(
    `/people/${encodeURIComponent(personId)}`,
    put({ expected_revision: revision, level }),
  );
