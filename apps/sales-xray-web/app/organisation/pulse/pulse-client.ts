/**
 * Organisation → Connections → Pulse: the link to the organisation's Pulse org
 * (owner, 25 Oct 2026; contract docs/architecture/pulse-identity-contract.md).
 * Owners and admins only; the API checks the live role on every call.
 */

const API = "/v1/sales-xray/pulse";
const READ: RequestInit = {
  credentials: "same-origin",
  cache: "no-store",
  redirect: "error",
  headers: { accept: "application/json" },
};

export type PulseSharing = {
  directory: "read";
  photos: "read" | "off";
  signals: "off" | "write";
};

export type PulseMember = {
  id: string;
  name: string | null;
  email: string | null;
  title: string | null;
  team: string | null;
  pulseRole: string | null;
  status: string;
  photoUrl: string | null;
  personId: string | null;
  matchedBy: "pulse_sign_in" | "email" | null;
  canInvite: boolean;
  invitedAt: string | null;
};

export type PulseAccess = {
  id: string;
  scopes: string[];
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
};

export type PulseLink = {
  orgName: string | null;
  orgId: string;
  linkedAt: string | null;
  linkedBy: string | null;
  scopes: string[];
  sharing: PulseSharing;
  webhooks: boolean;
  lastSyncAt: string | null;
  lastSync: {
    seen?: number;
    matched?: number;
    missing?: number;
    removed?: number;
    problem?: string;
  };
};

export type PulseState = {
  configured: boolean;
  link: PulseLink | null;
  members: PulseMember[];
  access: PulseAccess[];
};

export class PulseRefusal extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null,
  ) {
    super(message);
  }
}

const text = (value: unknown): string | null =>
  typeof value === "string" && value ? value : null;
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export function parsePulseState(value: unknown): PulseState | null {
  if (!record(value) || value.schema !== "sx-pulse/1") return null;
  const members: PulseMember[] = [];
  for (const raw of Array.isArray(value.members) ? value.members : []) {
    if (!record(raw) || typeof raw.id !== "string") continue;
    members.push({
      id: raw.id,
      name: text(raw.name),
      email: text(raw.email),
      title: text(raw.title),
      team: text(raw.team),
      pulseRole: text(raw.pulse_role),
      status: text(raw.status) ?? "active",
      // Only this API's own photo route is shown.
      photoUrl:
        typeof raw.photo_url === "string" &&
        raw.photo_url.startsWith(`${API}/members/`)
          ? raw.photo_url
          : null,
      personId: text(raw.person_id),
      matchedBy:
        raw.matched_by === "pulse_sign_in" || raw.matched_by === "email"
          ? raw.matched_by
          : null,
      canInvite: raw.can_invite === true,
      invitedAt: text(raw.invited_at),
    });
  }
  const access: PulseAccess[] = [];
  for (const raw of Array.isArray(value.pulse_access)
    ? value.pulse_access
    : []) {
    if (!record(raw) || typeof raw.id !== "string") continue;
    access.push({
      id: raw.id,
      scopes: Array.isArray(raw.scopes)
        ? raw.scopes.filter((item): item is string => typeof item === "string")
        : [],
      createdAt: text(raw.created_at) ?? "",
      lastUsedAt: text(raw.last_used_at),
      revokedAt: text(raw.revoked_at),
    });
  }
  let link: PulseLink | null = null;
  if (record(value.link) && typeof value.link.pulse_org_id === "string") {
    const sharing = record(value.link.sharing) ? value.link.sharing : {};
    const last = record(value.link.last_sync) ? value.link.last_sync : {};
    const count = (key: string) =>
      typeof last[key] === "number" ? (last[key] as number) : undefined;
    link = {
      orgName: text(value.link.pulse_org_name),
      orgId: value.link.pulse_org_id,
      linkedAt: text(value.link.linked_at),
      linkedBy: text(value.link.linked_by),
      scopes: Array.isArray(value.link.scopes)
        ? value.link.scopes.filter(
            (item): item is string => typeof item === "string",
          )
        : [],
      sharing: {
        directory: "read",
        photos: sharing.photos === "off" ? "off" : "read",
        signals: sharing.signals === "write" ? "write" : "off",
      },
      webhooks: value.link.webhooks === true,
      lastSyncAt: text(value.link.last_sync_at),
      lastSync: {
        seen: count("seen"),
        matched: count("matched"),
        missing: count("missing"),
        removed: count("removed"),
        problem: text(last.problem) ?? undefined,
      },
    };
  }
  return { configured: value.configured === true, link, members, access };
}

async function refusal(response: Response): Promise<PulseRefusal> {
  let message = "That didn't work. Try again.";
  let code: string | null = null;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (record(body.detail)) {
      message = text(body.detail.message) ?? message;
      code = text(body.detail.code);
    } else if (typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    // keep the plain words
  }
  return new PulseRefusal(message, response.status, code);
}

async function answer(response: Response): Promise<PulseState> {
  if (!response.ok) throw await refusal(response);
  const state = parsePulseState(await response.json());
  if (!state) throw new PulseRefusal("Pulse answered oddly.", 502, null);
  return state;
}

/** null: Pulse isn't offered here, or this person isn't an owner or admin. */
export async function readPulse(
  signal?: AbortSignal,
): Promise<PulseState | null> {
  const response = await fetch(API, { ...READ, signal });
  if (response.status === 401 || response.status === 403) return null;
  if (response.status === 404) return null;
  return answer(response);
}

function write(body?: unknown, method = "POST"): RequestInit {
  return {
    ...READ,
    method,
    headers: {
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };
}

/** Where to send the owner or admin so a Pulse org admin approves the link. */
export async function startPulseLink(): Promise<string> {
  const response = await fetch(`${API}/connect`, write());
  if (!response.ok) throw await refusal(response);
  const body = (await response.json()) as { redirect_url?: unknown };
  const url = text(body.redirect_url);
  if (!url || !/^https?:\/\//.test(url))
    throw new PulseRefusal("Pulse answered oddly.", 502, null);
  return url;
}

export async function syncPulse(): Promise<PulseState> {
  return answer(await fetch(`${API}/sync`, write()));
}

export async function invitePulseMembers(ids: string[]): Promise<PulseState> {
  return answer(
    await fetch(`${API}/invite`, write({ members: ids })),
  );
}

export async function savePulseSharing(
  sharing: Pick<PulseSharing, "photos" | "signals">,
): Promise<PulseState> {
  return answer(
    await fetch(`${API}/sharing`, write(sharing, "PUT")),
  );
}

export async function unlinkPulse(): Promise<PulseState> {
  return answer(await fetch(`${API}/disconnect`, write()));
}

/** Pulse's own access to Sales X-Ray (its Connect connection), revoked here. */
export async function revokePulseAccess(grantId: string): Promise<void> {
  const response = await fetch(
    `/v1/sales-xray/integrations/connections/${encodeURIComponent(grantId)}/revoke`,
    write(),
  );
  if (!response.ok) throw await refusal(response);
}

/** The words for ?pulse=<outcome> on the way back from Pulse. */
export function pulseReturnNotice(outcome: string | null): {
  tone: "success" | "error";
  title: string;
  message: string;
} | null {
  switch (outcome) {
    case null:
    case "":
      return null;
    case "connected":
      return {
        tone: "success",
        title: "Linked to Pulse",
        message: "Your team's names, photos, titles and teams now come from Pulse.",
      };
    case "linked_sync_failed":
      return {
        tone: "success",
        title: "Linked to Pulse",
        message: "Reading your Pulse members didn't finish. Press Sync now.",
      };
    case "cancelled":
    case "refused":
      return {
        tone: "error",
        title: "Not linked",
        message: "Pulse didn't approve the link. A Pulse org admin must allow it.",
      };
    case "org_taken":
      return {
        tone: "error",
        title: "Not linked",
        message: "That Pulse org is already linked to another organisation.",
      };
    case "expired":
      return {
        tone: "error",
        title: "Not linked",
        message: "The approval took too long. Start again.",
      };
    default:
      return {
        tone: "error",
        title: "Not linked",
        message: "Linking to Pulse didn't finish. Try again.",
      };
  }
}

export type PulsePerson = {
  title: string | null;
  team: string | null;
  photoUrl: string | null;
};

/** Pulse titles, teams and photos of this organisation's people (any member). */
export async function readPulsePeople(
  signal?: AbortSignal,
): Promise<Record<string, PulsePerson>> {
  const response = await fetch(`${API}/people`, { ...READ, signal });
  if (!response.ok) return {};
  const body = (await response.json()) as { people?: unknown };
  const found: Record<string, PulsePerson> = {};
  if (!record(body.people)) return found;
  for (const [personId, raw] of Object.entries(body.people)) {
    if (!record(raw)) continue;
    found[personId] = {
      title: text(raw.title),
      team: text(raw.team),
      photoUrl:
        typeof raw.photo_url === "string" &&
        raw.photo_url.startsWith(`${API}/members/`)
          ? raw.photo_url
          : null,
    };
  }
  return found;
}
