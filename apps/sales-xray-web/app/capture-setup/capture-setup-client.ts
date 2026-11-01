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
  /** Finished, but its recordings don't work, or its phone says recording is off (ph1-46). */
  | "recording_off"
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
  /** Every phone they finished on, newest first, by name (ph1-46). */
  phones?: readonly string[];
  /** Their connected lead calls today with no recording (owner, fix 5). */
  missing_today?: number;
  /** The phone, by name, with work-call logging off: Connections' rule (ph1-23). */
  call_log_off?: string | null;
  /** Recording on this seller's phone (competitor teardown #7). */
  recording?: CaptureRecording | null;
  /** Each of their phones, newest first, with its own recording (ph1-55, ph1-46). */
  devices?: readonly CaptureTeamDevice[];
}>;

export type CaptureTeamDevice = Readonly<{
  /** The install's own id, never a number. */
  device: string | null;
  name: string;
  recording: CaptureRecording | null;
  call_log_off: boolean;
}>;

/** "ok": a recording lately; "late": none lately, or none yet; "off": no folder or recorder. */
export type CaptureRecording = Readonly<{
  state: "ok" | "late" | "off";
  last_at: string | null;
  fix: "folder" | "recorder" | "test" | null;
  /** The phone this is about, by name (a seller can have two, ph1-46). */
  phone?: string;
}>;

export type CaptureTeam = Readonly<{
  people: CaptureTeamRow[];
  /** Everyone's connected lead calls today with no recording. */
  missingToday: number;
}>;

/** One connected call with no recording: its lead, when and how long (never a number). */
export type MissingCall = Readonly<{
  event_id: string;
  lead_id: string;
  lead_name: string | null;
  at: string;
  seconds: number;
}>;

/** The seller's own connected lead calls today with no recording after two minutes. */
export type MissingRecordings = Readonly<{
  calls: number;
  /** Calls the seller tried today, as Home counts them (its Tried). */
  tried: number;
  latest_at: string | null;
  /** The calls themselves, newest first (competitor teardown #13). */
  items: MissingCall[];
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
  "recording_off",
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
    people: body.people
      .filter(
        (row): row is CaptureTeamRow =>
          record(row) &&
          typeof row.person_id === "string" &&
          typeof row.name === "string" &&
          TEAM_STATES.includes(String(row.state)),
      )
      .map((row) => ({
        ...row,
        phones: Array.isArray(row.phones)
          ? row.phones.filter(
              (name): name is string => typeof name === "string",
            )
          : row.phone
            ? [row.phone]
            : [],
        devices: Array.isArray(row.devices)
          ? row.devices.filter(
              (device): device is CaptureTeamDevice =>
                record(device) && typeof device.name === "string",
            )
          : [],
      })),
    missingToday: count(body.missing_today),
  };
}

export function parseMissing(body: unknown): MissingRecordings {
  if (!record(body) || body.schema !== "sales-xray-missing-recordings/1")
    throw new Error("Calls without recordings could not be read.");
  const items = Array.isArray(body.items) ? body.items.filter(record) : [];
  return {
    calls: count(body.calls),
    tried: count(body.tried),
    latest_at: typeof body.latest_at === "string" ? body.latest_at : null,
    items: items.flatMap((item) =>
      typeof item.event_id === "string" &&
      typeof item.lead_id === "string" &&
      typeof item.at === "string"
        ? [
            {
              event_id: item.event_id,
              lead_id: item.lead_id,
              lead_name:
                typeof item.lead_name === "string" ? item.lead_name : null,
              at: item.at,
              seconds: count(item.seconds),
            },
          ]
        : [],
    ),
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

/** This phone's newest call recording, for Team's line (never the file or a number). */
export async function reportRecordingHealth(report: {
  device: string;
  newest_recording_at: string | null;
}): Promise<void> {
  const response = await fetch(`${CAPTURE_SETUP_PATH}/recording-health`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(report),
  });
  if (!response.ok) throw new Error("Recording health not sent.");
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

/**
 * The seller's own calls with no recording (the line on Calls and Reports):
 * today, or one India day, "2026-10-30" (the bell's reminder, ph1-27).
 */
export async function readMissingRecordings(
  signal?: AbortSignal,
  day?: string,
): Promise<MissingRecordings> {
  const path = day ? `/missing/${encodeURIComponent(day)}` : "/missing";
  return answer(
    await fetch(`${CAPTURE_SETUP_PATH}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { accept: "application/json" },
      signal,
    }),
    parseMissing,
  );
}
