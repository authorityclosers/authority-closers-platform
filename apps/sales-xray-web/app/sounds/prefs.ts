/**
 * The sound for each moment, kept by the server (/v1/lead-desk/sounds, round-2
 * board 4, 20 Nov 2026): the team's, set by owners, admins and managers, and
 * each person's own. Outside an organisation (a personal workspace) there is no
 * team: the person's own picks stay on this device.
 *
 * What plays is remembered here too, for the moment a lead arrives: the bell
 * plays it at once, without a read (update-notices.tsx).
 */
import { SX_EVENTS, type SxEventId } from "./library";
import { eventById, resolveChoice, type SoundChoice } from "./sounds";

export type SoundRow = {
  id: SxEventId;
  team: SoundChoice;
  mine: SoundChoice | null;
  plays: SoundChoice;
};

export type SoundsView = {
  events: SoundRow[];
  sellers_pick: boolean;
  manager: boolean;
  own_picks: number;
  /** Kept on this device only: a personal workspace has no team. */
  local?: true;
};

export class SoundsError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const BASE = "/v1/lead-desk/sounds";
const LOCAL_KEY = "sx-sounds-mine";
const PLAYS_KEY = "sx-sounds-plays";

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = "That didn’t work. Try again.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The plain words stay.
    }
    throw new SoundsError(detail, response.status);
  }
  return (await response.json()) as T;
}

function readLocal(): Partial<Record<SxEventId, SoundChoice>> {
  try {
    const kept = JSON.parse(
      window.localStorage.getItem(LOCAL_KEY) ?? "{}",
    ) as unknown;
    return kept && typeof kept === "object" ? (kept as never) : {};
  } catch {
    return {};
  }
}

/** A personal workspace's sounds: the library's, with this device's own picks. */
export function localView(): SoundsView {
  const mine = readLocal();
  return {
    events: SX_EVENTS.map((event) => {
      const own = mine[event.id] ?? null;
      const valid = own && resolveChoice(event, own) === own ? own : null;
      return {
        id: event.id,
        team: event.default,
        mine: valid,
        plays: resolveChoice(event, valid),
      };
    }),
    sellers_pick: true,
    manager: false,
    own_picks: 0,
    local: true,
  };
}

/** The page's read; outside an organisation, this device's own. */
export async function readSounds(signal?: AbortSignal): Promise<SoundsView> {
  try {
    return remember(await call<SoundsView>("", { signal }));
  } catch (error) {
    if (
      error instanceof SoundsError &&
      (error.status === 403 || error.status === 404)
    )
      return remember(localView());
    throw error;
  }
}

/** A person's own pick for moments (null: back to the team's). */
export async function saveMine(
  view: SoundsView,
  mine: Partial<Record<SxEventId, SoundChoice | null>>,
): Promise<SoundsView> {
  if (view.local) {
    const kept = { ...readLocal() };
    for (const [id, choice] of Object.entries(mine)) {
      if (choice) kept[id as SxEventId] = choice;
      else delete kept[id as SxEventId];
    }
    try {
      window.localStorage.setItem(LOCAL_KEY, JSON.stringify(kept));
    } catch {
      throw new SoundsError("This device can’t keep it. Try again.", 507);
    }
    return remember(localView());
  }
  return remember(
    await call<SoundsView>("", {
      method: "PUT",
      body: JSON.stringify({ mine }),
    }),
  );
}

/** The team's sounds (owners, admins and managers). */
export async function saveTeam(
  team: Partial<Record<SxEventId, SoundChoice>>,
  sellersPick: boolean,
): Promise<SoundsView> {
  return remember(
    await call<SoundsView>("/team", {
      method: "PUT",
      body: JSON.stringify({ team, sellers_pick: sellersPick }),
    }),
  );
}

// ----- what plays, remembered for the bell ---------------------------------

let plays: Partial<Record<SxEventId, SoundChoice>> | null = null;

function remember(view: SoundsView): SoundsView {
  plays = Object.fromEntries(view.events.map((row) => [row.id, row.plays]));
  try {
    window.localStorage.setItem(PLAYS_KEY, JSON.stringify(plays));
  } catch {
    // Memory still holds it for this visit.
  }
  return view;
}

/** What plays for this moment here: the last read's, else the library's default. */
export function playsFor(id: SxEventId): SoundChoice {
  const event = eventById(id);
  if (!event) return "none";
  if (!plays) {
    try {
      plays = JSON.parse(
        window.localStorage.getItem(PLAYS_KEY) ?? "null",
      ) as typeof plays;
    } catch {
      plays = null;
    }
  }
  const kept = plays && typeof plays === "object" ? plays[id] : null;
  return resolveChoice(event, kept);
}

let refreshed = false;
/** After a bell sound, quietly, once a visit: the picks read again for the next one. */
const REFRESH_AFTER_MS = 5_000;

/** The team's or your own picks may have changed elsewhere: read them again,
    once a visit, a little after a sound played (never on the way to it). */
export function refreshSoundsLater(): void {
  if (refreshed || typeof window === "undefined") return;
  refreshed = true;
  window.setTimeout(() => {
    void readSounds().catch(() => {
      // The last remembered sounds, or the library's, play meanwhile.
    });
  }, REFRESH_AFTER_MS);
}

/** Tests only. */
export function forgetSounds() {
  plays = null;
  refreshed = false;
}
