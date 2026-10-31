/**
 * Call capture setup (owner, 30 Oct 2026; server: call_ai/capture_setup.py). The
 * server says whether the steps are required here, where the seller's profile and
 * consent stand, when a no is asked again, and which phones finished. Agreeing is
 * the standing consent (auto-analysis-client.ts); this API records only a finished
 * phone or a no.
 */

export type CaptureConsent = "on" | "off" | "ask" | "unavailable";

export type CaptureSetupPhone = Readonly<{
  /** The install's own id (setupStatus().device), never a phone number. */
  device: string;
  model: string;
  app_version: string;
  at: string;
  recordings: boolean;
  background: boolean;
  uploads: boolean;
}>;

export type CaptureSetup = Readonly<{
  schema: "sales-xray-capture-setup/1";
  workspace: "organisation" | "personal";
  /** Sellers in an organisation (owner, admin, manager, member). */
  required: boolean;
  /** Name and phone, as the upload's write-eligibility check reads them. */
  profile_complete?: boolean;
  consent: CaptureConsent;
  consent_since?: string | null;
  /** The last no: at the disclosure, or turning the consent off in Privacy. */
  declined_at: string | null;
  ask_again_at: string | null;
  phones: readonly CaptureSetupPhone[];
  /** This person's installs that finished setup in any workspace (ph2-15). */
  finished_devices?: readonly string[];
}>;

export type CaptureTeamState =
  | "set_up"
  | "phone_pending"
  | "declined"
  | "turned_off"
  | "consent_changed"
  | "not_started";

export type CaptureTeamRow = Readonly<{
  person_id: string;
  name: string;
  role: string;
  state: CaptureTeamState;
  at: string | null;
  phone: string | null;
  /** Their connected lead calls today with no recording (owner, fix 5). */
  missing_today?: number;
}>;

export type CaptureTeam = Readonly<{
  people: CaptureTeamRow[];
  /** Everyone's connected lead calls today with no recording. */
  missingToday: number;
}>;

/** The seller's own connected lead calls today with no recording after two minutes. */
export type MissingRecordings = Readonly<{
  calls: number;
  /** Calls the seller tried today, as Home counts them (its Tried). */
  tried: number;
  latest_at: string | null;
}>;

export type CaptureFinishedPhone = Readonly<{
  device: string;
  model: string;
  family: string;
  app_version: string;
  recordings: boolean;
  background: boolean;
  uploads: boolean;
}>;

export const CAPTURE_SETUP_PATH = "/v1/sales-xray/call-ai/capture-setup";

const CONSENTS = ["on", "off", "ask", "unavailable"];
const TEAM_STATES = [
  "set_up",
  "phone_pending",
  "declined",
  "turned_off",
  "consent_changed",
  "not_started",
];

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const moment = (value: unknown) => value === null || typeof value === "string";
const count = (value: unknown) =>
  typeof value === "number" && Number.isInteger(value) && value > 0 ? value : 0;

export function parseCaptureSetup(body: unknown): CaptureSetup {
  if (
    !record(body) ||
    body.schema !== "sales-xray-capture-setup/1" ||
    (body.workspace !== "organisation" && body.workspace !== "personal") ||
    typeof body.required !== "boolean" ||
    !CONSENTS.includes(String(body.consent)) ||
    !moment(body.declined_at) ||
    !moment(body.ask_again_at) ||
    !Array.isArray(body.phones)
  )
    throw new Error("Call capture setup could not be read.");
  const phones = body.phones.filter(
    (phone): phone is CaptureSetupPhone =>
      record(phone) &&
      typeof phone.device === "string" &&
      typeof phone.at === "string",
  );
  const finished = Array.isArray(body.finished_devices)
    ? body.finished_devices.filter(
        (device): device is string => typeof device === "string",
      )
    : [];
  return { ...(body as CaptureSetup), phones, finished_devices: finished };
}

export function parseCaptureTeam(body: unknown): CaptureTeam {
  if (
    !record(body) ||
    body.schema !== "sales-xray-capture-setup-team/1" ||
    !Array.isArray(body.people)
  )
    throw new Error("Call capture could not be read.");
  return {
    people: body.people.filter(
      (row): row is CaptureTeamRow =>
        record(row) &&
        typeof row.person_id === "string" &&
        typeof row.name === "string" &&
        TEAM_STATES.includes(String(row.state)),
    ),
    missingToday: count(body.missing_today),
  };
}

export function parseMissing(body: unknown): MissingRecordings {
  if (!record(body) || body.schema !== "sales-xray-missing-recordings/1")
    throw new Error("Calls without recordings could not be read.");
  return {
    calls: count(body.calls),
    tried: count(body.tried),
    latest_at: typeof body.latest_at === "string" ? body.latest_at : null,
  };
}

async function answer<T>(
  response: Response,
  parse: (body: unknown) => T,
): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw Object.assign(
      new Error(
        typeof body?.detail === "string"
          ? body.detail
          : "Not saved. Try again.",
      ),
      { status: response.status },
    );
  }
  return parse(await response.json());
}

export async function readCaptureSetup(
  signal?: AbortSignal,
): Promise<CaptureSetup> {
  return answer(
    await fetch(CAPTURE_SETUP_PATH, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal,
    }),
    parseCaptureSetup,
  );
}

/** A phone finished, or a no at the disclosure. One key per tap. */
export async function recordCaptureSetup(
  choice:
    | { outcome: "completed"; phone: CaptureFinishedPhone }
    | { outcome: "declined" },
  key: string = crypto.randomUUID(),
): Promise<CaptureSetup> {
  return answer(
    await fetch(CAPTURE_SETUP_PATH, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify(choice),
    }),
    parseCaptureSetup,
  );
}

/** Each seller's state, for owners, admins and managers (Team). */
export async function readCaptureTeam(
  signal?: AbortSignal,
): Promise<CaptureTeam> {
  return answer(
    await fetch(`${CAPTURE_SETUP_PATH}/team`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal,
    }),
    parseCaptureTeam,
  );
}

/** The seller's own calls today with no recording (the recording check banner). */
export async function readMissingRecordings(
  signal?: AbortSignal,
): Promise<MissingRecordings> {
  return answer(
    await fetch(`${CAPTURE_SETUP_PATH}/missing`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal,
    }),
    parseMissing,
  );
}
