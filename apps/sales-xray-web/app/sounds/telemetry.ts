/**
 * What people pick and what really plays (brand kit SOUND-PICKER.md:
 * sound.picked, sound.previewed and sound.played, here sx.sound_*): a moment
 * and a pack, never a file. A play is sent one time in ten.
 */
import { inPhoneApp } from "../leads/native-phone";
import { track, type SoundPackName } from "../telemetry";
import type { SxEventId } from "./library";
import { NONE, parseSound, SYSTEM, type SoundChoice } from "./sounds";

const PLAYED_SHARE = 0.1;

function packOf(choice: SoundChoice): SoundPackName | null {
  if (choice === NONE || choice === SYSTEM) return choice;
  return (parseSound(choice)?.pack as SoundPackName | undefined) ?? null;
}

export function soundPicked(
  event: SxEventId,
  choice: SoundChoice,
  scope: "me" | "team" | "phone",
): void {
  const pack = packOf(choice);
  if (pack) track("sx.sound_picked", { event, pack, scope });
}

export function soundPreviewed(
  event: SxEventId | undefined,
  choice: SoundChoice,
): void {
  const pack = packOf(choice);
  if (pack) track("sx.sound_previewed", event ? { event, pack } : { pack });
}

export function soundPlayed(
  event: SxEventId,
  choice: SoundChoice,
  sample: number = Math.random(),
): void {
  if (sample >= PLAYED_SHARE) return;
  const pack = packOf(choice);
  if (!pack) return;
  const app = inPhoneApp();
  const platform =
    app && /iPhone|iPad|iPod/.test(navigator.userAgent)
      ? "ios"
      : app
        ? "android"
        : "web";
  track("sx.sound_played", { event, pack, platform });
}
