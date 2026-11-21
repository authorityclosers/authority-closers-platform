/**
 * Sound choices (brand kit sound/SOUND-PICKER.md): a choice is a library sound
 * id ("glass-v2.mention"), "none" or "system" (the phone's own sound), never a
 * file or an address. What plays: the person's own, else the team's, else the
 * library's default. Pure.
 */
import {
  FAMILIES,
  KINDS,
  PACKS,
  SX_EVENTS,
  type PackFamily,
  type SoundEvent,
  type SoundKind,
  type SxEventId,
} from "./library";

export type SoundChoice = string;
export const NONE = "none";
export const SYSTEM = "system";

const packOf = new Map(PACKS.map((pack) => [pack.id, pack]));

export function eventById(id: string): SoundEvent | undefined {
  return SX_EVENTS.find((event) => event.id === id);
}

export function isSxEvent(id: string): id is SxEventId {
  return eventById(id) !== undefined;
}

/** A library sound's pack and kind, or null for none, the phone's own or a stranger. */
export function parseSound(
  id: string,
): { pack: string; kind: SoundKind } | null {
  const dot = id.lastIndexOf(".");
  if (dot <= 0) return null;
  const pack = id.slice(0, dot);
  const kind = id.slice(dot + 1) as SoundKind;
  if (!packOf.has(pack) || !(kind in KINDS)) return null;
  return { pack, kind };
}

/** Whether this choice may play for this moment: none, the phone's own, or its kind. */
export function validFor(event: SoundEvent, choice: unknown): boolean {
  if (choice === NONE || choice === SYSTEM) return true;
  if (typeof choice !== "string") return false;
  return parseSound(choice)?.kind === event.kind;
}

/** What plays: mine, else the team's, else the library default. */
export function resolveChoice(
  event: SoundEvent,
  mine?: SoundChoice | null,
  team?: SoundChoice | null,
): SoundChoice {
  if (mine && validFor(event, mine)) return mine;
  if (team && validFor(event, team)) return team;
  return event.default;
}

/** "Glass V2 · Mention", "None", "Phone default". */
export function choiceLabel(choice: SoundChoice): string {
  if (choice === NONE) return "None";
  if (choice === SYSTEM) return "Phone default";
  const sound = parseSound(choice);
  if (!sound) return "Phone default";
  return `${packOf.get(sound.pack)?.title} · ${KINDS[sound.kind].label}`;
}

/** The pack's name alone ("Glass V2"), for a short line. */
export function packTitle(choice: SoundChoice): string | null {
  const sound = parseSound(choice);
  return sound ? (packOf.get(sound.pack)?.title ?? null) : null;
}

export type SoundGroup = {
  family: PackFamily;
  label: string;
  sounds: { id: string; label: string }[];
};

/** Every sound of this kind, grouped by family (Glass, Warm, Pulse, Synth). */
export function soundsOfKind(kind: SoundKind): SoundGroup[] {
  return FAMILIES.map(({ id: family, label }) => ({
    family,
    label,
    sounds: PACKS.filter((pack) => pack.family === family).map((pack) => ({
      id: `${pack.id}.${kind}`,
      label: `${pack.title} · ${KINDS[kind].label}`,
    })),
  }));
}

/**
 * The web file of a library sound: its MP3, which every browser and the phone
 * app's web view plays. The library's Opus .webm isn't shipped: public/ goes
 * whole into every web build and the phone bundle, which carries no .webm (a
 * guard in ask-dipak/lesson-video.test.tsx), and one format keeps it 3.2 MB.
 */
export function soundFiles(choice: SoundChoice): { mp3: string } | null {
  const sound = parseSound(choice);
  if (!sound) return null;
  return { mp3: `/sounds/${sound.pack}/${sound.kind}.mp3` };
}

/** Only the ringtone loops (sound/AGENTS.md rule 4). */
export const loops = (choice: SoundChoice) =>
  parseSound(choice)?.kind === "ringtone";
