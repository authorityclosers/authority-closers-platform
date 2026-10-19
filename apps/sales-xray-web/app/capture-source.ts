/**
 * How a recording from the phone was captured (ADR 0056 F2): sent with its upload
 * as X-Capture-Source and stored on the call. The phone knows (its recordings list
 * says "dialer", "in_app" or "accessibility"); the upload only has a File, so the
 * phone side leaves a note for that file (name + size) in sessionStorage.
 * sx-phone.js in the Android app writes the same key.
 */

export type CaptureSource =
  | "android_dialer_pickup"
  | "android_in_app_recorder"
  | "android_call_recorder";

const FROM_PHONE: Record<string, CaptureSource> = {
  dialer: "android_dialer_pickup",
  in_app: "android_in_app_recorder",
  accessibility: "android_call_recorder",
};
const KNOWN = new Set<string>(Object.values(FROM_PHONE));

const key = (file: { name: string; size: number }) =>
  `sx.capture:${file.name}:${file.size}`;

/** The phone's own word for how it captured a recording, as a capture source. */
export function fromPhone(captured: unknown): CaptureSource | null {
  return typeof captured === "string" ? (FROM_PHONE[captured] ?? null) : null;
}

export function rememberCapture(
  file: { name: string; size: number },
  source: CaptureSource | null,
): void {
  if (!source) return;
  try {
    sessionStorage.setItem(key(file), source);
  } catch {
    /* no storage: the call is saved without a capture source */
  }
}

/** The upload header for this file, when the phone left a note for it. */
export function captureHeader(file: {
  size: number;
  name?: string;
}): Record<string, string> {
  if (!file.name) return {};
  try {
    const value = sessionStorage.getItem(
      key({ name: file.name, size: file.size }),
    );
    return value && KNOWN.has(value) ? { "X-Capture-Source": value } : {};
  } catch {
    return {};
  }
}
