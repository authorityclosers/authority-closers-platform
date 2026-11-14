/**
 * A recording chosen on Reports' upload screen (Dipak's Reports V4 spec,
 * section 18: "Choose audio file", then "the application's existing upload
 * and analysis process") travels to New analysis, which takes it as if it had
 * been chosen there: the same checks, consent and Analyse. Memory only, for
 * one navigation: a reload drops it.
 */

let handed: File | null = null;

export function handOverRecording(file: File): void {
  handed = file;
}

/** The recording waiting for New analysis, once: taking it clears it. */
export function takeHandedRecording(): File | null {
  const file = handed;
  handed = null;
  return file;
}

/** The formats the screen names (section 18); New analysis accepts more. */
export const RECORDING_ACCEPT = "audio/*,.mp3,.wav,.m4a,.ogg,.flac";
export const RECORDING_FORMATS = "MP3 · WAV · M4A · OGG · FLAC";
