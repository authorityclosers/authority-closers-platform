import { autoCaptureSetup, autoCaptureStatus } from "../leads/native-phone";

/**
 * Agreeing again after the upload terms changed (SX-AUTOUPLOAD, production 16 Nov 2026: the provider switch made
 * every phone stop its uploads, and agreeing again left them stopped). When this phone stopped its uploads for that
 * reason only, turning them back on follows the agreement: Android shows its own Turn on words first. A seller who
 * turned uploads off themselves is left as they chose. Used wherever the agreement is given: Settings → Privacy and
 * the after-call ask (lead sheet); Call uploads turns the phone on itself.
 */
export async function resumeAfterAgreeing(): Promise<void> {
  const status = await autoCaptureStatus();
  if (!status?.supported || status.on) return;
  if (status.health !== "consent" && status.health !== "terms") return;
  try {
    await autoCaptureSetup(true, status.wifiOnly);
  } catch {
    // Not now, or the profile is incomplete: Settings → Call uploads says what is left.
  }
}
